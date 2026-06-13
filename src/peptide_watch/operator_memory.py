"""Durable operator memory for the Peptide Watch HQ.

This database stores workflow state only: watched/ignored/promoted entities,
factual source appearances, command interactions, and the latest briefing cursor.
It deliberately has no advice, verdict, target, or recommendation fields.
"""

from __future__ import annotations

import hashlib
import json
import re
import sqlite3
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterable, Mapping

VALID_STATUSES = {"watch", "ignore", "promoted", "archived"}
VALID_PRIORITIES = {"low", "normal", "high"}

FORBIDDEN_SCHEMA_TERMS = {
    "advice",
    "buy",
    "sell",
    "hold",
    "target",
    "verdict",
    "upside",
}


def operator_key(value: str) -> str:
    """Normalize an operator entity key without losing the display name."""

    key = re.sub(r"[^a-z0-9]+", "-", value.strip().lower()).strip("-")
    if not key:
        raise ValueError("entity is required")
    return key[:120]


def now_utc() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def init_operator_memory(path: str | Path) -> Path:
    """Create or migrate the operator memory database."""

    target = Path(path)
    if target.parent != Path("."):
        target.parent.mkdir(parents=True, exist_ok=True)
    with sqlite3.connect(target) as con:
        con.row_factory = sqlite3.Row
        _create_tables(con)
        _migrate_operator_entities(con)
        _assert_no_forbidden_schema_terms(con)
        con.commit()
    return target


def _create_tables(con: sqlite3.Connection) -> None:
    con.execute(
        """
        CREATE TABLE IF NOT EXISTS operator_entities (
          entity_key TEXT PRIMARY KEY,
          display_name TEXT NOT NULL,
          entity_type TEXT,
          status TEXT NOT NULL CHECK(status IN ('watch', 'ignore', 'promoted', 'archived')),
          priority TEXT NOT NULL DEFAULT 'normal' CHECK(priority IN ('low', 'normal', 'high')),
          first_seen_at TEXT NOT NULL,
          last_seen_at TEXT NOT NULL,
          appearance_count INTEGER NOT NULL DEFAULT 0,
          source_url_count INTEGER NOT NULL DEFAULT 0,
          user_notes TEXT,
          created_by TEXT NOT NULL DEFAULT 'telegram',
          created_at TEXT NOT NULL,
          updated_at TEXT NOT NULL
        )
        """
    )
    con.execute(
        """
        CREATE TABLE IF NOT EXISTS operator_entity_events (
          id INTEGER PRIMARY KEY AUTOINCREMENT,
          entity_key TEXT NOT NULL,
          run_id TEXT,
          event_type TEXT,
          source_family TEXT,
          source_url TEXT,
          observed_at TEXT NOT NULL,
          fact_summary TEXT NOT NULL,
          FOREIGN KEY(entity_key) REFERENCES operator_entities(entity_key)
        )
        """
    )
    con.execute(
        """
        CREATE TABLE IF NOT EXISTS operator_interactions (
          id INTEGER PRIMARY KEY AUTOINCREMENT,
          message_id TEXT,
          entity_key TEXT,
          command TEXT NOT NULL,
          user_text TEXT,
          response_summary TEXT,
          created_at TEXT NOT NULL
        )
        """
    )
    con.execute(
        """
        CREATE TABLE IF NOT EXISTS operator_attention (
          entity_key TEXT PRIMARY KEY,
          display_name TEXT NOT NULL,
          attention_count INTEGER NOT NULL DEFAULT 0,
          first_attention_at TEXT NOT NULL,
          last_attention_at TEXT NOT NULL,
          last_command TEXT,
          last_message_id TEXT,
          latest_fact_summary TEXT
        )
        """
    )
    con.execute(
        """
        CREATE TABLE IF NOT EXISTS briefing_cursor (
          id INTEGER PRIMARY KEY CHECK (id = 1),
          last_run_id TEXT,
          last_posted_hash TEXT,
          last_posted_at TEXT
        )
        """
    )
    con.execute("CREATE INDEX IF NOT EXISTS idx_operator_entities_status ON operator_entities(status)")
    con.execute("CREATE INDEX IF NOT EXISTS idx_operator_entities_priority ON operator_entities(priority)")
    con.execute("CREATE INDEX IF NOT EXISTS idx_operator_entity_events_key ON operator_entity_events(entity_key)")
    con.execute("CREATE INDEX IF NOT EXISTS idx_operator_interactions_entity ON operator_interactions(entity_key)")
    con.execute("CREATE INDEX IF NOT EXISTS idx_operator_attention_last ON operator_attention(last_attention_at)")


def _migrate_operator_entities(con: sqlite3.Connection) -> None:
    columns = _column_names(con, "operator_entities")
    now = now_utc()
    additions = {
        "entity_type": "TEXT",
        "first_seen_at": "TEXT",
        "last_seen_at": "TEXT",
        "appearance_count": "INTEGER NOT NULL DEFAULT 0",
        "source_url_count": "INTEGER NOT NULL DEFAULT 0",
    }
    for column, ddl in additions.items():
        if column not in columns:
            con.execute(f"ALTER TABLE operator_entities ADD COLUMN {column} {ddl}")
    con.execute(
        """
        UPDATE operator_entities
        SET first_seen_at = COALESCE(first_seen_at, created_at, updated_at, ?),
            last_seen_at = COALESCE(last_seen_at, updated_at, created_at, ?),
            appearance_count = COALESCE(appearance_count, 0),
            source_url_count = COALESCE(source_url_count, 0)
        """,
        (now, now),
    )


def _column_names(con: sqlite3.Connection, table: str) -> set[str]:
    return {str(row[1]) for row in con.execute(f"PRAGMA table_info({table})").fetchall()}


def _assert_no_forbidden_schema_terms(con: sqlite3.Connection) -> None:
    rows = con.execute(
        "SELECT name FROM sqlite_master WHERE type = 'table' AND name NOT LIKE 'sqlite_%'"
    ).fetchall()
    for row in rows:
        table = str(row["name"] if isinstance(row, sqlite3.Row) else row[0])
        columns = _column_names(con, table)
        for column in columns:
            normalized = column.lower()
            if any(term in normalized for term in FORBIDDEN_SCHEMA_TERMS):
                raise RuntimeError(f"operator memory schema contains forbidden field: {table}.{column}")


def upsert_entity(
    path: str | Path,
    display_name: str,
    *,
    status: str,
    priority: str | None = None,
    note: str | None = None,
    entity_type: str | None = None,
    appearance_count: int | None = None,
    source_url_count: int | None = None,
    first_seen_at: str | None = None,
    last_seen_at: str | None = None,
    created_by: str = "telegram",
) -> dict[str, Any]:
    if status not in VALID_STATUSES:
        raise ValueError(f"invalid status: {status}")
    if priority is not None and priority not in VALID_PRIORITIES:
        raise ValueError(f"invalid priority: {priority}")
    init_operator_memory(path)
    key = operator_key(display_name)
    now = now_utc()
    with sqlite3.connect(path) as con:
        con.row_factory = sqlite3.Row
        existing = con.execute(
            "SELECT * FROM operator_entities WHERE entity_key = ?", (key,)
        ).fetchone()
        merged_note = note if note is not None else (existing["user_notes"] if existing else None)
        con.execute(
            """
            INSERT INTO operator_entities (
              entity_key, display_name, entity_type, status, priority,
              first_seen_at, last_seen_at, appearance_count, source_url_count,
              user_notes, created_by, created_at, updated_at
            )
            VALUES (
              ?, ?, ?, ?, COALESCE(?, 'normal'),
              COALESCE(?, ?), COALESCE(?, ?), COALESCE(?, 0), COALESCE(?, 0),
              ?, ?, ?, ?
            )
            ON CONFLICT(entity_key) DO UPDATE SET
              display_name = excluded.display_name,
              entity_type = COALESCE(excluded.entity_type, operator_entities.entity_type),
              status = excluded.status,
              priority = COALESCE(excluded.priority, operator_entities.priority),
              first_seen_at = COALESCE(operator_entities.first_seen_at, excluded.first_seen_at),
              last_seen_at = COALESCE(excluded.last_seen_at, operator_entities.last_seen_at),
              appearance_count = MAX(operator_entities.appearance_count, excluded.appearance_count),
              source_url_count = MAX(operator_entities.source_url_count, excluded.source_url_count),
              user_notes = COALESCE(excluded.user_notes, operator_entities.user_notes),
              updated_at = excluded.updated_at
            """,
            (
                key,
                display_name,
                entity_type,
                status,
                priority,
                first_seen_at,
                now,
                last_seen_at,
                now,
                appearance_count,
                source_url_count,
                merged_note,
                created_by,
                now,
                now,
            ),
        )
        con.commit()
        row = con.execute("SELECT * FROM operator_entities WHERE entity_key = ?", (key,)).fetchone()
        return dict(row)


def get_entity(path: str | Path, entity: str) -> dict[str, Any] | None:
    init_operator_memory(path)
    key = operator_key(entity)
    with sqlite3.connect(path) as con:
        con.row_factory = sqlite3.Row
        row = con.execute("SELECT * FROM operator_entities WHERE entity_key = ?", (key,)).fetchone()
    return dict(row) if row else None


def list_entities(
    path: str | Path,
    *,
    statuses: Iterable[str] | None = None,
) -> list[dict[str, Any]]:
    init_operator_memory(path)
    with sqlite3.connect(path) as con:
        con.row_factory = sqlite3.Row
        if statuses is None:
            rows = con.execute(
                """
                SELECT * FROM operator_entities
                ORDER BY
                  CASE priority WHEN 'high' THEN 0 WHEN 'normal' THEN 1 ELSE 2 END,
                  updated_at DESC,
                  display_name
                """
            ).fetchall()
        else:
            values = tuple(statuses)
            if not values:
                return []
            placeholders = ",".join("?" for _ in values)
            rows = con.execute(
                f"""
                SELECT * FROM operator_entities
                WHERE status IN ({placeholders})
                ORDER BY
                  CASE priority WHEN 'high' THEN 0 WHEN 'normal' THEN 1 ELSE 2 END,
                  updated_at DESC,
                  display_name
                """,
                values,
            ).fetchall()
    return [dict(row) for row in rows]


def record_entity_events(
    path: str | Path,
    entity: str,
    rows: Iterable[Mapping[str, Any]],
) -> int:
    init_operator_memory(path)
    key = operator_key(entity)
    inserted = 0
    now = now_utc()
    with sqlite3.connect(path) as con:
        for row in rows:
            fact = str(row.get("what_changed") or row.get("title") or "").strip()
            if not fact:
                continue
            con.execute(
                """
                INSERT INTO operator_entity_events (
                  entity_key, run_id, event_type, source_family, source_url, observed_at, fact_summary
                )
                VALUES (?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    key,
                    row.get("run_id"),
                    row.get("event_type"),
                    row.get("source_id"),
                    row.get("source_url") or row.get("url"),
                    row.get("created_at") or now,
                    fact[:1000],
                ),
            )
            inserted += 1
        con.commit()
    return inserted


def record_interaction(
    path: str | Path,
    *,
    command: str,
    message_id: str | None,
    entity_key: str | None,
    user_text: str | None,
    response_summary: str,
) -> None:
    init_operator_memory(path)
    with sqlite3.connect(path) as con:
        con.execute(
            """
            INSERT INTO operator_interactions (
              message_id, entity_key, command, user_text, response_summary, created_at
            )
            VALUES (?, ?, ?, ?, ?, ?)
            """,
            (message_id, entity_key, command, user_text, response_summary[:240], now_utc()),
        )
        con.commit()


def record_attention(
    path: str | Path,
    display_name: str,
    *,
    command: str,
    message_id: str | None = None,
    fact_summary: str | None = None,
) -> dict[str, Any]:
    """Record that the operator asked about an entity.

    This is workflow attention only. It stores counts, timestamps, and the
    latest factual source summary; it never stores a verdict or recommendation.
    """

    init_operator_memory(path)
    key = operator_key(display_name)
    now = now_utc()
    with sqlite3.connect(path) as con:
        con.row_factory = sqlite3.Row
        con.execute(
            """
            INSERT INTO operator_attention (
              entity_key, display_name, attention_count, first_attention_at,
              last_attention_at, last_command, last_message_id, latest_fact_summary
            )
            VALUES (?, ?, 1, ?, ?, ?, ?, ?)
            ON CONFLICT(entity_key) DO UPDATE SET
              display_name = excluded.display_name,
              attention_count = operator_attention.attention_count + 1,
              last_attention_at = excluded.last_attention_at,
              last_command = excluded.last_command,
              last_message_id = excluded.last_message_id,
              latest_fact_summary = COALESCE(excluded.latest_fact_summary, operator_attention.latest_fact_summary)
            """,
            (key, display_name, now, now, command, message_id, fact_summary),
        )
        con.commit()
        row = con.execute("SELECT * FROM operator_attention WHERE entity_key = ?", (key,)).fetchone()
    return dict(row)


def list_attention(path: str | Path, *, limit: int = 8) -> list[dict[str, Any]]:
    init_operator_memory(path)
    with sqlite3.connect(path) as con:
        con.row_factory = sqlite3.Row
        rows = con.execute(
            """
            SELECT * FROM operator_attention
            ORDER BY last_attention_at DESC, display_name
            LIMIT ?
            """,
            (limit,),
        ).fetchall()
    return [dict(row) for row in rows]


def operator_snapshot(path: str | Path, *, limit: int = 8) -> dict[str, Any]:
    """Return public-safe operator context without creating a missing DB."""

    target = Path(path)
    if not target.exists():
        return {
            "following": [],
            "quieted": [],
            "recently_asked": [],
            "prioritization_note": (
                "Operator memory can change ordering and labels, but not source facts."
            ),
        }
    uri = f"file:{target.resolve()}?mode=ro"
    with sqlite3.connect(uri, uri=True) as con:
        con.row_factory = sqlite3.Row
        following = con.execute(
            """
            SELECT entity_key, display_name, status, priority, appearance_count,
                   source_url_count, first_seen_at, last_seen_at, updated_at
            FROM operator_entities
            WHERE status IN ('watch', 'promoted')
            ORDER BY
              CASE priority WHEN 'high' THEN 0 WHEN 'normal' THEN 1 ELSE 2 END,
              updated_at DESC,
              display_name
            LIMIT ?
            """,
            (limit,),
        ).fetchall()
        quieted = con.execute(
            """
            SELECT entity_key, display_name, status, priority, appearance_count,
                   source_url_count, first_seen_at, last_seen_at, updated_at
            FROM operator_entities
            WHERE status IN ('ignore', 'archived')
            ORDER BY updated_at DESC, display_name
            LIMIT ?
            """,
            (limit,),
        ).fetchall()
        try:
            attention = con.execute(
                """
                SELECT entity_key, display_name, attention_count, first_attention_at,
                       last_attention_at, last_command, latest_fact_summary
                FROM operator_attention
                ORDER BY last_attention_at DESC, display_name
                LIMIT ?
                """,
                (limit,),
            ).fetchall()
        except sqlite3.OperationalError:
            attention = []
    return {
        "following": [dict(row) for row in following],
        "quieted": [dict(row) for row in quieted],
        "recently_asked": [dict(row) for row in attention],
        "prioritization_note": (
            "Operator memory can change ordering and labels, but not source facts."
        ),
    }


def get_briefing_cursor(path: str | Path) -> dict[str, Any] | None:
    init_operator_memory(path)
    with sqlite3.connect(path) as con:
        con.row_factory = sqlite3.Row
        row = con.execute("SELECT * FROM briefing_cursor WHERE id = 1").fetchone()
    return dict(row) if row else None


def set_briefing_cursor(path: str | Path, *, run_id: str | None, digest: str) -> None:
    init_operator_memory(path)
    with sqlite3.connect(path) as con:
        con.execute(
            """
            INSERT INTO briefing_cursor (id, last_run_id, last_posted_hash, last_posted_at)
            VALUES (1, ?, ?, ?)
            ON CONFLICT(id) DO UPDATE SET
              last_run_id = excluded.last_run_id,
              last_posted_hash = excluded.last_posted_hash,
              last_posted_at = excluded.last_posted_at
            """,
            (run_id, digest, now_utc()),
        )
        con.commit()


def briefing_digest(data: Mapping[str, Any]) -> str:
    latest_run = (data.get("source_health") or {}).get("latest_run") or {}
    payload = {
        "run_id": latest_run.get("run_id"),
        "top_event_ids": [event.get("id") for event in data.get("top_events", [])],
        "discoveries": [item.get("company_name") for item in data.get("discoveries", [])],
        "comment_periods": [item.get("docket_id") for item in data.get("active_comment_periods", [])],
        "shortages": [item.get("title") for item in data.get("active_shortages", [])],
    }
    encoded = json.dumps(payload, sort_keys=True, separators=(",", ":")).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def latest_run_id(data: Mapping[str, Any]) -> str | None:
    latest_run = (data.get("source_health") or {}).get("latest_run") or {}
    value = latest_run.get("run_id")
    return str(value) if value else None
