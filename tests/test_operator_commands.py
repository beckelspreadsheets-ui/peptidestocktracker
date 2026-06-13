import sqlite3
from pathlib import Path

from peptide_watch.database import init_db
from peptide_watch.events import insert_event
from peptide_watch.language_gate import check_text
from peptide_watch.operator_commands import handle_command, init_operator_db
from peptide_watch.runtime import ledger

ROOT = Path(__file__).resolve().parents[1]
CONFIG_DIR = ROOT / "config"


def _seed_db(tmp_path):
    db_path = init_db(tmp_path / "watch.db")
    with sqlite3.connect(db_path) as con:
        insert_event(
            con,
            source_id="sec_fulltext",
            external_id="BHIC",
            event_type="new_company_peptide_disclosure",
            field="",
            old_value="",
            new_value="BPC-157",
            run_id="r1",
            title="BHIC disclosed BPC-157 in a public filing",
            what_changed="BHIC appeared in SEC full-text discovery for BPC-157.",
            why_it_matters="Public-source recurrence for operator review.",
            confidence="high",
            severity="high",
            directness="direct",
            stock_market_relevance="Possible market relevance only.",
            peptide_id="bpc_157",
        )
        insert_event(
            con,
            source_id="sec_fulltext",
            external_id="CohBar",
            event_type="new_company_peptide_disclosure",
            field="",
            old_value="",
            new_value="MOTS-c",
            run_id="r1",
            title="CohBar disclosed MOTS-c in a public filing",
            what_changed="CohBar appeared in SEC full-text discovery for MOTS-c.",
            why_it_matters="Public-source recurrence for operator review.",
            confidence="high",
            severity="high",
            directness="direct",
            stock_market_relevance="Possible market relevance only.",
            peptide_id="mots_c",
        )
        run_id = ledger.create_run(con, ["sec_fulltext", "uspto_patents"])
        ledger.start_task(con, run_id, "sec_fulltext")
        ledger.finish_task(con, run_id, "sec_fulltext", "done", counts={"events_created": 1})
        ledger.finish_task(con, run_id, "uspto_patents", "error", error="403 Forbidden")
        ledger.finish_run(con, run_id, "completed", ledger.run_summary(con, run_id))
    return db_path


def test_hq_commands_are_deterministic_and_language_clean(tmp_path) -> None:
    db_path = _seed_db(tmp_path)
    operator_db = tmp_path / "operator_state.db"
    commands = [
        "/status",
        "/briefing",
        "/discoveries",
        "/sourcehealth",
        "/deadlines",
        "/watch BHIC SEC recurrence",
        "/ignore CohBar noisy",
        "/promote BHIC queue review",
        "/archive CohBar stale",
        "/setpriority BHIC high",
        "/why BHIC",
        "/notes BHIC",
    ]

    outputs = []
    for command in commands:
        result = handle_command(
            command,
            db_path=db_path,
            config_dir=CONFIG_DIR,
            operator_db_path=operator_db,
            message_id="1",
        )
        outputs.append(result.text)
        assert check_text(result.text) == []

    assert "Latest run:" in outputs[0]
    assert "BHIC saved to operator watch list" in outputs[5]
    assert "BHIC operator priority set to high" in outputs[9]
    assert "BHIC disclosed BPC-157" in outputs[10]
    assert operator_db.exists()


def test_operator_state_is_separate_from_watch_db(tmp_path) -> None:
    watch_db = _seed_db(tmp_path)
    operator_db = init_operator_db(tmp_path / "operator_state.db")

    handle_command(
        "/watch BHIC public filing recurrence",
        db_path=watch_db,
        config_dir=CONFIG_DIR,
        operator_db_path=operator_db,
    )

    with sqlite3.connect(operator_db) as con:
        row = con.execute(
            "SELECT display_name, status, priority, user_notes FROM operator_entities WHERE entity_key = 'bhic'"
        ).fetchone()
    assert row == ("BHIC", "watch", "normal", "public filing recurrence")

    with sqlite3.connect(watch_db) as con:
        tables = {
            row[0]
            for row in con.execute(
                "SELECT name FROM sqlite_master WHERE type = 'table' AND name = 'operator_entities'"
            )
        }
    assert tables == set()


def test_operator_memory_schema_and_cursor_are_phase3_durable(tmp_path) -> None:
    watch_db = _seed_db(tmp_path)
    operator_db = tmp_path / "operator_state.db"

    handle_command(
        "/watch BHIC SEC recurrence",
        db_path=watch_db,
        config_dir=CONFIG_DIR,
        operator_db_path=operator_db,
    )

    with sqlite3.connect(operator_db) as con:
        con.row_factory = sqlite3.Row
        entity = con.execute(
            "SELECT * FROM operator_entities WHERE entity_key = 'bhic'"
        ).fetchone()
        event_count = con.execute(
            "SELECT COUNT(*) FROM operator_entity_events WHERE entity_key = 'bhic'"
        ).fetchone()[0]
        cursor_before = con.execute("SELECT * FROM briefing_cursor WHERE id = 1").fetchone()
        columns = {
            row[1]
            for row in con.execute("PRAGMA table_info(operator_entities)").fetchall()
        }

    assert entity["status"] == "watch"
    assert entity["appearance_count"] >= 1
    assert entity["first_seen_at"]
    assert entity["last_seen_at"]
    assert event_count >= 1
    assert cursor_before is None
    forbidden = {"advice", "buy", "sell", "hold", "target", "verdict", "upside"}
    assert all(not any(term in column for term in forbidden) for column in columns)

    first = handle_command(
        "/briefing",
        db_path=watch_db,
        config_dir=CONFIG_DIR,
        operator_db_path=operator_db,
    ).text
    second = handle_command(
        "/briefing",
        db_path=watch_db,
        config_dir=CONFIG_DIR,
        operator_db_path=operator_db,
    ).text

    assert "Operator memory: following BHIC (watch, normal)." in first
    assert "Duplicate briefing suppressed by operator memory cursor." in second


def test_ignored_entity_loses_normal_briefing_prominence(tmp_path) -> None:
    watch_db = _seed_db(tmp_path)
    operator_db = tmp_path / "operator_state.db"

    handle_command(
        "/ignore CohBar noisy recurrence",
        db_path=watch_db,
        config_dir=CONFIG_DIR,
        operator_db_path=operator_db,
    )
    briefing = handle_command(
        "/briefing",
        db_path=watch_db,
        config_dir=CONFIG_DIR,
        operator_db_path=operator_db,
    ).text

    assert "ignored/archived item(s) kept out of normal prominence" in briefing
    assert "CohBar disclosed MOTS-c" not in briefing
