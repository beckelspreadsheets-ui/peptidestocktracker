"""USPTO Open Data Portal patent search monitor (API-key gated).

Requires the free key from https://developer.uspto.gov in the
PEPTIDE_WATCH_USPTO_API_KEY environment variable (never config). The
endpoint shape was probed live (401 awaiting a key at
``/api/v1/patent/applications/search``); field names inside the response are
normalized defensively — the entire record JSON is used as the matchable
text, so watch-term matching works even where field guesses differ. Run
``peptide-watch uspto check`` once the key is set to print the live response
shape and confirm.
"""

from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Any

from peptide_watch.config import WatchConfig, load_config
from peptide_watch.database import init_db
from peptide_watch.events import ad_hoc_run_id
from peptide_watch.net.client import DEFAULT_USER_AGENT, HttpClient
from peptide_watch.sources.regulatory import (
    RegulatoryScanResult,
    build_regulatory_document,
    open_connection,
    write_regulatory_document,
)

USPTO_SOURCE_ID = "uspto_patents"
USPTO_SEARCH_URL = "https://api.uspto.gov/api/v1/patent/applications/search"
USPTO_API_KEY_ENV = "PEPTIDE_WATCH_USPTO_API_KEY"
PARSER_VERSION = 1


def api_key_present() -> bool:
    return bool(os.environ.get(USPTO_API_KEY_ENV))


class UsptoClient:
    """USPTO Open Data Portal search client."""

    def __init__(
        self,
        *,
        search_url: str = USPTO_SEARCH_URL,
        api_key: str | None = None,
        timeout: float = 30.0,
        rate_limit_seconds: float = 1.0,
        user_agent: str = DEFAULT_USER_AGENT,
        http: HttpClient | None = None,
    ) -> None:
        self.search_url = search_url
        self.api_key = api_key or os.environ.get(USPTO_API_KEY_ENV, "")
        self._http = http or HttpClient(
            timeout=timeout, rate_limit_seconds=rate_limit_seconds, user_agent=user_agent
        )

    def search(self, query: str, *, limit: int = 25) -> list[dict[str, Any]]:
        return _extract_records(self.raw_search(query, limit=limit))

    def raw_search(self, query: str, *, limit: int = 2) -> dict[str, Any]:
        """One live request returning the unparsed payload (for `uspto check`)."""

        if not self.api_key:
            raise RuntimeError(f"{USPTO_API_KEY_ENV} is not set")
        return self._http.get_json(
            self.search_url,
            params={"q": query, "limit": limit},
            extra_headers={"X-API-KEY": self.api_key},
        )


def _extract_records(payload: dict[str, Any]) -> list[dict[str, Any]]:
    """Find the record list regardless of the envelope key the API uses."""

    for key in ("patentFileWrapperDataBag", "patentBag", "results", "records", "docs"):
        value = payload.get(key)
        if isinstance(value, list):
            return [record for record in value if isinstance(record, dict)]
    # fall back to the first list-of-dicts value in the payload
    for value in payload.values():
        if isinstance(value, list) and value and isinstance(value[0], dict):
            return [record for record in value if isinstance(record, dict)]
    return []


def _record_id(record: dict[str, Any]) -> str:
    for key in (
        "applicationNumberText",
        "applicationNumber",
        "patentNumber",
        "publicationNumber",
        "id",
    ):
        value = record.get(key)
        if value:
            return str(value)
    meta = record.get("applicationMetaData")
    if isinstance(meta, dict):
        for key in ("applicationNumberText", "applicationNumber"):
            if meta.get(key):
                return str(meta[key])
    return ""


def _record_title(record: dict[str, Any]) -> str:
    for key in ("inventionTitle", "title", "inventionSubjectMatterCategory"):
        value = record.get(key)
        if value:
            return str(value)
    meta = record.get("applicationMetaData")
    if isinstance(meta, dict) and meta.get("inventionTitle"):
        return str(meta["inventionTitle"])
    return ""


def default_uspto_queries(config: WatchConfig) -> list[str]:
    queries = list(config.queries.get("uspto", []))
    if queries:
        return queries
    return [f'"{peptide.aliases[0]}"' for peptide in config.primary_peptides]


def scan_uspto_patents(
    db_path: str | Path,
    *,
    config_dir: str | Path = "config",
    client: UsptoClient | None = None,
    queries: list[str] | None = None,
    run_id: str | None = None,
) -> RegulatoryScanResult:
    """Search USPTO patent applications for watch terms and store matches.

    Each query fails independently; a record's writes are one transaction.
    """

    config = load_config(config_dir)
    api_client = client or UsptoClient()
    selected_queries = queries or default_uspto_queries(config)
    run_id = run_id or ad_hoc_run_id()

    init_db(db_path)
    connection = open_connection(db_path)
    fetched = stored = inserted = changed = events_created = 0
    errors: list[str] = []
    seen_ids: set[str] = set()
    try:
        for query in selected_queries:
            try:
                records = api_client.search(query)
            except (KeyboardInterrupt, SystemExit):
                raise
            except Exception as exc:
                errors.append(f"query {query!r}: {exc}")
                continue
            for record in records:
                record_id = _record_id(record)
                if not record_id or record_id in seen_ids:
                    continue
                seen_ids.add(record_id)
                try:
                    fetched += 1
                    document = normalize_patent_record(record_id, record, query, config)
                    result = write_regulatory_document(connection, document, run_id=run_id)
                    connection.commit()
                except (KeyboardInterrupt, SystemExit):
                    raise
                except Exception as exc:
                    connection.rollback()
                    errors.append(f"record {record_id}: {exc}")
                    continue
                stored += 1
                inserted += int(result.inserted)
                changed += int(result.changed)
                events_created += result.events_created
    except BaseException:
        connection.rollback()
        connection.close()
        raise
    else:
        connection.close()

    if errors and stored == 0 and selected_queries:
        raise RuntimeError(f"USPTO scan failed for all queries: {'; '.join(errors[:5])}")

    return RegulatoryScanResult(
        fetched=fetched,
        stored=stored,
        inserted=inserted,
        changed=changed,
        events_created=events_created,
        source_ids=[USPTO_SOURCE_ID],
        queries=selected_queries,
        errors=errors,
    )


def normalize_patent_record(
    record_id: str, record: dict[str, Any], query: str, config: WatchConfig
):
    raw = json.dumps(record, sort_keys=True, separators=(",", ":"), ensure_ascii=False)
    title = _record_title(record)
    # The whole record is the matchable text: alias matching keeps working
    # even where the API's field names differ from the guesses above.
    text = f"{title}. {raw}"
    return build_regulatory_document(
        document_key=f"uspto:{record_id}",
        source_id=USPTO_SOURCE_ID,
        source_type="uspto_patent",
        url=f"https://patentcenter.uspto.gov/applications/{record_id}",
        title=title or f"USPTO application {record_id}",
        content_text=text,
        config=config,
        metadata={"query": query},
        raw_content=raw.encode("utf-8"),
        parser_version=PARSER_VERSION,
    )
