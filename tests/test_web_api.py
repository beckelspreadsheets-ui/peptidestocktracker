import sqlite3
from pathlib import Path

import pytest

pytest.importorskip("fastapi")
from fastapi.testclient import TestClient  # noqa: E402

from peptide_watch.database import init_db  # noqa: E402
from peptide_watch.events import insert_event  # noqa: E402
from peptide_watch.operator_memory import record_entity_events, upsert_entity  # noqa: E402
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


def test_market_watchlist_endpoint_is_context_only(client, monkeypatch):
    import peptide_watch.web.app as web_app

    c, _ = client

    def fake_market_data(_config):
        return [
            {
                "company_id": "hims",
                "name": "Hims & Hers Health",
                "ticker": "HIMS",
                "symbol": "HIMS",
                "exchange": "NYSE",
                "status": "ok",
                "provider": "test",
                "price": 20.0,
                "currency": "USD",
                "market_cap": 1_000_000_000,
                "change_1d_pct": 1.0,
                "change_7d_pct": 7.0,
                "change_30d_pct": 30.0,
                "as_of": "2026-06-13T00:00:00+00:00",
                "error": None,
            }
        ]

    monkeypatch.setattr(web_app, "watchlist_market_data", fake_market_data)
    body = c.get("/api/market/watchlist").json()

    assert body["items"][0]["company_id"] == "hims"
    assert body["items"][0]["market_cap"] == 1_000_000_000
    assert "not a recommendation" in body["source_note"]
    assert "disclaimers" in body


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


def test_events_filter_by_title_search(client):
    c, _ = client
    # the q filter approximates company/title search (events carry no company FK)
    body = c.get("/api/events?q=BPC-157").json()
    assert body["total"] == 1
    assert "BPC-157" in body["items"][0]["title"]
    assert c.get("/api/events?q=nonexistentco").json()["total"] == 0


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


def test_operator_entities_are_read_only_and_public_safe(client, tmp_path):
    _, db_path = client
    operator_db = tmp_path / "operator_state.db"
    row = upsert_entity(
        operator_db,
        "BHIC",
        status="watch",
        priority="high",
        note="operator note should not be exposed through read-only cockpit API",
        appearance_count=2,
        source_url_count=1,
    )
    record_entity_events(
        operator_db,
        "BHIC",
        [
            {
                "run_id": "run-123",
                "event_type": "new_company_peptide_disclosure",
                "source_id": "sec_fulltext",
                "source_url": "https://www.sec.gov/example",
                "created_at": "2026-06-13T00:00:00+00:00",
                "what_changed": "Confirmed fact: BHIC disclosed a target peptide in a public filing.",
            }
        ],
    )
    upsert_entity(operator_db, "CohBar", status="ignore", priority="low")

    scoped = TestClient(
        create_app(db_path=db_path, config_dir=CONFIG_DIR, operator_db_path=operator_db)
    )
    body = scoped.get("/api/operator/entities?status=watch").json()
    assert [item["entity_key"] for item in body["items"]] == [row["entity_key"]]
    assert body["items"][0]["has_notes"] is True
    assert "user_notes" not in body["items"][0]
    assert "disclaimers" in body

    detail = scoped.get("/api/operator/entities/bhic").json()
    assert detail["entity"]["display_name"] == "BHIC"
    assert "user_notes" not in detail["entity"]
    assert detail["source_facts"][0]["run_id"] == "run-123"
    assert detail["source_facts"][0]["source_url"] == "https://www.sec.gov/example"

    assert scoped.post("/api/operator/watch").status_code in {404, 405}
    assert scoped.get("/api/operator/entities?status=bad").status_code == 400


def test_operator_deadlines_endpoint_uses_tracker_facts(client):
    c, _ = client
    body = c.get("/api/operator/deadlines").json()
    assert "items" in body
    assert "disclaimers" in body


def test_api_connection_is_read_only(client):
    from peptide_watch.database import connect_readonly

    _, db_path = client
    con = connect_readonly(db_path)
    try:
        with pytest.raises(sqlite3.OperationalError):
            con.execute("INSERT INTO events (event_type, title) VALUES ('x','y')")
    finally:
        con.close()


def test_serves_dashboard_when_dist_present(tmp_path):
    from peptide_watch.database import init_db
    from peptide_watch.web.app import create_app

    db_path = init_db(tmp_path / "watch.db")
    dist = tmp_path / "dist"
    (dist / "assets").mkdir(parents=True)
    (dist / "index.html").write_text("<title>cockpit</title>", encoding="utf-8")
    (dist / "assets" / "app.js").write_text("console.log(1)", encoding="utf-8")
    c = TestClient(create_app(db_path=db_path, config_dir=CONFIG_DIR, dashboard_dist=dist))

    assert "cockpit" in c.get("/").text  # index.html
    assert c.get("/events").status_code == 200  # SPA fallback
    assert "console.log" in c.get("/assets/app.js").text  # real static file
    assert c.get("/api/health").status_code == 200  # API not shadowed
    # path traversal is refused (falls back to index.html, never serves outside dist)
    assert "cockpit" in c.get("/../../etc/hosts").text
