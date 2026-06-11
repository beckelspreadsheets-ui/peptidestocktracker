"""Transactional outbox over the events table.

Scanning only writes events; delivery is a separate sweep. Severity tiers:
critical/high events go out immediately (batched one message per source per
run); medium/low events wait for the digest. Events created by replay runs
are enqueued 'suppressed' so re-deriving history never sends alerts.
"""

from __future__ import annotations

import sqlite3
from datetime import datetime, timezone
from typing import Any

from peptide_watch.alerts.channels import Channel

IMMEDIATE_SEVERITIES = ("critical", "high")
DIGEST_SEVERITIES = ("medium", "low")
REPLAY_RUN_PREFIX = "replay-"

EVENT_COLUMNS = (
    "id, event_type, severity, title, what_changed, source_id, external_id, "
    "field, old_value, new_value, run_id, created_at"
)


def _now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def enqueue_undelivered(connection: sqlite3.Connection, channel_name: str) -> int:
    """Create a delivery row for every event that has none on this channel.

    Replay-run events are enqueued 'suppressed' instead of 'pending'.
    """

    cursor = connection.execute(
        f"""
        INSERT OR IGNORE INTO deliveries (event_id, channel, status)
        SELECT e.id, ?, CASE WHEN e.run_id LIKE '{REPLAY_RUN_PREFIX}%'
                             THEN 'suppressed' ELSE 'pending' END
        FROM events e
        WHERE NOT EXISTS (
            SELECT 1 FROM deliveries d WHERE d.event_id = e.id AND d.channel = ?
        )
        """,
        (channel_name, channel_name),
    )
    connection.commit()
    return cursor.rowcount


def _pending_rows(
    connection: sqlite3.Connection, channel_name: str, severities: tuple[str, ...]
) -> list[sqlite3.Row]:
    placeholders = ", ".join("?" for _ in severities)
    cursor = connection.cursor()
    cursor.row_factory = sqlite3.Row
    return cursor.execute(
        f"""
        SELECT {EVENT_COLUMNS}
        FROM events
        WHERE id IN (
            SELECT event_id FROM deliveries
            WHERE channel = ? AND status = 'pending'
        )
        AND COALESCE(severity, 'medium') IN ({placeholders})
        ORDER BY run_id, source_id, id
        """,
        (channel_name, *severities),
    ).fetchall()


def deliver_immediate(connection: sqlite3.Connection, channel: Channel) -> dict[str, Any]:
    """Send pending immediate-tier events, one batched message per (run, source).

    A failed send leaves the rows pending (attempts incremented) for the next
    sweep — a channel outage loses nothing.
    """

    enqueue_undelivered(connection, channel.name)
    rows = _pending_rows(connection, channel.name, IMMEDIATE_SEVERITIES)

    batches: dict[tuple[str, str], list[sqlite3.Row]] = {}
    for row in rows:
        batches.setdefault((row["run_id"] or "", row["source_id"] or ""), []).append(row)

    sent_messages = 0
    sent_events = 0
    failed_batches = 0
    for (run_id, source_id), batch in batches.items():
        event_ids = [row["id"] for row in batch]
        placeholders = ", ".join("?" for _ in event_ids)
        try:
            channel.send(format_batch(source_id, run_id, batch))
        except Exception as exc:
            failed_batches += 1
            connection.execute(
                f"""
                UPDATE deliveries SET attempts = attempts + 1, last_error = ?
                WHERE channel = ? AND event_id IN ({placeholders})
                """,
                (str(exc), channel.name, *event_ids),
            )
            connection.commit()
            continue
        connection.execute(
            f"""
            UPDATE deliveries
            SET status = 'sent', attempts = attempts + 1, sent_at = ?, last_error = NULL
            WHERE channel = ? AND event_id IN ({placeholders})
            """,
            (_now(), channel.name, *event_ids),
        )
        connection.commit()
        sent_messages += 1
        sent_events += len(batch)

    return {
        "messages_sent": sent_messages,
        "events_sent": sent_events,
        "batches_failed": failed_batches,
        "events_pending": len(rows) - sent_events,
    }


def format_batch(source_id: str, run_id: str, rows: list[sqlite3.Row]) -> str:
    lines = [
        f"[peptide-watch] {len(rows)} review event(s) — source {source_id or 'unknown'}, "
        f"run {run_id or 'untracked'}"
    ]
    for row in rows:
        lines.append(f"- [{row['severity']}] {row['title']}")
        if row["what_changed"]:
            lines.append(f"  {row['what_changed']}")
        if row["field"]:
            lines.append(f"  field: {row['field']} | {row['old_value']!r} -> {row['new_value']!r}")
    lines.append(
        "Review queue items from public sources; verify independently before acting on anything."
    )
    return "\n".join(lines)


def build_digest(connection: sqlite3.Connection, channel_name: str) -> tuple[str, list[int]]:
    """Render pending digest-tier events as markdown; returns (text, event ids)."""

    enqueue_undelivered(connection, channel_name)
    rows = _pending_rows(connection, channel_name, DIGEST_SEVERITIES)

    header = _latest_run_header(connection)
    if not rows:
        return (f"{header}\nNo digest-tier events pending.", [])

    lines = [header, "", f"## {len(rows)} digest event(s)", ""]
    by_source: dict[str, list[sqlite3.Row]] = {}
    for row in rows:
        by_source.setdefault(row["source_id"] or "unknown", []).append(row)
    for source_id in sorted(by_source):
        lines.append(f"### {source_id}")
        for row in by_source[source_id]:
            lines.append(f"- [{row['severity']}] {row['title']} ({row['created_at']})")
            if row["field"]:
                lines.append(
                    f"  - {row['field']}: {row['old_value']!r} -> {row['new_value']!r}"
                )
        lines.append("")
    lines.append("All items come from public sources; verify independently before acting.")
    return ("\n".join(lines), [row["id"] for row in rows])


def mark_digest_sent(
    connection: sqlite3.Connection, channel_name: str, event_ids: list[int]
) -> None:
    if not event_ids:
        return
    placeholders = ", ".join("?" for _ in event_ids)
    connection.execute(
        f"""
        UPDATE deliveries
        SET status = 'sent', attempts = attempts + 1, sent_at = ?, last_error = NULL
        WHERE channel = ? AND event_id IN ({placeholders})
        """,
        (_now(), channel_name, *event_ids),
    )
    connection.commit()


def _latest_run_header(connection: sqlite3.Connection) -> str:
    row = connection.execute(
        "SELECT run_id, status, started_at FROM runs ORDER BY rowid DESC LIMIT 1"
    ).fetchone()
    if row is None:
        return "# peptide-watch digest"
    return f"# peptide-watch digest — run {row[0]} ({row[1]}, started {row[2]})"
