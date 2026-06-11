"""SEC EDGAR full-text search monitor — the discovery engine.

Unlike the watchlist-driven ``sec_edgar`` family (which fetches recent
filings for configured companies), this searches the full text of *all*
EDGAR filings for the configured terms, so it surfaces filers that are not
on the watchlist yet. Hits for unknown companies are stored with
``metadata.discovery = true`` for review.
"""

from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any

from peptide_watch.config import WatchConfig, load_config
from peptide_watch.database import init_db
from peptide_watch.events import ad_hoc_run_id
from peptide_watch.net.client import DEFAULT_USER_AGENT, HttpClient
from peptide_watch.sources.company_documents import (
    CompanyMonitorScanResult,
    build_company_document,
    open_connection,
    write_company_document,
)

SEC_FTS_SOURCE_ID = "sec_fulltext"
SEC_FTS_BASE_URL = "https://efts.sec.gov/LATEST/search-index"
PARSER_VERSION = 1
QUOTED_TERM_RE = re.compile(r'"([^"]+)"')


class SecFullTextClient:
    """EDGAR full-text search (efts.sec.gov) client."""

    def __init__(
        self,
        *,
        base_url: str = SEC_FTS_BASE_URL,
        timeout: float = 30.0,
        rate_limit_seconds: float = 0.5,
        user_agent: str = DEFAULT_USER_AGENT,
        http: HttpClient | None = None,
    ) -> None:
        self.base_url = base_url
        self._http = http or HttpClient(
            timeout=timeout, rate_limit_seconds=rate_limit_seconds, user_agent=user_agent
        )

    def search(self, phrase: str) -> list[dict[str, Any]]:
        payload = self._http.get_json(self.base_url, params={"q": f'"{phrase}"'})
        return list(payload.get("hits", {}).get("hits", []))


def default_search_phrases(config: WatchConfig) -> list[str]:
    """Individual quoted phrases pulled from the sec_keywords query group."""

    phrases: list[str] = []
    for query in config.queries.get("sec_keywords", []):
        phrases.extend(QUOTED_TERM_RE.findall(query))
    if not phrases:
        for peptide in config.primary_peptides:
            phrases.extend(peptide.aliases[:2])
    seen: set[str] = set()
    unique = []
    for phrase in phrases:
        if phrase.casefold() not in seen:
            seen.add(phrase.casefold())
            unique.append(phrase)
    return unique


def scan_sec_fulltext(
    db_path: str | Path,
    *,
    config_dir: str | Path = "config",
    client: SecFullTextClient | None = None,
    phrases: list[str] | None = None,
    run_id: str | None = None,
) -> CompanyMonitorScanResult:
    """Full-text search EDGAR for watch terms; store every matching filing.

    Each phrase fails independently; a filing's writes are one transaction.
    """

    config = load_config(config_dir)
    api_client = client or SecFullTextClient()
    selected_phrases = phrases or default_search_phrases(config)
    run_id = run_id or ad_hoc_run_id()

    init_db(db_path)
    connection = open_connection(db_path)
    fetched = stored = inserted = changed = events_created = 0
    errors: list[str] = []
    company_ids: set[str] = set()
    seen_keys: set[str] = set()
    try:
        for phrase in selected_phrases:
            try:
                hits = api_client.search(phrase)
            except (KeyboardInterrupt, SystemExit):
                raise
            except Exception as exc:
                errors.append(f"phrase {phrase!r}: {exc}")
                continue
            fetched += len(hits)
            for hit in hits:
                try:
                    document = normalize_fts_hit(hit, phrase, config)
                    if document is None or document.document_key in seen_keys:
                        continue
                    seen_keys.add(document.document_key)
                    result = write_company_document(connection, document, run_id=run_id)
                    connection.commit()
                except (KeyboardInterrupt, SystemExit):
                    raise
                except Exception as exc:
                    connection.rollback()
                    errors.append(f"hit in {phrase!r}: {exc}")
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

    if errors and stored == 0 and fetched == 0 and selected_phrases:
        raise RuntimeError(
            f"SEC full-text scan failed for all phrases: {'; '.join(errors[:5])}"
        )

    return CompanyMonitorScanResult(
        fetched=fetched,
        stored=stored,
        inserted=inserted,
        changed=changed,
        events_created=events_created,
        source_ids=[SEC_FTS_SOURCE_ID],
        company_ids=sorted(company_ids),
        errors=errors,
    )


def normalize_fts_hit(hit: dict[str, Any], phrase: str, config: WatchConfig):
    source = hit.get("_source", {})
    hit_id = str(hit.get("_id") or "")
    accession = hit_id.split(":", 1)[0] if hit_id else str(source.get("adsh") or "")
    if not accession:
        return None

    ciks = source.get("cik") or source.get("ciks") or []
    if isinstance(ciks, (str, int)):
        ciks = [ciks]
    cik = str(ciks[0]) if ciks else ""
    display_names = source.get("display_names") or []
    display = str(display_names[0]) if display_names else ""
    file_type = str(source.get("file_type") or source.get("form_type") or "")
    file_date = str(source.get("file_date") or "")

    company_key, ticker = _match_watchlist_company(display, config)
    url = (
        f"https://www.sec.gov/Archives/edgar/data/{int(cik)}/{accession.replace('-', '')}/"
        if cik.isdigit()
        else f"https://efts.sec.gov/LATEST/search-index?q=%22{phrase}%22"
    )
    text = (
        f"{display} {file_type} filed {file_date}; "
        f"EDGAR full-text match for \"{phrase}\"."
    )
    raw = json.dumps(hit, sort_keys=True, separators=(",", ":"), ensure_ascii=False)
    return build_company_document(
        document_key=f"sec_fts:{accession}",
        source_id=SEC_FTS_SOURCE_ID,
        source_type="sec_filing",
        url=url,
        title=f"{display or 'Unknown filer'} {file_type}".strip(),
        company_key=company_key,
        company_name=display or None,
        ticker=ticker,
        filing_type=file_type or None,
        filing_date=file_date or None,
        source_tier="A",
        content_text=text,
        config=config,
        metadata={
            "phrase": phrase,
            "cik": cik,
            "discovery": company_key is None,
        },
        raw_content=raw.encode("utf-8"),
        parser_version=PARSER_VERSION,
    )


def _match_watchlist_company(display: str, config: WatchConfig) -> tuple[str | None, str | None]:
    """Match an EDGAR display name like 'Acme Corp (ACME) (CIK 0001234)' to the watchlist."""

    lowered = display.casefold()
    ticker_match = re.search(r"\(([A-Z][A-Z0-9.\-]{0,9})\)", display)
    ticker = ticker_match.group(1) if ticker_match else None
    for company in config.companies:
        if company.name.casefold() in lowered:
            return company.id, company.ticker or ticker
        if company.ticker and ticker:
            configured = {part.strip().upper() for part in re.split(r"[/\s]+", company.ticker)}
            if ticker.upper() in configured:
                return company.id, ticker
    return None, ticker
