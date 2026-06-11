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


def _uspto_record(app_number: str, *, assignee: str | None = None) -> dict:
    record: dict = {
        "applicationNumberText": app_number,
        "applicationMetaData": {
            "inventionTitle": "Stabilized transdermal composition",
            "firstInventorName": "Jane Doe",
            "filingDate": "2026-01-15",
            "cpcClassificationBag": ["A61K 38/10"],
        },
    }
    if assignee is not None:
        record["assignmentBag"] = [{"assigneeBag": [{"assigneeNameText": assignee}]}]
    return record


class FakeUsptoClient:
    api_key = "test-key"

    def __init__(self, record: dict | None = None):
        self.record = record or _uspto_record("18123456")

    def search(self, query: str, *, limit: int = 25):
        return [self.record]


def test_uspto_peptide_only_patent_is_medium_tier(tmp_path) -> None:
    from peptide_watch.sources.uspto import scan_uspto_patents

    db_path = init_db(tmp_path / "watch.db")
    result = scan_uspto_patents(
        db_path,
        config_dir=CONFIG_DIR,
        client=FakeUsptoClient(_uspto_record("18123456", assignee="Red Mountain Holdings, LLC")),
        queries=['"BPC-157"'],
    )

    assert result.stored == 1 and result.inserted == 1
    with sqlite3.connect(db_path) as connection:
        document = connection.execute(
            "SELECT document_key, source_type, peptide_ids_json FROM regulatory_documents"
        ).fetchone()
        event = connection.execute("SELECT event_type, severity FROM events").fetchone()
    assert document[0] == "uspto:18123456" and document[1] == "uspto_patent"
    assert "bpc_157" in document[2]  # query phrase folded into text -> tagged
    assert event == ("patent_publication", "medium")  # no watchlist owner


def test_uspto_assignment_to_public_company_is_critical(tmp_path) -> None:
    from peptide_watch.sources.uspto import scan_uspto_patents

    db_path = init_db(tmp_path / "watch.db")
    # "Hims & Hers Health" is a public watchlist company.
    result = scan_uspto_patents(
        db_path,
        config_dir=CONFIG_DIR,
        client=FakeUsptoClient(_uspto_record("18999999", assignee="Hims & Hers Health, Inc.")),
        queries=['"BPC-157"'],
    )

    assert result.stored == 1
    with sqlite3.connect(db_path) as connection:
        event = connection.execute("SELECT event_type, severity FROM events").fetchone()
        metadata = connection.execute(
            "SELECT metadata_json FROM regulatory_documents"
        ).fetchone()[0]
    assert event == ("patent_assignment_to_public_company", "critical")
    assert '"assigned_company_id":"hims"' in metadata.replace(" ", "")


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


class FakeNihReporterClient:
    def search(self, text: str, *, limit: int = 25):
        if "thymosin" not in text.lower():
            return []
        return [
            {
                "project_num": "1R43AG099999-01",
                "appl_id": 12345,
                "project_title": "Thymosin beta-4 wound healing peptide therapeutic",
                "organization": {"org_name": "Tiny Biotech Inc."},
                "activity_code": "R43",
                "award_notice_date": "2026-05-01T00:00:00",
                "abstract_text": "Develop a thymosin beta-4 based product.",
            }
        ]


def test_nih_reporter_scan_flags_sbir_award_as_high(tmp_path) -> None:
    from peptide_watch.sources.nih_reporter import scan_nih_reporter

    db_path = init_db(tmp_path / "watch.db")
    result = scan_nih_reporter(
        db_path,
        config_dir=CONFIG_DIR,
        client=FakeNihReporterClient(),
        queries=["thymosin beta-4"],
    )

    assert result.stored == 1 and result.inserted == 1
    with sqlite3.connect(db_path) as connection:
        document = connection.execute(
            "SELECT document_key, source_type, peptide_ids_json FROM regulatory_documents"
        ).fetchone()
        event = connection.execute("SELECT event_type, severity FROM events").fetchone()
    assert document[0] == "nih_reporter:1R43AG099999-01"
    assert document[1] == "nih_grant"
    assert "thymosin_beta_4" in document[2]
    assert event == ("grant_award", "high")  # R43 = SBIR small-business award


def test_globenewswire_feeds_route_to_watched_pages() -> None:
    config = load_config(CONFIG_DIR)
    coverage = source_coverage(config)
    assert coverage["gnw_bpc157"] == "watched_pages"
    assert coverage["gnw_tb500"] == "watched_pages"


def _reg_doc(doc_id, *, doc_type, open_for_comment, comment_end="2026-07-23T03:59:59Z"):
    return {
        "id": doc_id,
        "attributes": {
            "title": "Pharmacy Compounding Advisory Committee; BPC-157 nomination",
            "documentType": doc_type,
            "agencyId": "FDA",
            "docketId": doc_id.rsplit("-", 1)[0],
            "openForComment": open_for_comment,
            "commentEndDate": comment_end if open_for_comment else None,
            "postedDate": "2026-06-10T05:00:00Z",
            "highlightedContent": "nomination of <mark>BPC-157</mark> for compounding",
        },
    }


class FakeRegulationsClient:
    def __init__(self, documents):
        self.documents = documents

    def search(self, term, *, page_size=20):
        return self.documents


def test_regulations_notice_open_for_comment_is_high(tmp_path) -> None:
    from peptide_watch.sources.regulations import scan_regulations

    db_path = init_db(tmp_path / "watch.db")
    client = FakeRegulationsClient([_reg_doc("FDA-2025-N-6895-0001", doc_type="Notice", open_for_comment=True)])
    result = scan_regulations(db_path, config_dir=CONFIG_DIR, client=client, queries=["BPC-157"])

    assert result.stored == 1
    with sqlite3.connect(db_path) as connection:
        document = connection.execute(
            "SELECT document_key, peptide_ids_json FROM regulatory_documents"
        ).fetchone()
        event = connection.execute("SELECT event_type, severity FROM events").fetchone()
    assert document[0] == "regulations:FDA-2025-N-6895-0001"
    assert "bpc_157" in document[1]
    assert event == ("regulatory_comment_period_open", "high")


def test_regulations_proposed_rule_open_for_comment_is_critical(tmp_path) -> None:
    from peptide_watch.sources.regulations import scan_regulations

    db_path = init_db(tmp_path / "watch.db")
    client = FakeRegulationsClient([_reg_doc("FDA-2026-N-0001-0001", doc_type="Proposed Rule", open_for_comment=True)])
    result = scan_regulations(db_path, config_dir=CONFIG_DIR, client=client, queries=["BPC-157"])

    assert result.stored == 1
    with sqlite3.connect(db_path) as connection:
        event = connection.execute("SELECT event_type, severity FROM events").fetchone()
    assert event == ("regulatory_rule_open_for_comment", "critical")


def test_regulations_public_comment_is_medium(tmp_path) -> None:
    from peptide_watch.sources.regulations import scan_regulations

    db_path = init_db(tmp_path / "watch.db")
    client = FakeRegulationsClient([_reg_doc("FDA-2025-N-6895-0488", doc_type="Public Submission", open_for_comment=False)])
    result = scan_regulations(db_path, config_dir=CONFIG_DIR, client=client, queries=["BPC-157"])

    assert result.stored == 1
    with sqlite3.connect(db_path) as connection:
        event = connection.execute("SELECT event_type, severity FROM events").fetchone()
    assert event == ("regulatory_public_comment", "medium")
