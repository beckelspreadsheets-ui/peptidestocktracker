"""SEC EDGAR public filing monitor."""

from __future__ import annotations

import os
import re
from pathlib import Path
from typing import Any
from urllib.parse import quote

from bs4 import BeautifulSoup
from pydantic import BaseModel, ConfigDict

from peptide_watch.config import CompanyConfig, WatchConfig, load_config
from peptide_watch.database import init_db
from peptide_watch.events import ad_hoc_run_id
from peptide_watch.net.client import DEFAULT_USER_AGENT, HttpClient
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

SEC_DATA_BASE_URL = "https://data.sec.gov"
SEC_ARCHIVES_BASE_URL = "https://www.sec.gov/Archives/edgar/data"
SEC_TICKER_FILE_URL = "https://www.sec.gov/files/company_tickers.json"
SEC_SOURCE_ID = "sec_edgar"
DEFAULT_SEC_FORMS = ("10-K", "10-Q", "8-K", "S-1", "S-3", "424B", "DEF 14A", "20-F", "6-K")


class SecFilingRef(BaseModel):
    """Reference to a recent SEC filing primary document."""

    model_config = ConfigDict(extra="forbid")

    cik: str
    accession_number: str
    form: str
    filing_date: str | None = None
    report_date: str | None = None
    primary_document: str


class FetchedSecFiling(BaseModel):
    """Fetched public SEC filing document."""

    url: str
    content_type: str
    body: bytes


class SecEdgarClient:
    """SEC EDGAR client on the shared HTTP layer with an honest user-agent."""

    def __init__(
        self,
        *,
        data_base_url: str = SEC_DATA_BASE_URL,
        archives_base_url: str = SEC_ARCHIVES_BASE_URL,
        timeout: float = 30.0,
        rate_limit_seconds: float = 0.2,
        user_agent: str | None = None,
        http: HttpClient | None = None,
    ) -> None:
        self.data_base_url = data_base_url
        self.archives_base_url = archives_base_url
        resolved_user_agent = user_agent or os.environ.get(
            "PEPTIDE_WATCH_SEC_USER_AGENT", DEFAULT_USER_AGENT
        )
        self._http = http or HttpClient(
            timeout=timeout,
            rate_limit_seconds=rate_limit_seconds,
            user_agent=resolved_user_agent,
        )

    def get_company_tickers(self) -> dict[str, dict[str, Any]]:
        # The ticker map lives on www.sec.gov, not data.sec.gov (live-verified).
        return self._http.get_json(SEC_TICKER_FILE_URL)

    def get_submissions(self, cik: str) -> dict[str, Any]:
        padded_cik = _pad_cik(cik)
        return self._http.get_json(f"{self.data_base_url}/submissions/CIK{padded_cik}.json")

    def get_filing_text(
        self,
        cik: str,
        accession_number: str,
        primary_document: str,
    ) -> FetchedSecFiling:
        cik_int = str(int(cik))
        accession_path = accession_number.replace("-", "")
        primary_path = quote(primary_document)
        url = f"{self.archives_base_url}/{cik_int}/{accession_path}/{primary_path}"
        result = self._http.get(url, accept="text/html,text/plain,*/*")
        return FetchedSecFiling(
            url=result.url, content_type=result.content_type, body=result.body
        )

def scan_sec_filings(
    db_path: str | Path,
    *,
    config_dir: str | Path = "config",
    client: SecEdgarClient | None = None,
    company_ids: list[str] | None = None,
    tickers: list[str] | None = None,
    forms: list[str] | None = None,
    max_filings: int = 3,
    run_id: str | None = None,
) -> CompanyMonitorScanResult:
    """Scan recent SEC filings for configured public U.S. companies.

    Each company fails independently; a filing's writes are one transaction.
    """

    if max_filings < 1:
        raise ValueError("max_filings must be at least 1")

    config = load_config(config_dir)
    sec_client = client or SecEdgarClient()
    ticker_map = _ticker_map(sec_client.get_company_tickers())
    selected = _selected_sec_companies(config, company_ids=company_ids, tickers=tickers)
    selected_forms = tuple(forms or DEFAULT_SEC_FORMS)
    run_id = run_id or ad_hoc_run_id()

    init_db(db_path)
    connection = open_connection(db_path)
    fetched = stored = inserted = changed = events_created = 0
    errors: list[str] = []
    scanned_company_ids: list[str] = []
    try:
        for company in selected:
            cik = _resolve_company_cik(company, ticker_map)
            if cik is None:
                continue
            scanned_company_ids.append(company.id)
            try:
                submissions = sec_client.get_submissions(cik)
                filing_refs = _recent_filing_refs(
                    submissions,
                    cik=cik,
                    forms=selected_forms,
                    max_filings=max_filings,
                )
                for filing_ref in filing_refs:
                    fetched_filing = sec_client.get_filing_text(
                        filing_ref.cik,
                        filing_ref.accession_number,
                        filing_ref.primary_document,
                    )
                    fetched += 1
                    document = normalize_sec_filing(company, filing_ref, fetched_filing, config)
                    result = write_company_document(connection, document, run_id=run_id)
                    connection.commit()
                    stored += 1
                    inserted += int(result.inserted)
                    changed += int(result.changed)
                    events_created += result.events_created
            except (KeyboardInterrupt, SystemExit):
                raise
            except Exception as exc:
                connection.rollback()
                errors.append(f"{company.id}: {exc}")
    except BaseException:
        connection.rollback()
        connection.close()
        raise
    else:
        connection.close()

    if errors and stored == 0 and scanned_company_ids:
        raise RuntimeError(f"SEC scan failed for all companies: {'; '.join(errors[:5])}")

    return CompanyMonitorScanResult(
        fetched=fetched,
        stored=stored,
        inserted=inserted,
        changed=changed,
        events_created=events_created,
        source_ids=[SEC_SOURCE_ID],
        company_ids=sorted(scanned_company_ids),
        errors=errors,
    )


def normalize_sec_filing(
    company: CompanyConfig,
    filing_ref: SecFilingRef,
    fetched: FetchedSecFiling,
    config: WatchConfig,
) -> CompanyDocument:
    """Normalize one fetched SEC filing primary document."""

    text, title = _extract_text_and_title(fetched)
    document_title = title or f"{company.name} {filing_ref.form} {filing_ref.filing_date or ''}".strip()
    return build_company_document(
        document_key=(
            f"sec:{_pad_cik(filing_ref.cik)}:"
            f"{filing_ref.accession_number}:{filing_ref.primary_document}"
        ),
        source_id=SEC_SOURCE_ID,
        source_type="sec_filing",
        url=fetched.url,
        title=document_title,
        company_key=company.id,
        company_name=company.name,
        ticker=company.ticker,
        exchange=company.exchange,
        filing_type=filing_ref.form,
        accession_number=filing_ref.accession_number,
        filing_date=filing_ref.filing_date,
        source_tier="A",
        content_text=text,
        config=config,
        metadata={
            "cik": _pad_cik(filing_ref.cik),
            "report_date": filing_ref.report_date,
            "primary_document": filing_ref.primary_document,
            "company_tier": company.tier,
            "public_private": company.public_private,
            "relationship": company.relationship,
            "liquidity_risk": company.liquidity_risk,
        },
        raw_content=fetched.body,
        parser_version=PARSER_VERSION,
    )


def list_sec_documents(db_path: str | Path, *, limit: int = 100) -> list[CompanyDocument]:
    return list_company_documents(db_path, source_type="sec_filing", limit=limit)


def export_sec_documents_markdown(documents: list[CompanyDocument]) -> str:
    return export_company_documents_markdown(documents)


def _ticker_map(raw_tickers: dict[str, dict[str, Any]]) -> dict[str, str]:
    mapping: dict[str, str] = {}
    for entry in raw_tickers.values():
        ticker = str(entry.get("ticker") or "").upper()
        cik = entry.get("cik_str")
        if ticker and cik is not None:
            mapping[ticker] = _pad_cik(str(cik))
    return mapping


def _selected_sec_companies(
    config: WatchConfig,
    *,
    company_ids: list[str] | None,
    tickers: list[str] | None,
) -> list[CompanyConfig]:
    companies_by_id = {company.id: company for company in config.companies}
    if company_ids:
        missing = sorted(set(company_ids) - set(companies_by_id))
        if missing:
            raise ValueError(f"unknown company ids: {', '.join(missing)}")
        return [companies_by_id[company_id] for company_id in company_ids]

    ticker_filter = {ticker.upper() for ticker in tickers or []}
    selected: list[CompanyConfig] = []
    for company in config.companies:
        tokens = {token.upper() for token in _ticker_terms(company.ticker)}
        if ticker_filter and not tokens.intersection(ticker_filter):
            continue
        if ticker_filter or _is_sec_eligible(company):
            selected.append(company)
    return selected


def _is_sec_eligible(company: CompanyConfig) -> bool:
    public_private = company.public_private.casefold()
    exchange = (company.exchange or "").casefold()
    return (
        "public_us" in public_private
        or "mixed" in public_private
        or any(token in exchange for token in ["nasdaq", "nyse", "otc"])
    )


def _resolve_company_cik(company: CompanyConfig, tickers: dict[str, str]) -> str | None:
    extra_cik = company.model_extra.get("cik") if company.model_extra else None
    if extra_cik:
        return _pad_cik(str(extra_cik))
    for ticker in _ticker_terms(company.ticker):
        cik = tickers.get(ticker.upper())
        if cik:
            return cik
    return None


def _recent_filing_refs(
    submissions: dict[str, Any],
    *,
    cik: str,
    forms: tuple[str, ...],
    max_filings: int,
) -> list[SecFilingRef]:
    recent = submissions.get("filings", {}).get("recent", {})
    accession_numbers = list(recent.get("accessionNumber", []))
    form_values = list(recent.get("form", []))
    filing_dates = list(recent.get("filingDate", []))
    report_dates = list(recent.get("reportDate", []))
    primary_documents = list(recent.get("primaryDocument", []))
    selected_forms = {form.upper() for form in forms}

    refs: list[SecFilingRef] = []
    for index, accession_number in enumerate(accession_numbers):
        form = _list_value(form_values, index)
        primary_document = _list_value(primary_documents, index)
        if not accession_number or not primary_document:
            continue
        if selected_forms and form.upper() not in selected_forms:
            continue
        refs.append(
            SecFilingRef(
                cik=_pad_cik(cik),
                accession_number=str(accession_number),
                form=form,
                filing_date=_list_value(filing_dates, index) or None,
                report_date=_list_value(report_dates, index) or None,
                primary_document=primary_document,
            )
        )
        if len(refs) >= max_filings:
            break
    return refs


def _extract_text_and_title(fetched: FetchedSecFiling) -> tuple[str, str | None]:
    text = fetched.body.decode("utf-8", errors="ignore")
    soup = BeautifulSoup(text, "html.parser")
    title = soup.title.get_text(" ", strip=True) if soup.title else None
    return soup.get_text(" ", strip=True), title


def _ticker_terms(ticker: str | None) -> list[str]:
    if not ticker:
        return []
    return [term for term in re.split(r"[^A-Za-z0-9]+", ticker) if term]


def _pad_cik(cik: str) -> str:
    return str(int(cik)).zfill(10)


def _list_value(values: list[Any], index: int) -> str:
    if index >= len(values) or values[index] is None:
        return ""
    return str(values[index])
