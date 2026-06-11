import sqlite3

import pytest

from peptide_watch.database import connect, init_db, table_names
from peptide_watch.migrations import (
    DEFAULT_MIGRATIONS_DIR,
    apply_migrations,
    migration_files,
    schema_version,
)

LEDGER_TABLES = {"runs", "run_tasks", "source_cursors"}


def latest_migration_number() -> int:
    return migration_files(DEFAULT_MIGRATIONS_DIR)[-1][0]


def test_init_db_applies_migrations(tmp_path) -> None:
    db_path = init_db(tmp_path / "watch.db")

    assert LEDGER_TABLES <= table_names(db_path)
    connection = connect(db_path)
    try:
        assert schema_version(connection) == latest_migration_number()
    finally:
        connection.close()


def test_init_db_is_idempotent_with_migrations(tmp_path) -> None:
    db_path = init_db(tmp_path / "watch.db")
    init_db(db_path)

    assert LEDGER_TABLES <= table_names(db_path)


def test_apply_migrations_upgrades_legacy_database(tmp_path) -> None:
    from peptide_watch.database import DEFAULT_SCHEMA_PATH

    db_path = tmp_path / "legacy.db"
    with sqlite3.connect(db_path) as connection:
        connection.executescript(DEFAULT_SCHEMA_PATH.read_text(encoding="utf-8"))

    connection = connect(db_path)
    try:
        assert schema_version(connection) == 0
        applied = apply_migrations(connection)
        assert applied == [number for number, _ in migration_files()]
        assert schema_version(connection) == latest_migration_number()
    finally:
        connection.close()

    assert LEDGER_TABLES <= table_names(db_path)


def test_apply_migrations_skips_already_applied(tmp_path) -> None:
    db_path = init_db(tmp_path / "watch.db")

    connection = connect(db_path)
    try:
        assert apply_migrations(connection) == []
    finally:
        connection.close()


def test_failed_migration_rolls_back_atomically(tmp_path) -> None:
    migrations_dir = tmp_path / "migrations"
    migrations_dir.mkdir()
    (migrations_dir / "0001_good.sql").write_text(
        "CREATE TABLE good_table (id INTEGER PRIMARY KEY);", encoding="utf-8"
    )
    (migrations_dir / "0002_bad.sql").write_text(
        "CREATE TABLE partial_table (id INTEGER PRIMARY KEY);\n"
        "INSERT INTO missing_table VALUES (1);",
        encoding="utf-8",
    )

    db_path = tmp_path / "watch.db"
    connection = connect(db_path)
    try:
        with pytest.raises(sqlite3.Error):
            apply_migrations(connection, migrations_dir)
        assert schema_version(connection) == 1
        tables = {
            row[0]
            for row in connection.execute(
                "SELECT name FROM sqlite_master WHERE type = 'table'"
            ).fetchall()
        }
    finally:
        connection.close()

    assert "good_table" in tables
    assert "partial_table" not in tables


def test_migration_files_reject_unnumbered_names(tmp_path) -> None:
    migrations_dir = tmp_path / "migrations"
    migrations_dir.mkdir()
    (migrations_dir / "add_stuff.sql").write_text("SELECT 1;", encoding="utf-8")

    with pytest.raises(ValueError, match="must start with a number"):
        migration_files(migrations_dir)
