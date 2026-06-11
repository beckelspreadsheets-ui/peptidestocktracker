"""Catch-all monitor for configured page/RSS sources no other family claims.

Any ``type: page`` or ``type: rss`` entry in ``sources.yaml`` that the fda,
clinicaltrials, or company_pages families do not claim is watched here, so a
newly configured source can never be silently unmonitored. Pages get
content-hash change detection; feeds get one document per entry. Events fire
only when the content matches configured peptide/keyword terms.
"""

from __future__ import annotations

import hashlib
from pathlib import Path

import feedparser

from peptide_watch.config import SourceConfig, WatchConfig, load_config
from peptide_watch.cursors import get_cursor, save_cursor, touch_cursor
from peptide_watch.database import init_db
from peptide_watch.events import ad_hoc_run_id
from peptide_watch.sources.company_documents import (
    CompanyMonitorScanResult,
    build_company_document,
    open_connection,
    write_company_document,
)
from peptide_watch.sources.company_pages import (
    CompanyPageClient,
    _is_company_page_source,
)

PARSER_VERSION = 1
WATCHED_SOURCE_ID_PREFIX = "watched"


def is_watched_source(source_id: str, source: SourceConfig) -> bool:
    if source.type not in {"page", "rss"}:
        return False
    if source_id.startswith(("fda_", "clinicaltrials")):
        return False
    return not _is_company_page_source(source_id, source)


def selected_watched_sources(
    config: WatchConfig, source_ids: list[str] | None = None
) -> dict[str, SourceConfig]:
    available = {
        source_id: source
        for source_id, source in config.sources.items()
        if is_watched_source(source_id, source)
    }
    if not source_ids:
        return available
    missing = sorted(set(source_ids) - set(available))
    if missing:
        raise ValueError(f"unknown watched source ids: {', '.join(missing)}")
    return {source_id: available[source_id] for source_id in source_ids}


def scan_watched_pages(
    db_path: str | Path,
    *,
    config_dir: str | Path = "config",
    client: CompanyPageClient | None = None,
    source_ids: list[str] | None = None,
    run_id: str | None = None,
) -> CompanyMonitorScanResult:
    """Watch otherwise-unclaimed page/RSS sources for content changes.

    Each source fails independently; a source's writes are one transaction.
    """

    config = load_config(config_dir)
    selected = selected_watched_sources(config, source_ids)
    page_client = client or CompanyPageClient()
    run_id = run_id or ad_hoc_run_id()

    init_db(db_path)
    connection = open_connection(db_path)
    fetched = stored = inserted = changed = events_created = 0
    errors: list[str] = []
    try:
        for source_id, source in selected.items():
            try:
                cursor = get_cursor(connection, source_id)
                fetched_page = page_client.fetch(
                    source.url,
                    etag=cursor.etag if cursor else None,
                    last_modified=cursor.last_modified if cursor else None,
                )
                fetched += 1
                if fetched_page.not_modified:
                    touch_cursor(connection, source_id)
                    connection.commit()
                    continue
                documents = _normalize_watched_source(source_id, source, fetched_page, config)
                for document in documents:
                    result = write_company_document(connection, document, run_id=run_id)
                    stored += 1
                    inserted += int(result.inserted)
                    changed += int(result.changed)
                    events_created += result.events_created
                save_cursor(
                    connection,
                    source_id,
                    etag=fetched_page.etag,
                    last_modified=fetched_page.last_modified,
                )
                connection.commit()
            except (KeyboardInterrupt, SystemExit):
                raise
            except Exception as exc:
                connection.rollback()
                errors.append(f"{source_id}: {exc}")
    except BaseException:
        connection.rollback()
        connection.close()
        raise
    else:
        connection.close()

    if errors and stored == 0 and selected:
        raise RuntimeError(f"Watched page scan failed for all sources: {'; '.join(errors[:5])}")

    return CompanyMonitorScanResult(
        fetched=fetched,
        stored=stored,
        inserted=inserted,
        changed=changed,
        events_created=events_created,
        source_ids=list(selected),
        errors=errors,
    )


def _normalize_watched_source(source_id, source, fetched_page, config):
    """One document per feed entry for feeds; a single page document for pages.

    A source declared ``type: rss`` is always parsed as a feed — an empty feed
    yields nothing (not an HTML page). Auto-detected XML on a ``type: page``
    source is also treated as a feed when it has entries.
    """

    is_feed = source.type == "rss" or "xml" in fetched_page.content_type.lower()
    if is_feed:
        parsed = feedparser.parse(fetched_page.body)
        if parsed.entries:
            return [
                _feed_entry_document(source_id, source, entry, config)
                for entry in parsed.entries
            ]
        if source.type == "rss":
            return []  # explicitly a feed; an empty feed has nothing to store
    return [_page_document(source_id, source, fetched_page, config)]


def _feed_entry_document(source_id, source, entry, config):
    link = str(entry.get("link") or source.url)
    entry_key = entry.get("id") or link or entry.get("title", "")
    digest = hashlib.sha256(str(entry_key).encode("utf-8")).hexdigest()[:16]
    text_parts = [str(entry.get("title", "")), str(entry.get("summary", ""))]
    published = str(entry.get("published", "") or entry.get("updated", ""))
    if published:
        text_parts.append(published)
    return build_company_document(
        document_key=f"{WATCHED_SOURCE_ID_PREFIX}:{source_id}:{digest}",
        source_id=source_id,
        source_type="watched_feed_item",
        url=link,
        title=str(entry.get("title")) or None,
        company_key=source.company_id,
        source_tier=source.tier,
        content_text=" ".join(part for part in text_parts if part),
        config=config,
        metadata={"configured_url": source.url, "published": published},
        raw_content=str(entry).encode("utf-8"),
        parser_version=PARSER_VERSION,
    )


def _page_document(source_id, source, fetched_page, config):
    from peptide_watch.sources.company_pages import _extract_text_and_title

    text, title = _extract_text_and_title(fetched_page)
    return build_company_document(
        document_key=f"{WATCHED_SOURCE_ID_PREFIX}:{source_id}",
        source_id=source_id,
        source_type="watched_page",
        url=fetched_page.url,
        title=title or source_id,
        company_key=source.company_id,
        source_tier=source.tier,
        content_text=text,
        config=config,
        metadata={
            "configured_url": source.url,
            "content_type": fetched_page.content_type,
            "cadence": source.cadence,
        },
        raw_content=fetched_page.body,
        parser_version=PARSER_VERSION,
    )
