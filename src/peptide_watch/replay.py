"""Replay events from stored snapshots and verify stored payload integrity.

Replay re-runs the current normalize/diff logic over stored history with zero
network. Replay runs use a ``replay-`` run id, so the outbox enqueues their
events 'suppressed' — re-deriving history never sends alerts. ``--deliver``
uses a ``redrive-`` id instead, which the outbox treats as a normal run.

Clinical trials replay from full history (the raw API payload has always been
snapshotted). Page/filing sources replay from ``raw_blobs``, which are
captured from PR7 onward.
"""

from __future__ import annotations

import hashlib
import json
import sqlite3
from pathlib import Path
from typing import Any

from peptide_watch.config import load_config
from peptide_watch.database import connect, init_db
from peptide_watch.runtime.ledger import new_run_id


def replay_clinicaltrials(
    db_path: str | Path,
    *,
    config_dir: str | Path = "config",
    since: str | None = None,
    rebuild: bool = False,
    deliver: bool = False,
) -> dict[str, Any]:
    """Re-derive trial records and events from snapshot history, oldest first."""

    from peptide_watch.sources.clinicaltrials import normalize_study, write_trial_record

    config = load_config(config_dir)
    run_id = ("redrive-" if deliver else "replay-") + new_run_id()

    init_db(db_path)
    connection = connect(db_path)
    connection.row_factory = sqlite3.Row
    replayed = 0
    inserted = 0
    changed = 0
    events_created = 0
    try:
        params: list[str] = []
        where = ""
        if since:
            where = "WHERE captured_at >= ?"
            params.append(since)
        rows = connection.execute(
            f"SELECT raw_json, captured_at FROM clinical_trial_snapshots {where} "
            "ORDER BY captured_at, id",
            params,
        ).fetchall()

        if rebuild:
            # Snapshots intentionally outlive their parent rows during a
            # rebuild; the replay below re-inserts every parent.
            connection.execute("PRAGMA foreign_keys = OFF")
            connection.execute("DELETE FROM clinical_trials")
            connection.commit()
            connection.execute("PRAGMA foreign_keys = ON")

        for row in rows:
            record = normalize_study(json.loads(row["raw_json"]), config=config)
            result = write_trial_record(connection, record, run_id=run_id)
            connection.commit()
            replayed += 1
            inserted += int(result.inserted)
            changed += int(result.changed)
            events_created += result.events_created
    except BaseException:
        connection.rollback()
        connection.close()
        raise
    else:
        connection.close()

    return {
        "run_id": run_id,
        "snapshots_replayed": replayed,
        "inserted": inserted,
        "changed": changed,
        "events_created": events_created,
    }


def verify_integrity(db_path: str | Path) -> dict[str, Any]:
    """Re-hash stored payloads against their recorded sha256 keys."""

    init_db(db_path)
    connection = connect(db_path)
    corrupted: list[str] = []
    blobs_checked = 0
    snapshots_checked = 0
    try:
        for raw_sha256, content in connection.execute(
            "SELECT raw_sha256, content FROM raw_blobs"
        ):
            blobs_checked += 1
            if hashlib.sha256(content).hexdigest() != raw_sha256:
                corrupted.append(f"raw_blobs:{raw_sha256}")

        for snapshot_id, raw_sha256, raw_json in connection.execute(
            "SELECT id, raw_sha256, raw_json FROM clinical_trial_snapshots "
            "WHERE raw_sha256 IS NOT NULL AND raw_sha256 != ''"
        ):
            snapshots_checked += 1
            if hashlib.sha256(raw_json.encode("utf-8")).hexdigest() != raw_sha256:
                corrupted.append(f"clinical_trial_snapshots:{snapshot_id}")
    finally:
        connection.close()

    return {
        "blobs_checked": blobs_checked,
        "snapshots_checked": snapshots_checked,
        "corrupted": corrupted,
    }
