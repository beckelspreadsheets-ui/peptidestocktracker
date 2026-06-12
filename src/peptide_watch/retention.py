"""Data retention: prune old rows from high-volume, non-immutable tables.

Snapshots (`*_snapshots`) and `raw_blobs` are deliberately immutable — they are
the replay/audit trail and are managed via dated backups, not pruning. This
prunes only what grows by count and is safe to forget once delivered: events,
their deliveries, and source_documents older than a cutoff.
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

from peptide_watch.database import connect, init_db


def prune(db_path: str | Path, *, older_than_days: int = 180) -> dict[str, int]:
    """Delete delivered events, their deliveries, and source_documents older
    than the cutoff. Returns per-table delete counts."""

    if older_than_days < 1:
        raise ValueError("older_than_days must be at least 1")
    cutoff = (datetime.now(timezone.utc) - timedelta(days=older_than_days)).isoformat(
        timespec="seconds"
    )

    init_db(db_path)
    connection = connect(db_path)
    deleted: dict[str, int] = {}
    try:
        # Events past the cutoff whose deliveries are all resolved (sent or
        # suppressed) — never drop anything still pending delivery.
        old_event_ids = [
            row[0]
            for row in connection.execute(
                """
                SELECT e.id FROM events e
                WHERE e.created_at < ?
                  AND NOT EXISTS (
                      SELECT 1 FROM deliveries d
                      WHERE d.event_id = e.id AND d.status IN ('pending', 'failed')
                  )
                """,
                (cutoff,),
            ).fetchall()
        ]
        if old_event_ids:
            placeholders = ", ".join("?" for _ in old_event_ids)
            deleted["deliveries"] = connection.execute(
                f"DELETE FROM deliveries WHERE event_id IN ({placeholders})", old_event_ids
            ).rowcount
            deleted["events"] = connection.execute(
                f"DELETE FROM events WHERE id IN ({placeholders})", old_event_ids
            ).rowcount
        else:
            deleted["deliveries"] = 0
            deleted["events"] = 0

        deleted["source_documents"] = connection.execute(
            "DELETE FROM source_documents WHERE retrieved_at < ?", (cutoff,)
        ).rowcount
        connection.commit()
    finally:
        connection.close()
    return deleted


def storage_report(db_path: str | Path) -> dict[str, Any]:
    """Row counts and blob bytes — for the `status` health check."""

    init_db(db_path)
    connection = connect(db_path)
    try:
        report: dict[str, Any] = {}
        for table in (
            "events",
            "deliveries",
            "source_documents",
            "raw_blobs",
            "clinical_trial_snapshots",
            "regulatory_document_snapshots",
            "company_document_snapshots",
        ):
            report[table] = connection.execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0]
        report["raw_blob_bytes"] = connection.execute(
            "SELECT COALESCE(SUM(LENGTH(content)), 0) FROM raw_blobs"
        ).fetchone()[0]
    finally:
        connection.close()
    return report
