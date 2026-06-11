"""Run ledger: tracked runs with per-source task state in SQLite."""

from __future__ import annotations

import json
import sqlite3
import uuid
from datetime import datetime, timezone
from typing import Any

UNFINISHED_TASK_STATUSES = ("pending", "running", "error")


def _now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def new_run_id() -> str:
    """Time-prefixed run id so lexical order is chronological order."""

    stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S")
    return f"{stamp}-{uuid.uuid4().hex[:8]}"


def mark_interrupted_runs(connection: sqlite3.Connection) -> list[str]:
    """Any run still 'running' at startup did not finish; mark it interrupted."""

    rows = connection.execute("SELECT run_id FROM runs WHERE status = 'running'").fetchall()
    connection.execute(
        "UPDATE runs SET status = 'interrupted', finished_at = ? WHERE status = 'running'",
        (_now(),),
    )
    connection.commit()
    return [row[0] for row in rows]


def create_run(connection: sqlite3.Connection, source_ids: list[str]) -> str:
    run_id = new_run_id()
    connection.execute(
        "INSERT INTO runs (run_id, started_at, status) VALUES (?, ?, 'running')",
        (run_id, _now()),
    )
    connection.executemany(
        "INSERT INTO run_tasks (run_id, source_id, status) VALUES (?, ?, 'pending')",
        [(run_id, source_id) for source_id in source_ids],
    )
    connection.commit()
    return run_id


def latest_interrupted_run(connection: sqlite3.Connection) -> str | None:
    row = connection.execute(
        "SELECT run_id FROM runs WHERE status = 'interrupted' ORDER BY rowid DESC LIMIT 1"
    ).fetchone()
    return row[0] if row else None


def resume_run(connection: sqlite3.Connection, run_id: str) -> list[str]:
    """Reopen an interrupted run; return source ids of its unfinished tasks."""

    connection.execute(
        "UPDATE runs SET status = 'running', finished_at = NULL WHERE run_id = ?",
        (run_id,),
    )
    placeholders = ", ".join("?" for _ in UNFINISHED_TASK_STATUSES)
    rows = connection.execute(
        f"SELECT source_id FROM run_tasks WHERE run_id = ? AND status IN ({placeholders}) "
        "ORDER BY rowid",
        (run_id, *UNFINISHED_TASK_STATUSES),
    ).fetchall()
    connection.commit()
    return [row[0] for row in rows]


def start_task(connection: sqlite3.Connection, run_id: str, source_id: str) -> None:
    connection.execute(
        "UPDATE run_tasks SET status = 'running', attempt = attempt + 1, "
        "started_at = ?, error = NULL WHERE run_id = ? AND source_id = ?",
        (_now(), run_id, source_id),
    )
    connection.commit()


def finish_task(
    connection: sqlite3.Connection,
    run_id: str,
    source_id: str,
    status: str,
    *,
    error: str | None = None,
    counts: dict[str, int] | None = None,
) -> None:
    connection.execute(
        "UPDATE run_tasks SET status = ?, error = ?, counts_json = ?, finished_at = ? "
        "WHERE run_id = ? AND source_id = ?",
        (
            status,
            error,
            json.dumps(counts) if counts is not None else None,
            _now(),
            run_id,
            source_id,
        ),
    )
    connection.commit()


def finish_run(
    connection: sqlite3.Connection, run_id: str, status: str, summary: dict[str, Any]
) -> None:
    connection.execute(
        "UPDATE runs SET status = ?, finished_at = ?, summary_json = ? WHERE run_id = ?",
        (status, _now(), json.dumps(summary), run_id),
    )
    connection.commit()


def failure_streak(connection: sqlite3.Connection, source_id: str) -> tuple[int, int]:
    """Return (consecutive errors, skips since the last real attempt) for a source.

    Reads finished task history newest-first: leading 'skipped' rows count as
    cool-down runs already served; the 'error' rows behind them are the streak.
    A 'done' breaks the streak.
    """

    rows = connection.execute(
        "SELECT status FROM run_tasks "
        "WHERE source_id = ? AND status IN ('done', 'error', 'skipped') "
        "ORDER BY rowid DESC LIMIT 64",
        (source_id,),
    ).fetchall()
    statuses = [row[0] for row in rows]

    skips = 0
    while skips < len(statuses) and statuses[skips] == "skipped":
        skips += 1
    errors = 0
    for status in statuses[skips:]:
        if status != "error":
            break
        errors += 1
    return errors, skips


def run_summary(connection: sqlite3.Connection, run_id: str) -> dict[str, Any]:
    """Roll up task states and counts for one run."""

    rows = connection.execute(
        "SELECT source_id, status, attempt, error, counts_json, started_at, finished_at "
        "FROM run_tasks WHERE run_id = ? ORDER BY rowid",
        (run_id,),
    ).fetchall()

    totals: dict[str, int] = {}
    by_status: dict[str, int] = {}
    errors: dict[str, str] = {}
    skipped: dict[str, str] = {}
    for source_id, status, _attempt, error, counts_json, _started, _finished in rows:
        by_status[status] = by_status.get(status, 0) + 1
        if counts_json:
            for key, value in json.loads(counts_json).items():
                totals[key] = totals.get(key, 0) + int(value)
        if status == "error" and error:
            errors[source_id] = error.strip().splitlines()[-1]
        if status == "skipped" and error:
            skipped[source_id] = error

    return {
        "run_id": run_id,
        "sources": len(rows),
        "tasks_by_status": by_status,
        "totals": totals,
        "errors": errors,
        "skipped": skipped,
    }


def list_runs(connection: sqlite3.Connection, limit: int = 20) -> list[dict[str, Any]]:
    rows = connection.execute(
        "SELECT run_id, started_at, finished_at, status, summary_json "
        "FROM runs ORDER BY rowid DESC LIMIT ?",
        (limit,),
    ).fetchall()
    return [
        {
            "run_id": run_id,
            "started_at": started_at,
            "finished_at": finished_at,
            "status": status,
            "summary": json.loads(summary_json) if summary_json else None,
        }
        for run_id, started_at, finished_at, status, summary_json in rows
    ]


def get_run(connection: sqlite3.Connection, run_id: str) -> dict[str, Any] | None:
    row = connection.execute(
        "SELECT run_id, started_at, finished_at, status, summary_json FROM runs WHERE run_id = ?",
        (run_id,),
    ).fetchone()
    if row is None:
        return None
    tasks = connection.execute(
        "SELECT source_id, status, attempt, error, counts_json, started_at, finished_at "
        "FROM run_tasks WHERE run_id = ? ORDER BY rowid",
        (run_id,),
    ).fetchall()
    return {
        "run_id": row[0],
        "started_at": row[1],
        "finished_at": row[2],
        "status": row[3],
        "summary": json.loads(row[4]) if row[4] else None,
        "tasks": [
            {
                "source_id": source_id,
                "status": status,
                "attempt": attempt,
                "error": error,
                "counts": json.loads(counts_json) if counts_json else None,
                "started_at": started_at,
                "finished_at": finished_at,
            }
            for source_id, status, attempt, error, counts_json, started_at, finished_at in tasks
        ],
    }
