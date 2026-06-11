import sqlite3

from peptide_watch.config import UNVERIFIED_CLAIM_STATUS
from peptide_watch.database import REQUIRED_TABLES, backup_db, connect, init_db, table_names


def test_init_db_creates_required_tables(tmp_path) -> None:
    db_path = tmp_path / "data" / "watch.db"

    initialized = init_db(db_path)

    assert initialized == db_path
    assert db_path.exists()
    assert REQUIRED_TABLES <= table_names(db_path)


def test_connect_applies_pragmas(tmp_path) -> None:
    db_path = init_db(tmp_path / "watch.db")

    connection = connect(db_path)
    try:
        journal_mode = connection.execute("PRAGMA journal_mode").fetchone()[0]
        foreign_keys = connection.execute("PRAGMA foreign_keys").fetchone()[0]
        busy_timeout = connection.execute("PRAGMA busy_timeout").fetchone()[0]
    finally:
        connection.close()

    assert journal_mode == "wal"
    assert foreign_keys == 1
    assert busy_timeout == 5000


def test_backup_db_writes_consistent_copy(tmp_path) -> None:
    db_path = init_db(tmp_path / "watch.db")
    with sqlite3.connect(db_path) as connection:
        connection.execute("INSERT INTO claims (claim_text) VALUES (?)", ("Backup test claim",))

    backup_path = backup_db(db_path, tmp_path / "backups")

    assert backup_path.exists()
    assert backup_path.parent == tmp_path / "backups"
    with sqlite3.connect(backup_path) as connection:
        count = connection.execute("SELECT COUNT(*) FROM claims").fetchone()[0]
    assert count == 1
    assert REQUIRED_TABLES <= table_names(backup_path)


def test_backup_db_overwrites_same_day_backup(tmp_path) -> None:
    db_path = init_db(tmp_path / "watch.db")

    first = backup_db(db_path, tmp_path / "backups")
    second = backup_db(db_path, tmp_path / "backups")

    assert first == second
    assert second.exists()


def test_claims_default_to_needs_verification(tmp_path) -> None:
    db_path = init_db(tmp_path / "watch.db")

    with sqlite3.connect(db_path) as connection:
        connection.execute("INSERT INTO claims (claim_text) VALUES (?)", ("External report claim",))
        status = connection.execute("SELECT status FROM claims").fetchone()[0]

    assert status == UNVERIFIED_CLAIM_STATUS


def test_init_db_adds_milestone2_claim_columns(tmp_path) -> None:
    db_path = init_db(tmp_path / "watch.db")

    with sqlite3.connect(db_path) as connection:
        columns = {
            row[1]
            for row in connection.execute("PRAGMA table_info(claims)").fetchall()
        }

    assert {
        "claim_hash",
        "source_type",
        "claim_category",
        "company_name",
        "target_status",
        "verification_path",
        "reviewer_notes",
        "first_seen_at",
        "last_checked_at",
        "needs_review",
        "imported_from",
    } <= columns


def test_init_db_creates_clinical_trial_tables(tmp_path) -> None:
    db_path = init_db(tmp_path / "watch.db")

    with sqlite3.connect(db_path) as connection:
        trial_columns = {
            row[1]
            for row in connection.execute("PRAGMA table_info(clinical_trials)").fetchall()
        }

    assert {
        "nct_id",
        "overall_status",
        "phase",
        "enrollment_count",
        "primary_completion_date",
        "peptide_ids_json",
        "record_hash",
        "raw_json",
    } <= trial_columns


def test_init_db_creates_regulatory_document_tables(tmp_path) -> None:
    db_path = init_db(tmp_path / "watch.db")

    with sqlite3.connect(db_path) as connection:
        columns = {
            row[1]
            for row in connection.execute("PRAGMA table_info(regulatory_documents)").fetchall()
        }

    assert {
        "document_key",
        "source_id",
        "source_type",
        "url",
        "content_hash",
        "peptide_ids_json",
        "route_notes_json",
        "status_terms_json",
    } <= columns


def test_init_db_creates_company_document_tables(tmp_path) -> None:
    db_path = init_db(tmp_path / "watch.db")

    with sqlite3.connect(db_path) as connection:
        columns = {
            row[1]
            for row in connection.execute("PRAGMA table_info(company_documents)").fetchall()
        }

    assert {
        "document_key",
        "source_id",
        "source_type",
        "company_key",
        "filing_type",
        "accession_number",
        "content_hash",
        "peptide_ids_json",
        "company_matches_json",
        "keyword_matches_json",
    } <= columns


def test_init_db_migrates_existing_claims_table_before_indexes(tmp_path) -> None:
    db_path = tmp_path / "legacy.db"
    with sqlite3.connect(db_path) as connection:
        connection.execute(
            """
            CREATE TABLE claims (
              id INTEGER PRIMARY KEY AUTOINCREMENT,
              claim_text TEXT NOT NULL,
              status TEXT NOT NULL DEFAULT 'needs_verification',
              confidence TEXT NOT NULL DEFAULT 'low',
              created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
            )
            """
        )

    init_db(db_path)

    with sqlite3.connect(db_path) as connection:
        columns = {
            row[1]
            for row in connection.execute("PRAGMA table_info(claims)").fetchall()
        }
        indexes = {
            row[1]
            for row in connection.execute("PRAGMA index_list(claims)").fetchall()
        }

    assert "claim_hash" in columns
    assert "idx_claims_claim_hash" in indexes
