"""Per-source fetch cursors (etag / last-modified / opaque cursor state)."""

from __future__ import annotations

import sqlite3
from datetime import datetime, timezone
from typing import NamedTuple


class SourceCursor(NamedTuple):
    source_id: str
    etag: str | None
    last_modified: str | None
    cursor_json: str | None


def _now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def get_cursor(connection: sqlite3.Connection, source_id: str) -> SourceCursor | None:
    row = connection.execute(
        "SELECT source_id, etag, last_modified, cursor_json FROM source_cursors WHERE source_id = ?",
        (source_id,),
    ).fetchone()
    if row is None:
        return None
    return SourceCursor(row[0], row[1], row[2], row[3])


def save_cursor(
    connection: sqlite3.Connection,
    source_id: str,
    *,
    etag: str | None = None,
    last_modified: str | None = None,
    cursor_json: str | None = None,
) -> None:
    connection.execute(
        """
        INSERT INTO source_cursors (source_id, etag, last_modified, cursor_json, updated_at)
        VALUES (?, ?, ?, ?, ?)
        ON CONFLICT(source_id) DO UPDATE SET
          etag = excluded.etag,
          last_modified = excluded.last_modified,
          cursor_json = excluded.cursor_json,
          updated_at = excluded.updated_at
        """,
        (source_id, etag, last_modified, cursor_json, _now()),
    )


def touch_cursor(connection: sqlite3.Connection, source_id: str) -> None:
    """Record that the cursor was revalidated (304) without new content."""

    connection.execute(
        "UPDATE source_cursors SET updated_at = ? WHERE source_id = ?",
        (_now(), source_id),
    )
