import sqlite3
from pathlib import Path

import pytest

pytest.importorskip("fastapi")
from fastapi.testclient import TestClient  # noqa: E402

from peptide_watch.database import init_db  # noqa: E402
from peptide_watch.events import insert_event  # noqa: E402
from peptide_watch.runtime import ledger  # noqa: E402
from peptide_watch.web.app import create_app  # noqa: E402

ROOT = Path(__file__).resolve().parents[1]
CONFIG_DIR = ROOT / "config"


@pytest.fixture
def client(tmp_path):
    db_path = init_db(tmp_path / "watch.db")
    with sqlite3.connect(db_path) as con:
        insert_event(
            con,
            source_id="sec_fulltext",
            external_id="newco",
            event_type="new_company_peptide_disclosure",
            field="",
            old_value="",
            new_value="x",
            run_id="r1",
            title="New filer disclosed BPC-157",
            what_changed="Confirmed fact: a new filer disclosed a target peptide.",
            why_it_matters="y",
            confidence="high",
            severity="high",
            directness="direct",
            stock_market_relevance="Possible market relevance only.",
            peptide_id="bpc_157",
        )
        insert_event(
            con,
            source_id="pubmed",
            external_id="pmid1",
            event_type="pubmed_publication",
            field="",
            old_value="",
            new_value="x",
            run_id="r1",
            title="A routine publication",
            what_changed="",
            why_it_matters="y",
            confidence="high",
            severity="medium",
            directness="direct",
            stock_market_relevance="Possible market relevance only.",
            peptide_id="ghk_cu",
        )
        con.commit()
    # a tracked run so source-health/job-runs have data
    con = sqlite3.connect(db_path)
    try:
        run_id = ledger.create_run(con, ["clinicaltrials", "fda"])
        ledger.start_task(con, run_id, "clinicaltrials")
        ledger.finish_task(con, run_id, "clinicaltrials", "done", counts={"events_created": 1})
        ledger.finish_task(con, run_id, "fda", "error", error="boom\n403 Forbidden")
        ledger.finish_run(con, run_id, "completed", ledger.run_summary(con, run_id))
    finally:
        con.close()
    return TestClient(create_app(db_path=db_path, config_dir=CONFIG_DIR)), db_path


def test_health(client):
    c, _ = client
    r = c.get("/api/health")
    assert r.status_code == 200
    body = r.json()
    assert body["db_ok"] is True
    assert body["counts"]["events"] == 2


def test_config_and_watchlist(client):
    c, _ = client
    assert c.get("/api/config/peptides").status_code == 200
    wl = c.get("/api/watchlist").json()
    assert any(item["id"] == "hims" for item in wl)
    assert "ticker" in wl[0] and "tier" in wl[0]


def test_events_list_pagination_and_compliance(client):
    c, _ = client
    body = c.get("/api/events").json()
    assert body["total"] == 2 and body["limit"] == 50
    assert "disclaimers" in body
    for item in body["items"]:
        # every event carries the compliance fields
        for field in ("severity", "confidence", "directness", "source_id"):
            assert field in item


def test_events_filter_by_severity(client):
    c, _ = client
    body = c.get("/api/events?severity=high").json()
    assert body["total"] == 1
    assert body["items"][0]["event_type"] == "new_company_peptide_disclosure"


def test_event_detail_and_404(client):
    c, _ = client
    first = c.get("/api/events").json()["items"][0]["id"]
    detail = c.get(f"/api/events/{first}")
    assert detail.status_code == 200
    assert "disclaimers" in detail.json()
    assert c.get("/api/events/999999").status_code == 404


def test_briefing_endpoint(client):
    c, _ = client
    body = c.get("/api/briefing").json()
    assert body["schema_version"] == "1.0"
    assert body["top_events"][0]["event_type"] == "new_company_peptide_disclosure"


def test_source_health_and_job_runs(client):
    c, _ = client
    health = c.get("/api/source-health").json()
    fda = next(h for h in health if h["source_id"] == "fda")
    assert fda["status"] == "error" and "403" in fda["last_error"]
    runs = c.get("/api/job-runs").json()
    assert runs and runs[0]["status"] == "completed"


def test_api_connection_is_read_only(client):
    from peptide_watch.database import connect_readonly

    _, db_path = client
    con = connect_readonly(db_path)
    try:
        with pytest.raises(sqlite3.OperationalError):
            con.execute("INSERT INTO events (event_type, title) VALUES ('x','y')")
    finally:
        con.close()
