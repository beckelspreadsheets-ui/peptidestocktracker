import copy
import sqlite3
from pathlib import Path

import pytest

from peptide_watch.config import load_config
from peptide_watch.database import init_db
from peptide_watch.events import insert_event
from peptide_watch.sources.clinicaltrials import (
    normalize_study,
    scan_clinicaltrials,
    store_trial_record,
)
from peptide_watch.sources.fda import FetchedFdaContent, scan_fda_sources
from peptide_watch.sources.regulatory import build_regulatory_document, store_regulatory_document

from test_clinicaltrials import _study_payload

ROOT = Path(__file__).resolve().parents[1]
CONFIG_DIR = ROOT / "config"


def _regulatory_document(config, *, text: str, raw: bytes, parser_version: int = 1):
    return build_regulatory_document(
        document_key="fda:test_source",
        source_id="test_source",
        source_type="fda_page",
        url="https://example.gov/page",
        content_text=text,
        config=config,
        raw_content=raw,
        parser_version=parser_version,
    )


def _payload_with_nct(nct_id: str) -> dict:
    payload = copy.deepcopy(_study_payload())
    payload["protocolSection"]["identificationModule"]["nctId"] = nct_id
    return payload


class FakeFdaClient:
    """Maps configured source URLs to bodies; raises for urls marked broken."""

    def __init__(self, bodies: dict[str, bytes], broken: set[str] | None = None):
        self.bodies = bodies
        self.broken = broken or set()

    def fetch(self, url: str) -> FetchedFdaContent:
        if url in self.broken:
            raise ConnectionError(f"fetch failed: {url}")
        return FetchedFdaContent(url=url, content_type="text/html", body=self.bodies[url])


class SweepClinicalTrialsClient:
    """Returns one fixed study for every lookup and query, like a full sweep."""

    def __init__(self, payload: dict):
        self.payload = payload

    def get_study(self, nct_id: str) -> dict:
        return self.payload

    def search_studies(self, term: str, *, page_size: int = 25, max_pages: int = 1) -> list[dict]:
        return [self.payload]


def _events(db_path, where: str = "1=1") -> list[tuple]:
    with sqlite3.connect(db_path) as connection:
        return connection.execute(
            f"SELECT event_type, field, old_value, new_value, run_id FROM events WHERE {where} ORDER BY id"
        ).fetchall()


def test_rescan_unchanged_content_creates_no_events_or_source_documents(tmp_path) -> None:
    config = load_config(CONFIG_DIR)
    db_path = init_db(tmp_path / "watch.db")
    document = _regulatory_document(config, text="503A Bulks List includes BPC-157", raw=b"v1")

    first = store_regulatory_document(db_path, document, run_id="run-1")
    second = store_regulatory_document(db_path, document, run_id="run-2")

    assert first.events_created == 1
    assert second.events_created == 0 and second.changed is False
    with sqlite3.connect(db_path) as connection:
        assert connection.execute("SELECT COUNT(*) FROM events").fetchone()[0] == 1
        assert connection.execute("SELECT COUNT(*) FROM source_documents").fetchone()[0] == 1


def test_volatile_markup_change_does_not_create_event(tmp_path) -> None:
    config = load_config(CONFIG_DIR)
    db_path = init_db(tmp_path / "watch.db")
    text = "503A Bulks List includes BPC-157"

    store_regulatory_document(
        db_path,
        _regulatory_document(config, text=text, raw=b"<html ts=1>same text</html>"),
        run_id="run-1",
    )
    result = store_regulatory_document(
        db_path,
        _regulatory_document(config, text=text, raw=b"<html ts=2>same text</html>"),
        run_id="run-2",
    )

    assert result.changed is False and result.events_created == 0
    with sqlite3.connect(db_path) as connection:
        assert connection.execute("SELECT COUNT(*) FROM events").fetchone()[0] == 1


def test_parser_upgrade_with_identical_raw_suppresses_events(tmp_path) -> None:
    config = load_config(CONFIG_DIR)
    db_path = init_db(tmp_path / "watch.db")
    raw = b"<html>nav junk + real text</html>"

    store_regulatory_document(
        db_path,
        _regulatory_document(config, text="nav junk real text", raw=raw, parser_version=1),
        run_id="run-1",
    )
    result = store_regulatory_document(
        db_path,
        _regulatory_document(config, text="real text", raw=raw, parser_version=2),
        run_id="run-2",
    )

    assert result.changed is False and result.events_created == 0
    with sqlite3.connect(db_path) as connection:
        row = connection.execute(
            "SELECT content_text, parser_version FROM regulatory_documents"
        ).fetchone()
        events = connection.execute("SELECT COUNT(*) FROM events").fetchone()[0]
        snapshots = connection.execute(
            "SELECT COUNT(*) FROM regulatory_document_snapshots"
        ).fetchone()[0]
    assert row == ("real text", 2)  # re-extraction applied silently
    assert events == 1  # only the initial detection event
    assert snapshots == 2


def test_repeated_transition_emits_one_event_per_run(tmp_path) -> None:
    db_path = init_db(tmp_path / "watch.db")

    store_trial_record(db_path, normalize_study(_study_payload(status="NOT_YET_RECRUITING")), run_id="run-1")
    store_trial_record(db_path, normalize_study(_study_payload(status="RECRUITING")), run_id="run-2")
    store_trial_record(db_path, normalize_study(_study_payload(status="NOT_YET_RECRUITING")), run_id="run-3")
    store_trial_record(db_path, normalize_study(_study_payload(status="RECRUITING")), run_id="run-4")

    transitions = _events(db_path, "event_type = 'trial_status_change'")
    assert [(t[2], t[3], t[4]) for t in transitions] == [
        ("NOT_YET_RECRUITING", "RECRUITING", "run-2"),
        ("RECRUITING", "NOT_YET_RECRUITING", "run-3"),
        ("NOT_YET_RECRUITING", "RECRUITING", "run-4"),
    ]
    assert all(t[1] == "overall_status" for t in transitions)


def test_identical_event_within_one_run_is_deduplicated(tmp_path) -> None:
    db_path = init_db(tmp_path / "watch.db")
    kwargs = dict(
        source_id="s",
        external_id="x",
        event_type="t",
        field="f",
        old_value="a",
        new_value="b",
        run_id="run-1",
        title="t",
        what_changed="w",
        why_it_matters="y",
        confidence="high",
        severity="low",
        directness="direct",
        stock_market_relevance="r",
    )

    with sqlite3.connect(db_path) as connection:
        assert insert_event(connection, **kwargs) is True
        assert insert_event(connection, **kwargs) is False  # same run: deduped
        assert insert_event(connection, **{**kwargs, "run_id": "run-2"}) is True


def test_record_disappearance_uses_hysteresis(tmp_path) -> None:
    db_path = init_db(tmp_path / "watch.db")
    # Seed a trial that the sweeps below will never return.
    missing = normalize_study(_payload_with_nct("NCT00000001"))
    store_trial_record(db_path, missing, run_id="seed")
    client = SweepClinicalTrialsClient(_study_payload())

    def sweep(run_id: str):
        return scan_clinicaltrials(db_path, config_dir=CONFIG_DIR, client=client, run_id=run_id)

    sweep("run-1")
    sweep("run-2")
    assert _events(db_path, "event_type = 'record_disappeared'") == []

    sweep("run-3")  # third consecutive miss crosses the threshold
    disappeared = _events(db_path, "event_type = 'record_disappeared'")
    assert len(disappeared) == 1
    assert disappeared[0][1:4] == ("presence", "present", "missing")

    sweep("run-4")  # past the threshold: no repeat alert
    assert len(_events(db_path, "event_type = 'record_disappeared'")) == 1

    # Reappearance resets the counter.
    store_trial_record(db_path, missing, run_id="run-5")
    with sqlite3.connect(db_path) as connection:
        miss_count = connection.execute(
            "SELECT miss_count FROM clinical_trials WHERE nct_id = 'NCT00000001'"
        ).fetchone()[0]
    assert miss_count == 0


def test_fda_scan_isolates_failing_source(tmp_path) -> None:
    config = load_config(CONFIG_DIR)
    db_path = init_db(tmp_path / "watch.db")
    good_url = config.sources["fda_pcac_2026"].url
    bad_url = config.sources["fda_safety_risk"].url
    client = FakeFdaClient(
        bodies={good_url: b"<html><title>PCAC</title>BPC-157 meeting</html>"},
        broken={bad_url},
    )

    result = scan_fda_sources(
        db_path,
        config_dir=CONFIG_DIR,
        client=client,
        source_ids=["fda_pcac_2026", "fda_safety_risk"],
    )

    assert result.stored == 1
    assert len(result.errors) == 1 and "fda_safety_risk" in result.errors[0]
    with sqlite3.connect(db_path) as connection:
        assert connection.execute("SELECT COUNT(*) FROM regulatory_documents").fetchone()[0] == 1


def test_fda_scan_raises_when_every_source_fails(tmp_path) -> None:
    config = load_config(CONFIG_DIR)
    db_path = init_db(tmp_path / "watch.db")
    urls = {config.sources[s].url for s in ["fda_pcac_2026", "fda_safety_risk"]}
    client = FakeFdaClient(bodies={}, broken=urls)

    with pytest.raises(RuntimeError, match="failed for all sources"):
        scan_fda_sources(
            db_path,
            config_dir=CONFIG_DIR,
            client=client,
            source_ids=["fda_pcac_2026", "fda_safety_risk"],
        )
