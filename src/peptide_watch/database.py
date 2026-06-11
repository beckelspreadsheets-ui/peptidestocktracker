"""SQLite database initialization."""

from __future__ import annotations

import sqlite3
from datetime import datetime, timezone
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[2]
DEFAULT_SCHEMA_PATH = PROJECT_ROOT / "schema" / "schema.sql"

REQUIRED_TABLES = frozenset(
    {
        "alerts",
        "claims",
        "company_document_snapshots",
        "company_documents",
        "clinical_trial_snapshots",
        "clinical_trials",
        "companies",
        "events",
        "peptide_aliases",
        "peptides",
        "regulatory_document_snapshots",
        "regulatory_documents",
        "securities",
        "source_documents",
    }
)

CLINICAL_TRIAL_COLUMN_MIGRATIONS = {
    "source_url": "TEXT NOT NULL DEFAULT ''",
    "brief_title": "TEXT",
    "official_title": "TEXT",
    "overall_status": "TEXT",
    "phase": "TEXT",
    "phases_json": "TEXT NOT NULL DEFAULT '[]'",
    "enrollment_count": "INTEGER",
    "enrollment_type": "TEXT",
    "sponsor_name": "TEXT",
    "primary_completion_date": "TEXT",
    "completion_date": "TEXT",
    "last_update_post_date": "TEXT",
    "has_results": "INTEGER NOT NULL DEFAULT 0",
    "interventions_json": "TEXT NOT NULL DEFAULT '[]'",
    "conditions_json": "TEXT NOT NULL DEFAULT '[]'",
    "primary_outcomes_json": "TEXT NOT NULL DEFAULT '[]'",
    "locations_json": "TEXT NOT NULL DEFAULT '[]'",
    "peptide_ids_json": "TEXT NOT NULL DEFAULT '[]'",
    "matched_aliases_json": "TEXT NOT NULL DEFAULT '[]'",
    "query_terms_json": "TEXT NOT NULL DEFAULT '[]'",
    "record_hash": "TEXT NOT NULL DEFAULT ''",
    "raw_json": "TEXT NOT NULL DEFAULT '{}'",
    "first_seen_at": "TEXT",
    "last_seen_at": "TEXT",
    "updated_at": "TEXT",
}

CLAIM_COLUMN_MIGRATIONS = {
    "claim_hash": "TEXT",
    "company_name": "TEXT",
    "claim_category": "TEXT",
    "source_type": "TEXT NOT NULL DEFAULT 'external_report'",
    "target_status": "TEXT",
    "priority": "TEXT",
    "verification_path": "TEXT",
    "evidence_excerpt": "TEXT",
    "reviewer_notes": "TEXT",
    "first_seen_at": "TEXT",
    "last_checked_at": "TEXT",
    "needs_review": "INTEGER NOT NULL DEFAULT 1",
    "imported_from": "TEXT",
}

REGULATORY_DOCUMENT_COLUMN_MIGRATIONS = {
    "source_id": "TEXT NOT NULL DEFAULT ''",
    "source_type": "TEXT NOT NULL DEFAULT ''",
    "url": "TEXT NOT NULL DEFAULT ''",
    "title": "TEXT",
    "document_number": "TEXT",
    "publication_date": "TEXT",
    "docket_ids_json": "TEXT NOT NULL DEFAULT '[]'",
    "content_hash": "TEXT NOT NULL DEFAULT ''",
    "content_text": "TEXT NOT NULL DEFAULT ''",
    "peptide_ids_json": "TEXT NOT NULL DEFAULT '[]'",
    "matched_aliases_json": "TEXT NOT NULL DEFAULT '[]'",
    "route_notes_json": "TEXT NOT NULL DEFAULT '{}'",
    "status_terms_json": "TEXT NOT NULL DEFAULT '[]'",
    "metadata_json": "TEXT NOT NULL DEFAULT '{}'",
    "first_seen_at": "TEXT",
    "last_seen_at": "TEXT",
    "updated_at": "TEXT",
}

COMPANY_DOCUMENT_COLUMN_MIGRATIONS = {
    "source_id": "TEXT NOT NULL DEFAULT ''",
    "source_type": "TEXT NOT NULL DEFAULT ''",
    "url": "TEXT NOT NULL DEFAULT ''",
    "title": "TEXT",
    "company_key": "TEXT",
    "company_name": "TEXT",
    "ticker": "TEXT",
    "exchange": "TEXT",
    "filing_type": "TEXT",
    "accession_number": "TEXT",
    "filing_date": "TEXT",
    "source_tier": "TEXT",
    "content_hash": "TEXT NOT NULL DEFAULT ''",
    "content_text": "TEXT NOT NULL DEFAULT ''",
    "peptide_ids_json": "TEXT NOT NULL DEFAULT '[]'",
    "matched_aliases_json": "TEXT NOT NULL DEFAULT '[]'",
    "company_matches_json": "TEXT NOT NULL DEFAULT '[]'",
    "keyword_matches_json": "TEXT NOT NULL DEFAULT '[]'",
    "metadata_json": "TEXT NOT NULL DEFAULT '{}'",
    "first_seen_at": "TEXT",
    "last_seen_at": "TEXT",
    "updated_at": "TEXT",
}


def connect(db_path: str | Path) -> sqlite3.Connection:
    """Open a SQLite connection with the standard durability/concurrency pragmas."""

    connection = sqlite3.connect(db_path)
    connection.execute("PRAGMA journal_mode = WAL")
    connection.execute("PRAGMA foreign_keys = ON")
    connection.execute("PRAGMA busy_timeout = 5000")
    return connection


def backup_db(db_path: str | Path, backups_dir: str | Path = "backups") -> Path:
    """Write a consistent backup of the database via VACUUM INTO."""

    source = Path(db_path)
    if not source.exists():
        raise FileNotFoundError(f"database not found: {source}")

    backups = Path(backups_dir)
    backups.mkdir(parents=True, exist_ok=True)
    stamp = datetime.now(timezone.utc).strftime("%Y%m%d")
    target = backups / f"{source.stem}-{stamp}.db"
    if target.exists():
        target.unlink()

    connection = connect(source)
    try:
        connection.execute("VACUUM INTO ?", (str(target),))
    finally:
        connection.close()
    return target


def init_db(db_path: str | Path, schema_path: str | Path = DEFAULT_SCHEMA_PATH) -> Path:
    """Create or update a SQLite database by executing the repository schema."""

    target = Path(db_path)
    schema = Path(schema_path)
    if not schema.exists():
        raise FileNotFoundError(f"schema file not found: {schema}")

    if target.parent != Path("."):
        target.parent.mkdir(parents=True, exist_ok=True)

    sql = schema.read_text(encoding="utf-8")
    if not sql.strip():
        raise ValueError(f"schema file is empty: {schema}")

    with connect(target) as connection:
        connection.executescript(sql)
        _migrate_claims_table(connection)
        _migrate_clinical_trials_table(connection)
        _migrate_regulatory_documents_table(connection)
        _migrate_company_documents_table(connection)
        connection.commit()

    return target


def table_names(db_path: str | Path) -> set[str]:
    """Return non-internal SQLite table names for validation and diagnostics."""

    with sqlite3.connect(db_path) as connection:
        rows = connection.execute(
            "SELECT name FROM sqlite_master WHERE type = 'table' AND name NOT LIKE 'sqlite_%'"
        ).fetchall()
    return {row[0] for row in rows}


def _migrate_claims_table(connection: sqlite3.Connection) -> None:
    """Add Milestone 2 claim-registry columns to existing SQLite databases."""

    columns = _column_names(connection, "claims")
    for column_name, column_definition in CLAIM_COLUMN_MIGRATIONS.items():
        if column_name not in columns:
            connection.execute(f"ALTER TABLE claims ADD COLUMN {column_name} {column_definition}")

    connection.execute(
        """
        UPDATE claims
        SET first_seen_at = COALESCE(first_seen_at, created_at, CURRENT_TIMESTAMP)
        WHERE first_seen_at IS NULL
        """
    )
    connection.execute(
        """
        UPDATE claims
        SET source_type = COALESCE(source_type, 'external_report')
        WHERE source_type IS NULL
        """
    )
    connection.execute(
        """
        UPDATE claims
        SET needs_review = COALESCE(needs_review, 1)
        WHERE needs_review IS NULL
        """
    )
    connection.execute("CREATE UNIQUE INDEX IF NOT EXISTS idx_claims_claim_hash ON claims(claim_hash)")
    connection.execute("CREATE INDEX IF NOT EXISTS idx_claims_status ON claims(status)")
    connection.execute("CREATE INDEX IF NOT EXISTS idx_claims_needs_review ON claims(needs_review)")


def _migrate_clinical_trials_table(connection: sqlite3.Connection) -> None:
    """Ensure Milestone 3 clinical trial tables and indexes exist."""

    connection.execute(
        """
        CREATE TABLE IF NOT EXISTS clinical_trials (
          nct_id TEXT PRIMARY KEY,
          source_url TEXT NOT NULL,
          brief_title TEXT,
          official_title TEXT,
          overall_status TEXT,
          phase TEXT,
          phases_json TEXT NOT NULL DEFAULT '[]',
          enrollment_count INTEGER,
          enrollment_type TEXT,
          sponsor_name TEXT,
          primary_completion_date TEXT,
          completion_date TEXT,
          last_update_post_date TEXT,
          has_results INTEGER NOT NULL DEFAULT 0,
          interventions_json TEXT NOT NULL DEFAULT '[]',
          conditions_json TEXT NOT NULL DEFAULT '[]',
          primary_outcomes_json TEXT NOT NULL DEFAULT '[]',
          locations_json TEXT NOT NULL DEFAULT '[]',
          peptide_ids_json TEXT NOT NULL DEFAULT '[]',
          matched_aliases_json TEXT NOT NULL DEFAULT '[]',
          query_terms_json TEXT NOT NULL DEFAULT '[]',
          record_hash TEXT NOT NULL,
          raw_json TEXT NOT NULL,
          first_seen_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
          last_seen_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
          updated_at TEXT
        )
        """
    )
    columns = _column_names(connection, "clinical_trials")
    for column_name, column_definition in CLINICAL_TRIAL_COLUMN_MIGRATIONS.items():
        if column_name not in columns:
            connection.execute(
                f"ALTER TABLE clinical_trials ADD COLUMN {column_name} {column_definition}"
            )

    connection.execute(
        """
        CREATE TABLE IF NOT EXISTS clinical_trial_snapshots (
          id INTEGER PRIMARY KEY AUTOINCREMENT,
          nct_id TEXT NOT NULL REFERENCES clinical_trials(nct_id),
          record_hash TEXT NOT NULL,
          captured_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
          source_url TEXT NOT NULL,
          raw_json TEXT NOT NULL,
          UNIQUE(nct_id, record_hash)
        )
        """
    )
    connection.execute(
        """
        UPDATE clinical_trials
        SET first_seen_at = COALESCE(first_seen_at, CURRENT_TIMESTAMP),
            last_seen_at = COALESCE(last_seen_at, CURRENT_TIMESTAMP)
        WHERE first_seen_at IS NULL OR last_seen_at IS NULL
        """
    )
    connection.execute(
        "CREATE INDEX IF NOT EXISTS idx_clinical_trials_status ON clinical_trials(overall_status)"
    )
    connection.execute(
        "CREATE INDEX IF NOT EXISTS idx_clinical_trials_last_seen ON clinical_trials(last_seen_at)"
    )
    connection.execute(
        "CREATE INDEX IF NOT EXISTS idx_clinical_trial_snapshots_nct "
        "ON clinical_trial_snapshots(nct_id)"
    )


def _migrate_regulatory_documents_table(connection: sqlite3.Connection) -> None:
    """Ensure Milestone 4 regulatory document tables and indexes exist."""

    connection.execute(
        """
        CREATE TABLE IF NOT EXISTS regulatory_documents (
          document_key TEXT PRIMARY KEY,
          source_id TEXT NOT NULL,
          source_type TEXT NOT NULL,
          url TEXT NOT NULL,
          title TEXT,
          document_number TEXT,
          publication_date TEXT,
          docket_ids_json TEXT NOT NULL DEFAULT '[]',
          content_hash TEXT NOT NULL,
          content_text TEXT NOT NULL,
          peptide_ids_json TEXT NOT NULL DEFAULT '[]',
          matched_aliases_json TEXT NOT NULL DEFAULT '[]',
          route_notes_json TEXT NOT NULL DEFAULT '{}',
          status_terms_json TEXT NOT NULL DEFAULT '[]',
          metadata_json TEXT NOT NULL DEFAULT '{}',
          first_seen_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
          last_seen_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
          updated_at TEXT
        )
        """
    )
    columns = _column_names(connection, "regulatory_documents")
    for column_name, column_definition in REGULATORY_DOCUMENT_COLUMN_MIGRATIONS.items():
        if column_name not in columns:
            connection.execute(
                f"ALTER TABLE regulatory_documents ADD COLUMN {column_name} {column_definition}"
            )

    connection.execute(
        """
        CREATE TABLE IF NOT EXISTS regulatory_document_snapshots (
          id INTEGER PRIMARY KEY AUTOINCREMENT,
          document_key TEXT NOT NULL REFERENCES regulatory_documents(document_key),
          content_hash TEXT NOT NULL,
          captured_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
          url TEXT NOT NULL,
          content_text TEXT NOT NULL,
          metadata_json TEXT NOT NULL DEFAULT '{}',
          UNIQUE(document_key, content_hash)
        )
        """
    )
    connection.execute(
        """
        UPDATE regulatory_documents
        SET first_seen_at = COALESCE(first_seen_at, CURRENT_TIMESTAMP),
            last_seen_at = COALESCE(last_seen_at, CURRENT_TIMESTAMP)
        WHERE first_seen_at IS NULL OR last_seen_at IS NULL
        """
    )
    connection.execute(
        "CREATE INDEX IF NOT EXISTS idx_regulatory_documents_source "
        "ON regulatory_documents(source_id)"
    )
    connection.execute(
        "CREATE INDEX IF NOT EXISTS idx_regulatory_documents_last_seen "
        "ON regulatory_documents(last_seen_at)"
    )
    connection.execute(
        "CREATE INDEX IF NOT EXISTS idx_regulatory_snapshots_document "
        "ON regulatory_document_snapshots(document_key)"
    )


def _migrate_company_documents_table(connection: sqlite3.Connection) -> None:
    """Ensure Milestone 5 company/news/filing document tables and indexes exist."""

    connection.execute(
        """
        CREATE TABLE IF NOT EXISTS company_documents (
          document_key TEXT PRIMARY KEY,
          source_id TEXT NOT NULL,
          source_type TEXT NOT NULL,
          url TEXT NOT NULL,
          title TEXT,
          company_key TEXT,
          company_name TEXT,
          ticker TEXT,
          exchange TEXT,
          filing_type TEXT,
          accession_number TEXT,
          filing_date TEXT,
          source_tier TEXT,
          content_hash TEXT NOT NULL,
          content_text TEXT NOT NULL,
          peptide_ids_json TEXT NOT NULL DEFAULT '[]',
          matched_aliases_json TEXT NOT NULL DEFAULT '[]',
          company_matches_json TEXT NOT NULL DEFAULT '[]',
          keyword_matches_json TEXT NOT NULL DEFAULT '[]',
          metadata_json TEXT NOT NULL DEFAULT '{}',
          first_seen_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
          last_seen_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
          updated_at TEXT
        )
        """
    )
    columns = _column_names(connection, "company_documents")
    for column_name, column_definition in COMPANY_DOCUMENT_COLUMN_MIGRATIONS.items():
        if column_name not in columns:
            connection.execute(
                f"ALTER TABLE company_documents ADD COLUMN {column_name} {column_definition}"
            )

    connection.execute(
        """
        CREATE TABLE IF NOT EXISTS company_document_snapshots (
          id INTEGER PRIMARY KEY AUTOINCREMENT,
          document_key TEXT NOT NULL REFERENCES company_documents(document_key),
          content_hash TEXT NOT NULL,
          captured_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
          url TEXT NOT NULL,
          content_text TEXT NOT NULL,
          metadata_json TEXT NOT NULL DEFAULT '{}',
          UNIQUE(document_key, content_hash)
        )
        """
    )
    connection.execute(
        """
        UPDATE company_documents
        SET first_seen_at = COALESCE(first_seen_at, CURRENT_TIMESTAMP),
            last_seen_at = COALESCE(last_seen_at, CURRENT_TIMESTAMP)
        WHERE first_seen_at IS NULL OR last_seen_at IS NULL
        """
    )
    connection.execute(
        "CREATE INDEX IF NOT EXISTS idx_company_documents_source "
        "ON company_documents(source_id)"
    )
    connection.execute(
        "CREATE INDEX IF NOT EXISTS idx_company_documents_company "
        "ON company_documents(company_key)"
    )
    connection.execute(
        "CREATE INDEX IF NOT EXISTS idx_company_documents_last_seen "
        "ON company_documents(last_seen_at)"
    )
    connection.execute(
        "CREATE INDEX IF NOT EXISTS idx_company_snapshots_document "
        "ON company_document_snapshots(document_key)"
    )


def _column_names(connection: sqlite3.Connection, table_name: str) -> set[str]:
    rows = connection.execute(f"PRAGMA table_info({table_name})").fetchall()
    return {row[1] for row in rows}
