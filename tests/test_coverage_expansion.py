import shutil
import sqlite3
from pathlib import Path

from typer.testing import CliRunner

from peptide_watch.cli import app
from peptide_watch.config import load_config
from peptide_watch.coverage import source_coverage, unclaimed_sources
from peptide_watch.database import init_db
from peptide_watch.sources.company_pages import FetchedCompanyPage
from peptide_watch.sources.pubmed import scan_pubmed
from peptide_watch.sources.sec_fulltext import scan_sec_fulltext
from peptide_watch.sources.watched_pages import scan_watched_pages

ROOT = Path(__file__).resolve().parents[1]
CONFIG_DIR = ROOT / "config"

RSS_BODY = b"""<?xml version="1.0"?>
<rss version="2.0"><channel><title>Patent feed</title>
<item><title>Stabilized BPC-157 composition patent published</title>
<link>https://example.org/patents/1</link>
<description>Patent application mentioning BPC-157 microneedle delivery.</description>
</item>
<item><title>Unrelated widget patent</title>
<link>https://example.org/patents/2</link>
<description>Nothing relevant here.</description>
</item>
</channel></rss>"""


class FakePageClient:
    def __init__(self, body: bytes, content_type: str = "text/html"):
        self.body = body
        self.content_type = content_type

    def fetch(self, url: str, **kwargs) -> FetchedCompanyPage:
        return FetchedCompanyPage(url=url, content_type=self.content_type, body=self.body)


class FakePubMedClient:
    def search(self, term: str, *, retmax: int = 20) -> list[str]:
        return ["12345678"]

    def summaries(self, pmids):
        if "12345678" not in pmids:
            return {}
        return {
            "12345678": {
                "title": "BPC-157 accelerates tendon healing in a randomized model",
                "fulljournalname": "Journal of Peptide Research",
                "pubdate": "2026 May",
                "authors": [{"name": "Doe J"}],
            }
        }


class FakeSecFullTextClient:
    def __init__(self, hits):
        self.hits = hits

    def search(self, phrase: str):
        return self.hits


def _fts_hit(display: str, accession: str, cik: str = "1773751"):
    return {
        "_id": f"{accession}:doc.htm",
        "_source": {
            "cik": [cik],
            "display_names": [display],
            "file_type": "8-K",
            "file_date": "2026-06-10",
        },
    }


def test_every_configured_source_is_claimed_by_a_family() -> None:
    config = load_config(CONFIG_DIR)
    coverage = source_coverage(config)

    assert unclaimed_sources(config) == []
    assert coverage["sedar_plus"] == "watched_pages"
    assert coverage["uspto_assignment"] == "watched_pages"
    assert coverage["wipo_patentscope_rss"] == "watched_pages"
    assert coverage["sec_fulltext"] == "sec_fulltext"
    assert coverage["pubmed"] == "pubmed"
    assert coverage["fda_import_alert_66_66"] == "fda"


def test_config_check_fails_on_unclaimed_source(tmp_path) -> None:
    config_dir = tmp_path / "config"
    shutil.copytree(CONFIG_DIR, config_dir)
    sources_path = config_dir / "sources.yaml"
    sources_path.write_text(
        sources_path.read_text(encoding="utf-8")
        + "  mystery_api:\n    type: api\n    url: https://example.org/api\n"
        + "    tier: B\n    cadence: daily\n",
        encoding="utf-8",
    )

    result = CliRunner().invoke(app, ["config", "check", "--config-dir", str(config_dir)])

    assert result.exit_code == 1
    assert "mystery_api" in result.output


def test_watched_pages_monitors_unclaimed_page_sources(tmp_path) -> None:
    db_path = init_db(tmp_path / "watch.db")
    first = scan_watched_pages(
        db_path,
        config_dir=CONFIG_DIR,
        client=FakePageClient(b"<html><title>SEDAR+</title>BPC-157 filing posted</html>"),
        source_ids=["sedar_plus"],
    )
    changed = scan_watched_pages(
        db_path,
        config_dir=CONFIG_DIR,
        client=FakePageClient(b"<html><title>SEDAR+</title>BPC-157 NEW filing today</html>"),
        source_ids=["sedar_plus"],
    )

    assert first.stored == 1 and first.inserted == 1
    assert changed.changed == 1 and changed.events_created == 1
    with sqlite3.connect(db_path) as connection:
        source_type = connection.execute(
            "SELECT source_type FROM company_documents"
        ).fetchone()[0]
    assert source_type == "watched_page"


def test_watched_pages_creates_one_document_per_feed_entry(tmp_path) -> None:
    db_path = init_db(tmp_path / "watch.db")
    result = scan_watched_pages(
        db_path,
        config_dir=CONFIG_DIR,
        client=FakePageClient(RSS_BODY, content_type="application/rss+xml"),
        source_ids=["wipo_patentscope_rss"],
    )

    assert result.stored == 2
    with sqlite3.connect(db_path) as connection:
        rows = connection.execute(
            "SELECT title, peptide_ids_json FROM company_documents ORDER BY document_key"
        ).fetchall()
        events = connection.execute("SELECT COUNT(*) FROM events").fetchone()[0]
    assert len(rows) == 2
    # only the entry matching a watch term creates an event
    assert events == 1


def test_pubmed_scan_stores_publication_and_emits_event(tmp_path) -> None:
    db_path = init_db(tmp_path / "watch.db")
    result = scan_pubmed(db_path, config_dir=CONFIG_DIR, client=FakePubMedClient())

    assert result.stored == 1 and result.inserted == 1
    with sqlite3.connect(db_path) as connection:
        document = connection.execute(
            "SELECT document_key, source_type, url FROM regulatory_documents"
        ).fetchone()
        event_type = connection.execute("SELECT event_type FROM events").fetchone()[0]
    assert document[0] == "pubmed:12345678"
    assert document[1] == "pubmed_publication"
    assert document[2] == "https://pubmed.ncbi.nlm.nih.gov/12345678/"
    assert event_type == "pubmed_publication"

    rescan = scan_pubmed(db_path, config_dir=CONFIG_DIR, client=FakePubMedClient())
    assert rescan.events_created == 0  # unchanged publication, no duplicate alert


def test_sec_fulltext_matches_watchlist_and_flags_discoveries(tmp_path) -> None:
    db_path = init_db(tmp_path / "watch.db")
    hits = [
        _fts_hit("Hims & Hers Health, Inc.  (HIMS)  (CIK 0001773751)", "0001213900-26-000001"),
        _fts_hit("Unknown Peptide Newco Inc.  (UPNI)  (CIK 0009999999)", "0001213900-26-000002", cik="9999999"),
    ]
    result = scan_sec_fulltext(
        db_path,
        config_dir=CONFIG_DIR,
        client=FakeSecFullTextClient(hits),
        phrases=["BPC-157"],
    )

    assert result.stored == 2
    assert result.company_ids == ["hims"]
    with sqlite3.connect(db_path) as connection:
        rows = connection.execute(
            "SELECT company_key, metadata_json FROM company_documents ORDER BY document_key"
        ).fetchall()
        event_types = {
            row[0]
            for row in connection.execute("SELECT event_type FROM events").fetchall()
        }
    known = next(row for row in rows if row[0] == "hims")
    discovery = next(row for row in rows if row[0] is None)
    assert '"discovery":false' in known[1].replace(" ", "")
    assert '"discovery":true' in discovery[1].replace(" ", "")
    assert event_types == {"sec_filing_target_mention"}


class FakeOpenFdaClient:
    def search_enforcements(self, term: str, *, limit: int = 50):
        if term != "GHK-Cu":
            return []
        return [
            {
                "recall_number": "D-0051-2026",
                "status": "Ongoing",
                "classification": "Class II",
                "product_description": "GHK-Cu (Copper Peptide) for Injection, all strengths.",
                "reason_for_recall": "Lack of Assurance of Sterility",
                "recalling_firm": "GenoGenix LLC",
                "report_date": "20251015",
                "event_id": "97369",
            }
        ]


def test_openfda_scan_stores_enforcement_and_emits_high_severity_event(tmp_path) -> None:
    from peptide_watch.sources.openfda import scan_openfda_enforcement

    db_path = init_db(tmp_path / "watch.db")
    result = scan_openfda_enforcement(
        db_path,
        config_dir=CONFIG_DIR,
        client=FakeOpenFdaClient(),
        terms=["peptide", "GHK-Cu"],
    )

    assert result.stored == 1 and result.inserted == 1
    with sqlite3.connect(db_path) as connection:
        document = connection.execute(
            "SELECT document_key, source_type, peptide_ids_json FROM regulatory_documents"
        ).fetchone()
        event = connection.execute("SELECT event_type, severity FROM events").fetchone()
    assert document[0] == "openfda:D-0051-2026"
    assert document[1] == "fda_enforcement"
    assert "ghk_cu" in document[2]
    assert event == ("fda_enforcement_report", "high")

    rescan = scan_openfda_enforcement(
        db_path, config_dir=CONFIG_DIR, client=FakeOpenFdaClient(), terms=["GHK-Cu"]
    )
    assert rescan.events_created == 0


def test_webhook_channel_posts_json_from_env(monkeypatch) -> None:
    import httpx

    from peptide_watch.alerts.channels import WebhookChannel

    posts = []

    def handler(request):
        posts.append((str(request.url), request.read()))
        return httpx.Response(204)

    monkeypatch.setenv("PEPTIDE_WATCH_WEBHOOK_URL", "https://hooks.example.com/abc")
    channel = WebhookChannel(transport=httpx.MockTransport(handler))
    channel.send("test alert")

    assert posts[0][0] == "https://hooks.example.com/abc"
    assert b'"content"' in posts[0][1] and b"test alert" in posts[0][1]


def test_webhook_channel_requires_env_url(monkeypatch) -> None:
    import pytest

    from peptide_watch.alerts.channels import WebhookChannel

    monkeypatch.delenv("PEPTIDE_WATCH_WEBHOOK_URL", raising=False)
    with pytest.raises(ValueError, match="PEPTIDE_WATCH_WEBHOOK_URL"):
        WebhookChannel()


class FakeUsptoClient:
    api_key = "test-key"

    def search(self, query: str, *, limit: int = 25):
        return [
            {
                "applicationNumberText": "18123456",
                "inventionTitle": "Stabilized BPC-157 transdermal composition",
                "applicantName": "Example Therapeutics Inc.",
            }
        ]


def test_uspto_scan_stores_patent_and_emits_high_severity_event(tmp_path) -> None:
    from peptide_watch.sources.uspto import scan_uspto_patents

    db_path = init_db(tmp_path / "watch.db")
    result = scan_uspto_patents(
        db_path, config_dir=CONFIG_DIR, client=FakeUsptoClient(), queries=['"BPC-157"']
    )

    assert result.stored == 1 and result.inserted == 1
    with sqlite3.connect(db_path) as connection:
        document = connection.execute(
            "SELECT document_key, source_type FROM regulatory_documents"
        ).fetchone()
        event = connection.execute("SELECT event_type, severity FROM events").fetchone()
    assert document == ("uspto:18123456", "uspto_patent")
    assert event == ("patent_publication", "high")


def test_uspto_record_extraction_handles_unknown_envelopes() -> None:
    from peptide_watch.sources.uspto import _extract_records

    assert _extract_records({"patentFileWrapperDataBag": [{"a": 1}]}) == [{"a": 1}]
    assert _extract_records({"someFutureKey": [{"b": 2}], "count": 1}) == [{"b": 2}]
    assert _extract_records({"count": 0}) == []


def test_uspto_scan_without_key_raises_actionable_error(tmp_path, monkeypatch) -> None:
    from peptide_watch.sources.uspto import scan_uspto_patents

    monkeypatch.delenv("PEPTIDE_WATCH_USPTO_API_KEY", raising=False)
    db_path = init_db(tmp_path / "watch.db")
    import pytest

    with pytest.raises(RuntimeError, match="PEPTIDE_WATCH_USPTO_API_KEY"):
        scan_uspto_patents(db_path, config_dir=CONFIG_DIR, queries=['"BPC-157"'])
