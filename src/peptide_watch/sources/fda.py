"""FDA page and PDF monitors for PCAC, 503A, and safety-risk sources."""

from __future__ import annotations

import io
import time
from dataclasses import dataclass
from pathlib import Path
from urllib.request import Request, urlopen

from bs4 import BeautifulSoup
from pydantic import BaseModel
from pypdf import PdfReader

from peptide_watch.config import SourceConfig, WatchConfig, load_config
from peptide_watch.database import init_db
from peptide_watch.events import ad_hoc_run_id
from peptide_watch.sources.regulatory import (
    RegulatoryDocument,
    RegulatoryScanResult,
    build_regulatory_document,
    export_regulatory_documents_markdown,
    list_regulatory_documents,
    open_connection,
    write_regulatory_document,
)

PARSER_VERSION = 1


class FetchedFdaContent(BaseModel):
    """Fetched FDA source content."""

    url: str
    content_type: str
    body: bytes


@dataclass(frozen=True)
class FdaClient:
    """FDA public page/PDF client with explicit rate limiting."""

    timeout: float = 30.0
    rate_limit_seconds: float = 0.2
    user_agent: str = "peptide-watch/0.1 public-source research"

    def fetch(self, url: str) -> FetchedFdaContent:
        request = Request(
            url,
            headers={
                "Accept": "text/html,application/pdf,*/*",
                "User-Agent": self.user_agent,
            },
        )
        try:
            with urlopen(request, timeout=self.timeout) as response:
                content_type = response.headers.get("content-type", "")
                body = response.read()
                final_url = response.geturl()
        finally:
            if self.rate_limit_seconds > 0:
                time.sleep(self.rate_limit_seconds)
        return FetchedFdaContent(url=final_url, content_type=content_type, body=body)


def scan_fda_sources(
    db_path: str | Path,
    *,
    config_dir: str | Path = "config",
    client: FdaClient | None = None,
    source_ids: list[str] | None = None,
    run_id: str | None = None,
) -> RegulatoryScanResult:
    """Scan configured FDA sources and store changed documents.

    Each source fails independently; a source's writes are one transaction.
    """

    config = load_config(config_dir)
    selected = _selected_fda_sources(config, source_ids)
    api_client = client or FdaClient()
    run_id = run_id or ad_hoc_run_id()

    init_db(db_path)
    connection = open_connection(db_path)
    fetched = stored = inserted = changed = events_created = 0
    errors: list[str] = []
    try:
        for source_id, source in selected.items():
            try:
                fetched_content = api_client.fetch(source.url)
                fetched += 1
                document = normalize_fda_document(source_id, source, fetched_content, config)
                result = write_regulatory_document(connection, document, run_id=run_id)
                connection.commit()
            except (KeyboardInterrupt, SystemExit):
                raise
            except Exception as exc:
                connection.rollback()
                errors.append(f"{source_id}: {exc}")
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

    if errors and stored == 0 and selected:
        raise RuntimeError(f"FDA scan failed for all sources: {'; '.join(errors[:5])}")

    return RegulatoryScanResult(
        fetched=fetched,
        stored=stored,
        inserted=inserted,
        changed=changed,
        events_created=events_created,
        source_ids=list(selected),
        errors=errors,
    )


def normalize_fda_document(
    source_id: str,
    source: SourceConfig,
    fetched: FetchedFdaContent,
    config: WatchConfig,
) -> RegulatoryDocument:
    """Normalize one FDA page or PDF into a regulatory document."""

    source_type = "fda_pdf" if _is_pdf(source, fetched) else "fda_page"
    text, title = _extract_text_and_title(fetched, source_type)
    return build_regulatory_document(
        document_key=f"fda:{source_id}",
        source_id=source_id,
        source_type=source_type,
        url=fetched.url,
        title=title or _title_from_source_id(source_id),
        content_text=text,
        config=config,
        metadata={
            "configured_url": source.url,
            "content_type": fetched.content_type,
            "source_tier": source.tier,
            "cadence": source.cadence,
        },
        raw_content=fetched.body,
        parser_version=PARSER_VERSION,
    )


def list_fda_documents(db_path: str | Path, *, limit: int = 100) -> list[RegulatoryDocument]:
    return list_regulatory_documents(db_path, source_prefix="fda_", limit=limit)


def export_fda_documents_markdown(documents: list[RegulatoryDocument]) -> str:
    return export_regulatory_documents_markdown(documents)


def _selected_fda_sources(
    config: WatchConfig,
    source_ids: list[str] | None,
) -> dict[str, SourceConfig]:
    available = {
        source_id: source
        for source_id, source in config.sources.items()
        if source_id.startswith("fda_")
    }
    if not source_ids:
        return available
    missing = sorted(set(source_ids) - set(available))
    if missing:
        raise ValueError(f"unknown FDA source ids: {', '.join(missing)}")
    return {source_id: available[source_id] for source_id in source_ids}


def _is_pdf(source: SourceConfig, fetched: FetchedFdaContent) -> bool:
    return source.type == "pdf" or "application/pdf" in fetched.content_type.lower()


def _extract_text_and_title(fetched: FetchedFdaContent, source_type: str) -> tuple[str, str | None]:
    if source_type == "fda_pdf":
        return _extract_pdf_text(fetched.body), None
    html = fetched.body.decode("utf-8", errors="ignore")
    soup = BeautifulSoup(html, "html.parser")
    title = soup.title.get_text(" ", strip=True) if soup.title else None
    return soup.get_text(" ", strip=True), title


def _extract_pdf_text(body: bytes) -> str:
    reader = PdfReader(io.BytesIO(body))
    pages: list[str] = []
    for page in reader.pages:
        pages.append(page.extract_text() or "")
    return "\n".join(pages)


def _title_from_source_id(source_id: str) -> str:
    return source_id.replace("_", " ").upper()
