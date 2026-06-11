import sqlite3

import pytest
from typer.testing import CliRunner

from peptide_watch.alerts import deliver_immediate
from peptide_watch.cli import app
from peptide_watch.config import load_config
from peptide_watch.database import init_db
from peptide_watch.replay import replay_clinicaltrials, verify_integrity
from peptide_watch.sources.clinicaltrials import normalize_study, store_trial_record
from peptide_watch.sources.regulatory import build_regulatory_document, store_regulatory_document

from test_change_detection import CONFIG_DIR
from test_clinicaltrials import _study_payload
from test_outbox import CollectingChannel


def _populated_db(tmp_path):
    """A database with one row in every snapshot table and raw_blobs."""

    from peptide_watch.sources.company_documents import build_company_document, store_company_document

    config = load_config(CONFIG_DIR)
    db_path = init_db(tmp_path / "watch.db")
    store_trial_record(db_path, normalize_study(_study_payload()), run_id="run-1")
    store_regulatory_document(
        db_path,
        build_regulatory_document(
            document_key="fda:seed",
            source_id="seed",
            source_type="fda_page",
            url="https://example.gov/page",
            content_text="503A Bulks List includes BPC-157",
            config=config,
            raw_content=b"<html>raw</html>",
        ),
        run_id="run-1",
    )
    store_company_document(
        db_path,
        build_company_document(
            document_key="company_page:seed",
            source_id="seed_page",
            source_type="company_page",
            url="https://example.com/news",
            content_text="BPC-157 commercial launch news",
            config=config,
            raw_content=b"<html>raw page</html>",
        ),
        run_id="run-1",
    )
    return db_path


@pytest.mark.parametrize(
    ("table", "update_sql"),
    [
        ("clinical_trial_snapshots", "UPDATE clinical_trial_snapshots SET source_url = 'x'"),
        (
            "regulatory_document_snapshots",
            "UPDATE regulatory_document_snapshots SET url = 'x'",
        ),
        ("company_document_snapshots", "UPDATE company_document_snapshots SET url = 'x'"),
        ("raw_blobs", "UPDATE raw_blobs SET created_at = 'x'"),
    ],
)
def test_snapshots_and_blobs_are_immutable(tmp_path, table, update_sql) -> None:
    db_path = _populated_db(tmp_path)
    with sqlite3.connect(db_path) as connection:
        assert connection.execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0] > 0
        with pytest.raises(sqlite3.DatabaseError, match="immutable"):
            connection.execute(update_sql)
        with pytest.raises(sqlite3.DatabaseError, match="immutable"):
            connection.execute(f"DELETE FROM {table}")


def test_raw_blob_captured_and_verify_passes(tmp_path) -> None:
    config = load_config(CONFIG_DIR)
    db_path = init_db(tmp_path / "watch.db")
    document = build_regulatory_document(
        document_key="fda:blob_test",
        source_id="blob_test",
        source_type="fda_page",
        url="https://example.gov/page",
        content_text="503A Bulks List includes BPC-157",
        config=config,
        raw_content=b"<html>raw payload</html>",
    )
    store_regulatory_document(db_path, document, run_id="run-1")

    with sqlite3.connect(db_path) as connection:
        row = connection.execute("SELECT raw_sha256 FROM raw_blobs").fetchone()
    assert row is not None and row[0] == document.raw_sha256

    result = verify_integrity(db_path)
    assert result["blobs_checked"] == 1
    assert result["corrupted"] == []


def test_verify_detects_corrupted_blob(tmp_path) -> None:
    config = load_config(CONFIG_DIR)
    db_path = init_db(tmp_path / "watch.db")
    document = build_regulatory_document(
        document_key="fda:blob_test",
        source_id="blob_test",
        source_type="fda_page",
        url="https://example.gov/page",
        content_text="some text",
        config=config,
        raw_content=b"original bytes",
    )
    store_regulatory_document(db_path, document, run_id="run-1")

    with sqlite3.connect(db_path) as connection:
        connection.execute("DROP TRIGGER raw_blobs_no_update")  # simulate disk corruption
        connection.execute("UPDATE raw_blobs SET content = ?", (b"tampered",))

    result = verify_integrity(db_path)
    assert len(result["corrupted"]) == 1
    assert result["corrupted"][0].startswith("raw_blobs:")

    cli_result = CliRunner().invoke(app, ["verify", "--db", str(db_path)])
    assert cli_result.exit_code == 1
    assert "1 corrupted" in cli_result.output


def test_replay_rebuilds_records_and_suppresses_alerts(tmp_path) -> None:
    config = load_config(CONFIG_DIR)
    db_path = init_db(tmp_path / "watch.db")
    store_trial_record(
        db_path,
        normalize_study(_study_payload(status="NOT_YET_RECRUITING"), config=config),
        run_id="run-1",
    )
    store_trial_record(
        db_path,
        normalize_study(_study_payload(status="RECRUITING"), config=config),
        run_id="run-2",
    )
    with sqlite3.connect(db_path) as connection:
        before = connection.execute(
            "SELECT nct_id, record_hash, overall_status FROM clinical_trials"
        ).fetchall()
        events_before = connection.execute("SELECT COUNT(*) FROM events").fetchone()[0]

    result = replay_clinicaltrials(db_path, config_dir=CONFIG_DIR, rebuild=True)

    assert result["snapshots_replayed"] == 2
    assert result["run_id"].startswith("replay-")
    with sqlite3.connect(db_path) as connection:
        after = connection.execute(
            "SELECT nct_id, record_hash, overall_status FROM clinical_trials"
        ).fetchall()
        replay_events = connection.execute(
            "SELECT COUNT(*) FROM events WHERE run_id = ?", (result["run_id"],)
        ).fetchone()[0]
        total_events = connection.execute("SELECT COUNT(*) FROM events").fetchone()[0]
    assert after == before  # rebuild reproduces the records table
    assert replay_events > 0  # history re-derived under the replay run
    assert total_events > events_before

    # replay events are suppressed: a delivery sweep sends nothing new for them
    connection = sqlite3.connect(db_path)
    try:
        channel = CollectingChannel()
        deliver_immediate(connection, channel)
        suppressed = connection.execute(
            "SELECT COUNT(*) FROM deliveries d JOIN events e ON e.id = d.event_id "
            "WHERE e.run_id = ? AND d.status = 'suppressed'",
            (result["run_id"],),
        ).fetchone()[0]
    finally:
        connection.close()
    assert suppressed == replay_events
    assert all(result["run_id"] not in message for message in channel.messages)


def test_replay_cli_rejects_unsupported_source(tmp_path) -> None:
    db_path = init_db(tmp_path / "watch.db")
    result = CliRunner().invoke(app, ["replay", "--db", str(db_path), "--source", "fda"])
    assert result.exit_code == 1
