"""Numbered SQL migrations applied transactionally, tracked via PRAGMA user_version."""

from __future__ import annotations

import sqlite3
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[2]
DEFAULT_MIGRATIONS_DIR = PROJECT_ROOT / "schema" / "migrations"


def migration_files(migrations_dir: str | Path = DEFAULT_MIGRATIONS_DIR) -> list[tuple[int, Path]]:
    """Return (number, path) pairs for migration files, validated and ordered."""

    directory = Path(migrations_dir)
    if not directory.exists():
        raise FileNotFoundError(f"migrations directory not found: {directory}")

    files: list[tuple[int, Path]] = []
    for path in sorted(directory.glob("*.sql")):
        prefix = path.name.split("_", 1)[0]
        if not prefix.isdigit():
            raise ValueError(f"migration file must start with a number: {path.name}")
        files.append((int(prefix), path))

    numbers = [number for number, _ in files]
    if len(set(numbers)) != len(numbers):
        raise ValueError(f"duplicate migration numbers in {directory}")
    if numbers != sorted(numbers):
        raise ValueError(f"migration numbers out of order in {directory}")
    return files


def schema_version(connection: sqlite3.Connection) -> int:
    return connection.execute("PRAGMA user_version").fetchone()[0]


def apply_migrations(
    connection: sqlite3.Connection,
    migrations_dir: str | Path = DEFAULT_MIGRATIONS_DIR,
) -> list[int]:
    """Apply unapplied migrations in order; each runs in one transaction."""

    applied: list[int] = []
    for number, path in migration_files(migrations_dir):
        if number <= schema_version(connection):
            continue
        sql = path.read_text(encoding="utf-8")
        script = f"BEGIN;\n{sql}\nPRAGMA user_version = {number};\nCOMMIT;"
        try:
            connection.executescript(script)
        except sqlite3.Error:
            if connection.in_transaction:
                connection.execute("ROLLBACK")
            raise
        applied.append(number)
    return applied
