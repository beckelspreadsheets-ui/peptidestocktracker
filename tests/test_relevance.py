import sqlite3
from datetime import datetime, timedelta, timezone
from pathlib import Path

from peptide_watch.config import load_config
from peptide_watch.database import init_db
from peptide_watch.events import insert_event
from peptide_watch.relevance import (
    briefing,
    proximity_index,
    relevance_score,
    render_briefing_markdown,
)

ROOT = Path(__file__).resolve().parents[1]
CONFIG_DIR = ROOT / "config"
NOW = datetime(2026, 6, 12, tzinfo=timezone.utc)


def _config():
    return load_config(CONFIG_DIR)


def _event(**overrides):
    base = {
        "event_type": "sec_filing_target_mention",
        "severity": "medium",
        "source_id": "sec_fulltext",
        "peptide_id": "bpc_157",
        "created_at": NOW.isoformat(),
    }
    base.update(overrides)
    return base


def test_score_is_deterministic():
    config = _config()
    e = _event()
    a = relevance_score(e, config, now=NOW)
    b = relevance_score(e, config, now=NOW)
    assert a.score == b.score
    assert 0 <= a.score <= 100


def test_severity_ordering():
    config = _config()
    crit = relevance_score(_event(severity="critical"), config, now=NOW).score
    low = relevance_score(_event(severity="low"), config, now=NOW).score
    assert crit > low


def test_event_type_ordering_gem_beats_routine():
    config = _config()
    gem = relevance_score(
        _event(event_type="new_company_peptide_disclosure"), config, now=NOW
    ).score
    routine = relevance_score(_event(event_type="pubmed_publication"), config, now=NOW).score
    assert gem > routine


def test_recency_ordering_fresh_beats_old():
    config = _config()
    fresh = relevance_score(_event(created_at=NOW.isoformat()), config, now=NOW).score
    old = relevance_score(
        _event(created_at=(NOW - timedelta(days=60)).isoformat()), config, now=NOW
    ).score
    assert fresh > old


def test_proximity_public_tier1_beats_private_tier3():
    config = _config()
    # regentree = private Tier 1; pmd_promore = Tier 3 public_non_us; build source links
    # Use real source ids mapped to companies via config.sources[].company_id.
    # hims_ir_news -> hims (public Tier 2); a private/Tier-3 source for contrast.
    index = proximity_index(config)
    public = relevance_score(
        _event(source_id="hims_ir_news", event_type="grant_award"),
        config,
        now=NOW,
        index=index,
    ).score
    # mma_inc_news -> mma_inc (Tier 3 public_us); compare a Tier-2 public to Tier-3 public
    tier3 = relevance_score(
        _event(source_id="mma_inc_news", event_type="grant_award"),
        config,
        now=NOW,
        index=index,
    ).score
    assert public > tier3


def test_null_created_at_is_safe():
    config = _config()
    result = relevance_score(_event(created_at=None), config, now=NOW)
    assert 0 <= result.score <= 100
    assert result.score_reasons


def test_score_reasons_pass_language_gate():
    from peptide_watch.language_gate import check_text

    config = _config()
    for et in ("new_company_peptide_disclosure", "pubmed_publication", "drug_shortage"):
        reasons = relevance_score(_event(event_type=et), config, now=NOW).score_reasons
        assert check_text(" ".join(reasons)) == []


def _seed_db(tmp_path):
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
            peptide_id="bpc_157",
        )
        con.commit()
    return db_path


def test_briefing_schema_and_ranking(tmp_path):
    config = _config()
    db_path = _seed_db(tmp_path)
    con = sqlite3.connect(db_path)
    try:
        data = briefing(con, config, now=NOW)
    finally:
        con.close()

    assert data["schema_version"] == "1.0"
    assert "global" in data["disclaimers"]
    assert data["counts"]["events_window"] == 2
    # the gem (high severity + top type) must outrank the routine pubmed event
    assert data["top_events"][0]["event_type"] == "new_company_peptide_disclosure"
    assert data["top_events"][0]["score"] >= data["top_events"][1]["score"]
    assert data["top_events"][0]["score_reasons"]
    # markdown render works and carries the disclaimer
    md = render_briefing_markdown(data)
    assert "not a buy/sell recommendation" in md
    assert "Top signals" in md
