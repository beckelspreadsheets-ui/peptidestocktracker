import sqlite3
from pathlib import Path

from typer.testing import CliRunner

from peptide_watch.cli import app
from peptide_watch.config import load_config
from peptide_watch.database import init_db
from peptide_watch.sources.company_documents import (
    build_company_document,
    list_company_documents,
    store_company_document,
)
from peptide_watch.sources.company_pages import (
    FetchedCompanyPage,
    normalize_company_page,
    scan_company_pages,
)
from peptide_watch.sources.sec import (
    FetchedSecFiling,
    SecFilingRef,
    normalize_sec_filing,
    scan_sec_filings,
)

ROOT = Path(__file__).resolve().parents[1]

COMPANY_PAGE_TEXT = """
The Precision Peptide Company announced a commercial launch claim for a BPC-157
transdermal patch and purchase order. This company release is not clinical proof.
"""

SEC_FILING_TEXT = """
Hims & Hers describes a peptide facility, compounding pharmacy capabilities, and
mentions BPC-157 only as a monitored target term for this test filing.
"""


class FakeCompanyPageClient:
    def fetch(self, url: str, **kwargs) -> FetchedCompanyPage:
        return FetchedCompanyPage(
            url=url,
            content_type="text/html",
            body=f"<html><title>Company News</title><body>{COMPANY_PAGE_TEXT}</body></html>".encode(),
        )


class FakeSecClient:
    def get_company_tickers(self) -> dict:
        return {"0": {"cik_str": 1773751, "ticker": "HIMS", "title": "HIMS & HERS HEALTH, INC."}}

    def get_submissions(self, cik: str) -> dict:
        return {
            "filings": {
                "recent": {
                    "accessionNumber": ["0001773751-26-000001"],
                    "form": ["10-K"],
                    "filingDate": ["2026-03-01"],
                    "reportDate": ["2025-12-31"],
                    "primaryDocument": ["hims-20251231.htm"],
                }
            }
        }

    def get_filing_text(
        self,
        cik: str,
        accession_number: str,
        primary_document: str,
    ) -> FetchedSecFiling:
        return FetchedSecFiling(
            url=(
                "https://www.sec.gov/Archives/edgar/data/1773751/"
                "000177375126000001/hims-20251231.htm"
            ),
            content_type="text/html",
            body=f"<html><title>HIMS 10-K</title><body>{SEC_FILING_TEXT}</body></html>".encode(),
        )


def test_store_company_document_detects_new_and_changed_microcap_events(tmp_path) -> None:
    db_path = init_db(tmp_path / "watch.db")
    config = load_config(ROOT / "config")
    first = build_company_document(
        document_key="company_page:precision_peptide_cse",
        source_id="precision_peptide_cse",
        source_type="company_page",
        url="https://thecse.com/example",
        title="Precision Peptide news",
        company_key="precision_peptide",
        source_tier="B",
        content_text=COMPANY_PAGE_TEXT,
        config=config,
        metadata={"company_tier": 2, "public_private": "public_otc_canada", "liquidity_risk": "extreme"},
    )
    second = build_company_document(
        document_key="company_page:precision_peptide_cse",
        source_id="precision_peptide_cse",
        source_type="company_page",
        url="https://thecse.com/example",
        title="Precision Peptide news",
        company_key="precision_peptide",
        source_tier="B",
        content_text=f"{COMPANY_PAGE_TEXT} New agreement language was added.",
        config=config,
        metadata={"company_tier": 2, "public_private": "public_otc_canada", "liquidity_risk": "extreme"},
    )

    created = store_company_document(db_path, first)
    unchanged = store_company_document(db_path, first)
    changed = store_company_document(db_path, second)

    assert created.inserted is True
    assert created.events_created == 1
    assert unchanged.events_created == 0
    assert changed.changed is True
    assert changed.events_created == 1
    with sqlite3.connect(db_path) as connection:
        event_rows = connection.execute(
            "SELECT event_type, confidence, severity, stock_market_relevance FROM events ORDER BY id"
        ).fetchall()
    assert [row[0] for row in event_rows] == ["commercial_launch_claim", "commercial_launch_claim"]
    assert event_rows[0][1] == "medium"
    assert event_rows[0][2] == "medium"
    assert "This is not a buy/sell recommendation. Verify independently." in event_rows[0][3]
    assert "liquidity, dilution, promotional, and regulatory risk" in event_rows[0][3]


def test_scan_company_pages_with_fake_client(tmp_path) -> None:
    db_path = init_db(tmp_path / "watch.db")

    result = scan_company_pages(
        db_path,
        config_dir=ROOT / "config",
        client=FakeCompanyPageClient(),
        source_ids=["precision_peptide_cse"],
    )
    documents = list_company_documents(db_path, source_type="company_page")

    assert result.fetched == 1
    assert result.inserted == 1
    assert result.events_created == 1
    assert documents[0].company_key == "precision_peptide"
    assert "bpc_157" in documents[0].peptide_ids
    assert "commercial_launch" in documents[0].keyword_matches


def test_normalize_company_page_uses_configured_company_id() -> None:
    config = load_config(ROOT / "config")
    source = config.sources["hims_ir_news"]
    fetched = FetchedCompanyPage(
        url=source.url,
        content_type="text/html",
        body=(
            "<html><title>Hims news</title><body>"
            "Hims discusses a peptide facility and compounding pharmacy infrastructure."
            "</body></html>"
        ).encode(),
    )

    document = normalize_company_page("hims_ir_news", source, fetched, config)

    assert document.company_key == "hims"
    assert document.company_name == "Hims & Hers Health"
    assert "infrastructure" in document.keyword_matches


def test_scan_sec_filings_with_fake_client_creates_review_event(tmp_path) -> None:
    db_path = init_db(tmp_path / "watch.db")

    result = scan_sec_filings(
        db_path,
        config_dir=ROOT / "config",
        client=FakeSecClient(),
        company_ids=["hims"],
        forms=["10-K"],
        max_filings=1,
    )
    documents = list_company_documents(db_path, source_type="sec_filing")

    assert result.fetched == 1
    assert result.inserted == 1
    assert result.events_created == 1
    assert documents[0].filing_type == "10-K"
    assert documents[0].accession_number == "0001773751-26-000001"
    assert "bpc_157" in documents[0].peptide_ids
    with sqlite3.connect(db_path) as connection:
        event = connection.execute(
            "SELECT event_type, confidence, severity FROM events"
        ).fetchone()
    assert event == ("sec_filing_target_mention", "high", "high")


def test_normalize_sec_filing_preserves_metadata() -> None:
    config = load_config(ROOT / "config")
    company = next(company for company in config.companies if company.id == "hims")
    filing_ref = SecFilingRef(
        cik="1773751",
        accession_number="0001773751-26-000001",
        form="10-K",
        filing_date="2026-03-01",
        report_date="2025-12-31",
        primary_document="hims-20251231.htm",
    )
    fetched = FetchedSecFiling(
        url="https://www.sec.gov/example",
        content_type="text/html",
        body=f"<html><title>HIMS 10-K</title><body>{SEC_FILING_TEXT}</body></html>".encode(),
    )

    document = normalize_sec_filing(company, filing_ref, fetched, config)

    assert document.document_key == "sec:0001773751:0001773751-26-000001:hims-20251231.htm"
    assert document.company_key == "hims"
    assert document.source_tier == "A"
    assert document.metadata["cik"] == "0001773751"


def test_company_monitor_cli_list_commands(tmp_path) -> None:
    db_path = init_db(tmp_path / "watch.db")
    config = load_config(ROOT / "config")
    document = build_company_document(
        document_key="company_page:precision_peptide_cse",
        source_id="precision_peptide_cse",
        source_type="company_page",
        url="https://thecse.com/example",
        title="Precision Peptide news",
        company_key="precision_peptide",
        source_tier="B",
        content_text=COMPANY_PAGE_TEXT,
        config=config,
    )
    store_company_document(db_path, document)

    result = CliRunner().invoke(app, ["company-pages", "list", "--db", str(db_path)])

    assert result.exit_code == 0, result.output
    assert "precision_peptide_cse" in result.output
    assert "bpc_157" in result.output
