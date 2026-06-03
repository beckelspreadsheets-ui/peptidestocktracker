"""SEC EDGAR public filing monitor."""

from __future__ import annotations

import json
import os
import re
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any
from urllib.parse import quote
from urllib.request import Request, urlopen

from bs4 import BeautifulSoup
from pydantic import BaseModel, ConfigDict

from peptide_watch.config import CompanyConfig, WatchConfig, load_config
from peptide_watch.sources.company_documents import (
    CompanyDocument,
    CompanyMonitorScanResult,
    build_company_document,
    export_company_documents_markdown,
    hash_bytes,
    list_company_documents,
    store_company_document,
)

SEC_DATA_BASE_URL = "https://data.sec.gov"
SEC_ARCHIVES_BASE_URL = "https://www.sec.gov/Archives/edgar/data"
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


@dataclass(frozen=True)
class SecEdgarClient:
    """SEC EDGAR client with explicit public-source user-agent and rate limiting."""

    data_base_url: str = SEC_DATA_BASE_URL
    archives_base_url: str = SEC_ARCHIVES_BASE_URL
    timeout: float = 30.0
    rate_limit_seconds: float = 0.2
    user_agent: str = os.environ.get(
        "PEPTIDE_WATCH_SEC_USER_AGENT",
        "peptide-watch/0.1 public-source research",
    )

    def get_company_tickers(self) -> dict[str, dict[str, Any]]:
        request = self._request(f"{self.data_base_url}/files/company_tickers.json")
        try:
            with urlopen(request, timeout=self.timeout) as response:
                return json.loads(response.read().decode("utf-8"))
        finally:
            self._sleep()

    def get_submissions(self, cik: str) -> dict[str, Any]:
        padded_cik = _pad_cik(cik)
        request = self._request(f"{self.data_base_url}/submissions/CIK{padded_cik}.json")
        try:
            with urlopen(request, timeout=self.timeout) as response:
                return json.loads(response.read().decode("utf-8"))
        finally:
            self._sleep()

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
        request = self._request(url, accept="text/html,text/plain,*/*")
        try:
            with urlopen(request, timeout=self.timeout) as response:
                content_type = response.headers.get("content-type", "")
                body = response.read()
                final_url = response.geturl()
        finally:
            self._sleep()
        return FetchedSecFiling(url=final_url, content_type=content_type, body=body)

    def _request(self, url: str, *, accept: str = "application/json,*/*") -> Request:
        return Request(
            url,
            headers={
                "Accept": accept,
                "User-Agent": self.user_agent,
            },
        )

    def _sleep(self) -> None:
        if self.rate_limit_seconds > 0:
            time.sleep(self.rate_limit_seconds)


def scan_sec_filings(
    db_path: str | Path,
    *,
    config_dir: str | Path = "config",
    client: SecEdgarClient | None = None,
    company_ids: list[str] | None = None,
    tickers: list[str] | None = None,
    forms: list[str] | None = None,
    max_filings: int = 3,
) -> CompanyMonitorScanResult:
    """Scan recent SEC filings for configured public U.S. companies."""

    if max_filings < 1:
        raise ValueError("max_filings must be at least 1")

    config = load_config(config_dir)
    sec_client = client or SecEdgarClient()
    ticker_map = _ticker_map(sec_client.get_company_tickers())
    selected = _selected_sec_companies(config, company_ids=company_ids, tickers=tickers)
    selected_forms = tuple(forms or DEFAULT_SEC_FORMS)

    fetched = stored = inserted = changed = events_created = 0
    scanned_company_ids: list[str] = []
    for company in selected:
        cik = _resolve_company_cik(company, ticker_map)
        if cik is None:
            continue
        scanned_company_ids.append(company.id)
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
            document = normalize_sec_filing(company, filing_ref, fetched_filing, config)
            result = store_company_document(db_path, document)
            fetched += 1
            stored += 1
            inserted += int(result.inserted)
            changed += int(result.changed)
            events_created += result.events_created

    return CompanyMonitorScanResult(
        fetched=fetched,
        stored=stored,
        inserted=inserted,
        changed=changed,
        events_created=events_created,
        source_ids=[SEC_SOURCE_ID],
        company_ids=sorted(scanned_company_ids),
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
        content_hash=hash_bytes(fetched.body),
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
