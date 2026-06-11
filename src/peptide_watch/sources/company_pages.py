"""Company IR/news/public page monitors."""

from __future__ import annotations

import time
from dataclasses import dataclass
from pathlib import Path
from urllib.request import Request, urlopen

from bs4 import BeautifulSoup
from pydantic import BaseModel

from peptide_watch.config import CompanyConfig, SourceConfig, WatchConfig, load_config
from peptide_watch.database import init_db
from peptide_watch.events import ad_hoc_run_id
from peptide_watch.sources.company_documents import (
    CompanyDocument,
    CompanyMonitorScanResult,
    build_company_document,
    export_company_documents_markdown,
    list_company_documents,
    open_connection,
    write_company_document,
)

PARSER_VERSION = 1


class FetchedCompanyPage(BaseModel):
    """Fetched public company page content."""

    url: str
    content_type: str
    body: bytes


@dataclass(frozen=True)
class CompanyPageClient:
    """Public company page client with explicit rate limiting."""

    timeout: float = 30.0
    rate_limit_seconds: float = 0.2
    user_agent: str = "peptide-watch/0.1 public-source research"

    def fetch(self, url: str) -> FetchedCompanyPage:
        request = Request(
            url,
            headers={
                "Accept": "text/html,application/xhtml+xml,application/xml,text/plain,*/*",
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
        return FetchedCompanyPage(url=final_url, content_type=content_type, body=body)


def scan_company_pages(
    db_path: str | Path,
    *,
    config_dir: str | Path = "config",
    client: CompanyPageClient | None = None,
    source_ids: list[str] | None = None,
    run_id: str | None = None,
) -> CompanyMonitorScanResult:
    """Scan configured company IR/news/page sources and create review events.

    Each source fails independently; a source's writes are one transaction.
    """

    config = load_config(config_dir)
    selected = _selected_company_page_sources(config, source_ids)
    page_client = client or CompanyPageClient()
    run_id = run_id or ad_hoc_run_id()

    init_db(db_path)
    connection = open_connection(db_path)
    fetched = stored = inserted = changed = events_created = 0
    errors: list[str] = []
    company_ids: set[str] = set()
    try:
        for source_id, source in selected.items():
            try:
                fetched_page = page_client.fetch(source.url)
                fetched += 1
                document = normalize_company_page(source_id, source, fetched_page, config)
                result = write_company_document(connection, document, run_id=run_id)
                connection.commit()
            except (KeyboardInterrupt, SystemExit):
                raise
            except Exception as exc:
                connection.rollback()
                errors.append(f"{source_id}: {exc}")
                continue
            if document.company_key:
                company_ids.add(document.company_key)
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
        raise RuntimeError(f"Company page scan failed for all sources: {'; '.join(errors[:5])}")

    return CompanyMonitorScanResult(
        fetched=fetched,
        stored=stored,
        inserted=inserted,
        changed=changed,
        events_created=events_created,
        source_ids=list(selected),
        company_ids=sorted(company_ids),
        errors=errors,
    )


def normalize_company_page(
    source_id: str,
    source: SourceConfig,
    fetched: FetchedCompanyPage,
    config: WatchConfig,
) -> CompanyDocument:
    """Normalize one configured company page into a document record."""

    company_id = _source_company_id(source)
    company = _company_by_id(config, company_id)
    text, title = _extract_text_and_title(fetched)
    return build_company_document(
        document_key=f"company_page:{source_id}",
        source_id=source_id,
        source_type="company_page",
        url=fetched.url,
        title=title or _title_from_source_id(source_id),
        company_key=company.id if company else company_id,
        company_name=company.name if company else None,
        ticker=company.ticker if company else None,
        exchange=company.exchange if company else None,
        source_tier=source.tier,
        content_text=text,
        config=config,
        metadata={
            "configured_url": source.url,
            "content_type": fetched.content_type,
            "source_tier": source.tier,
            "cadence": source.cadence,
            "company_tier": company.tier if company else None,
            "public_private": company.public_private if company else None,
            "liquidity_risk": company.liquidity_risk if company else None,
        },
        raw_content=fetched.body,
        parser_version=PARSER_VERSION,
    )


def list_company_page_documents(
    db_path: str | Path,
    *,
    limit: int = 100,
) -> list[CompanyDocument]:
    return list_company_documents(db_path, source_type="company_page", limit=limit)


def export_company_page_documents_markdown(documents: list[CompanyDocument]) -> str:
    return export_company_documents_markdown(documents)


def _selected_company_page_sources(
    config: WatchConfig,
    source_ids: list[str] | None,
) -> dict[str, SourceConfig]:
    available = {
        source_id: source
        for source_id, source in config.sources.items()
        if _is_company_page_source(source_id, source)
    }
    if not source_ids:
        return available
    missing = sorted(set(source_ids) - set(available))
    if missing:
        raise ValueError(f"unknown company page source ids: {', '.join(missing)}")
    return {source_id: available[source_id] for source_id in source_ids}


def _is_company_page_source(source_id: str, source: SourceConfig) -> bool:
    if source.type not in {"page", "rss"}:
        return False
    if _source_company_id(source):
        return True
    lowered = source_id.casefold()
    if lowered.startswith(("fda_", "clinicaltrials")):
        return False
    if lowered in {"sedar_plus", "uspto_assignment"} or lowered.startswith("wipo_"):
        return False
    return any(token in lowered for token in ["news", "ir", "otc", "cse", "company"])


def _source_company_id(source: SourceConfig) -> str | None:
    return source.company_id or None


def _company_by_id(config: WatchConfig, company_id: str | None) -> CompanyConfig | None:
    if not company_id:
        return None
    company = next((item for item in config.companies if item.id == company_id), None)
    if company is None:
        raise ValueError(f"source references unknown company_id: {company_id}")
    return company


def _extract_text_and_title(fetched: FetchedCompanyPage) -> tuple[str, str | None]:
    text = fetched.body.decode("utf-8", errors="ignore")
    soup = BeautifulSoup(text, "html.parser")
    title = soup.title.get_text(" ", strip=True) if soup.title else None
    return soup.get_text(" ", strip=True), title


def _title_from_source_id(source_id: str) -> str:
    return source_id.replace("_", " ").title()
