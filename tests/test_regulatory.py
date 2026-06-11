import sqlite3
from pathlib import Path

from typer.testing import CliRunner

from peptide_watch.cli import app
from peptide_watch.config import SourceConfig, load_config
from peptide_watch.database import init_db
from peptide_watch.sources.fda import FetchedFdaContent, normalize_fda_document, scan_fda_sources
from peptide_watch.sources.federal_register import (
    normalize_federal_register_document,
    scan_federal_register,
)
from peptide_watch.sources.regulatory import (
    build_regulatory_document,
    list_regulatory_documents,
    store_regulatory_document,
)

ROOT = Path(__file__).resolve().parents[1]
FDA_PCAC_TEXT = """
July 23-24, 2026: Meeting of the Pharmacy Compounding Advisory Committee.
On July 23, 2026, the Committee will discuss BPC-157-related bulk drug substances
(BPC-157 free base / BPC-157 acetate), KPV-related bulk drug substances, TB-500,
and MOTs-C for potential inclusion on the 503A Bulks List. This is not FDA approval.
"""
FDA_503A_TEXT = """
Category 1: non-injectable GHK-Cu will be added back to Category 1.
FDA continues to identify safety concerns for injectable GHK-Cu.
Category 2: BPC-157 may present significant safety risks for certain routes.
"""


class FakeFdaClient:
    def __init__(self, body: bytes) -> None:
        self.body = body

    def fetch(self, url: str, **kwargs) -> FetchedFdaContent:
        return FetchedFdaContent(url=url, content_type="text/html", body=self.body)


class FakeFederalRegisterClient:
    def search_documents(self, query: str, *, per_page: int = 20) -> list[dict]:
        return [{"document_number": "2026-07361"}]

    def get_document(self, document_number: str) -> dict:
        return _federal_register_document(document_number)

    def get_text(self, url: str) -> str:
        return "Semax and Epitalon are also discussed for possible 503A Bulks List inclusion."


def test_build_regulatory_document_extracts_status_and_route_notes() -> None:
    config = load_config(ROOT / "config")
    document = build_regulatory_document(
        document_key="fda:fda_503a_pdf",
        source_id="fda_503a_pdf",
        source_type="fda_pdf",
        url="https://www.fda.gov/media/94155/download",
        title="503A Categories Update",
        content_text=FDA_503A_TEXT,
        config=config,
    )

    assert "ghk_cu" in document.peptide_ids
    assert "Category 1" in document.status_terms
    assert "non-injectable" in document.status_terms
    assert "injectable" in document.status_terms
    assert any("non-injectable GHK-Cu" in note for note in document.route_notes["ghk_cu"])


def test_store_regulatory_document_detects_new_and_changed_documents(tmp_path) -> None:
    db_path = init_db(tmp_path / "watch.db")
    config = load_config(ROOT / "config")
    first = build_regulatory_document(
        document_key="fda:fda_pcac_2026",
        source_id="fda_pcac_2026",
        source_type="fda_page",
        url="https://www.fda.gov/example",
        title="PCAC",
        content_text=FDA_PCAC_TEXT,
        config=config,
    )
    second = build_regulatory_document(
        document_key="fda:fda_pcac_2026",
        source_id="fda_pcac_2026",
        source_type="fda_page",
        url="https://www.fda.gov/example",
        title="PCAC",
        content_text=f"{FDA_PCAC_TEXT} Briefing documents posted.",
        config=config,
    )

    created = store_regulatory_document(db_path, first)
    unchanged = store_regulatory_document(db_path, first)
    changed = store_regulatory_document(db_path, second)

    assert created.inserted is True
    assert unchanged.events_created == 0
    assert changed.changed is True
    assert changed.events_created == 1
    with sqlite3.connect(db_path) as connection:
        event_types = [
            row[0]
            for row in connection.execute("SELECT event_type FROM events ORDER BY id").fetchall()
        ]
    assert event_types == ["fda_pcac_document_detected", "fda_pcac_update"]


def test_normalize_fda_document_from_html_matches_pcac_aliases() -> None:
    config = load_config(ROOT / "config")
    source = SourceConfig(type="page", url="https://www.fda.gov/example", tier="A", cadence="daily")
    fetched = FetchedFdaContent(
        url="https://www.fda.gov/example",
        content_type="text/html",
        body=f"<html><title>PCAC</title><body>{FDA_PCAC_TEXT}</body></html>".encode(),
    )

    document = normalize_fda_document("fda_pcac_2026", source, fetched, config)

    assert document.title == "PCAC"
    assert {"bpc_157", "kpv", "tb_500", "mots_c"} <= set(document.peptide_ids)
    assert "503A Bulks List" in document.status_terms


def test_scan_fda_sources_with_fake_client(tmp_path) -> None:
    db_path = init_db(tmp_path / "watch.db")

    result = scan_fda_sources(
        db_path,
        config_dir=ROOT / "config",
        client=FakeFdaClient(f"<html><title>PCAC</title><body>{FDA_PCAC_TEXT}</body></html>".encode()),
        source_ids=["fda_pcac_2026"],
    )

    assert result.fetched == 1
    assert result.inserted == 1
    assert result.events_created == 1
    assert list_regulatory_documents(db_path, source_prefix="fda_")[0].source_id == "fda_pcac_2026"


def test_normalize_federal_register_document_preserves_docket_and_matches_peptides() -> None:
    config = load_config(ROOT / "config")

    document = normalize_federal_register_document(
        _federal_register_document("2026-07361"),
        "BPC-157 KPV TB-500",
        config,
    )

    assert document.document_key == "federal_register:2026-07361"
    assert document.docket_ids == ["Docket No. FDA-2025-N-6895", "FDA-2025-N-6895"]
    assert {"bpc_157", "kpv", "tb_500"} <= set(document.peptide_ids)
    assert "PCAC" in document.status_terms


def test_scan_federal_register_with_fake_client(tmp_path) -> None:
    db_path = init_db(tmp_path / "watch.db")

    result = scan_federal_register(
        db_path,
        config_dir=ROOT / "config",
        client=FakeFederalRegisterClient(),
        queries=["BPC-157 KPV TB-500"],
    )

    assert result.fetched == 1
    assert result.stored == 1
    assert result.inserted == 1
    assert result.events_created == 1
    with sqlite3.connect(db_path) as connection:
        event_type = connection.execute("SELECT event_type FROM events").fetchone()[0]
    assert event_type == "federal_register_notice_detected"


def test_regulatory_cli_list_commands(tmp_path) -> None:
    db_path = init_db(tmp_path / "watch.db")
    config = load_config(ROOT / "config")
    document = build_regulatory_document(
        document_key="fda:fda_pcac_2026",
        source_id="fda_pcac_2026",
        source_type="fda_page",
        url="https://www.fda.gov/example",
        title="PCAC",
        content_text=FDA_PCAC_TEXT,
        config=config,
    )
    store_regulatory_document(db_path, document)

    result = CliRunner().invoke(app, ["fda", "list", "--db", str(db_path)])

    assert result.exit_code == 0, result.output
    assert "fda_pcac_2026" in result.output
    assert "bpc_157" in result.output


def _federal_register_document(document_number: str) -> dict:
    return {
        "document_number": document_number,
        "title": (
            "Pharmacy Compounding Advisory Committee; Notice of Meeting; "
            "Establishment of a Public Docket"
        ),
        "abstract": "FDA announces a Pharmacy Compounding Advisory Committee meeting.",
        "action": "Notice; establishment of a public docket; request for comments.",
        "dates": "The meeting will be held on July 23 and July 24, 2026.",
        "publication_date": "2026-04-16",
        "html_url": "https://www.federalregister.gov/documents/2026/04/16/2026-07361/example",
        "raw_text_url": "https://www.federalregister.gov/documents/full_text/text/2026/04/16/2026-07361.txt",
        "docket_ids": ["Docket No. FDA-2025-N-6895"],
        "dockets": [
            {
                "id": "FDA-2025-N-6895",
                "title": "Bulk Drug Substances Nominated for Inclusion on the Section 503A Bulks List",
            }
        ],
        "excerpts": (
            "On July 23, 2026, the Committee will discuss BPC-157, KPV, TB-500, "
            "and MOTs-C for potential inclusion on the 503A Bulks List."
        ),
    }
