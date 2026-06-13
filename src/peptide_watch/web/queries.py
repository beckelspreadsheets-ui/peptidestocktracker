"""Read queries for the API. The only place the web layer holds SQL.

Every event row is returned with its source URL + evidence and the compliance
fields, per the product's disclosure posture.
"""

from __future__ import annotations

from pathlib import Path
import sqlite3
from typing import Any

EVENT_SELECT = """
    SELECT e.id, e.event_type, e.peptide_id, e.title, e.what_changed, e.why_it_matters,
           e.confidence, e.severity, e.directness, e.stock_market_relevance,
           e.needs_review, e.source_id, e.external_id, e.field, e.old_value, e.new_value,
           e.run_id, e.created_at,
           sd.url AS source_url, sd.title AS source_title, sd.evidence_tier
    FROM events e
    LEFT JOIN source_documents sd ON sd.id = e.source_document_id
"""

_FILTERABLE = {
    "peptide": "e.peptide_id = ?",
    "severity": "e.severity = ?",
    "confidence": "e.confidence = ?",
    "source_type": "e.source_id = ?",
    "event_type": "e.event_type = ?",
}

VALID_OPERATOR_STATUSES = {"watch", "ignore", "promoted", "archived"}


def _event_where(filters: dict[str, Any]) -> tuple[str, list[Any]]:
    clauses: list[str] = []
    params: list[Any] = []
    for key, sql in _FILTERABLE.items():
        value = filters.get(key)
        if value is not None:
            clauses.append(sql)
            params.append(value)
    # free-text / company search over the event title (company event filtering
    # is approximated by title match, since events carry no company FK)
    if filters.get("q"):
        clauses.append("e.title LIKE ?")
        params.append(f"%{filters['q']}%")
    if filters.get("date_from"):
        clauses.append("e.created_at >= ?")
        params.append(filters["date_from"])
    if filters.get("date_to"):
        clauses.append("e.created_at <= ?")
        params.append(filters["date_to"])
    review = filters.get("review_status")
    if review in ("needs_review", "reviewed"):
        clauses.append("e.needs_review = ?")
        params.append(1 if review == "needs_review" else 0)
    where = (" WHERE " + " AND ".join(clauses)) if clauses else ""
    return where, params


def list_events(
    connection: sqlite3.Connection,
    *,
    filters: dict[str, Any] | None = None,
    limit: int = 50,
    offset: int = 0,
) -> dict[str, Any]:
    connection.row_factory = sqlite3.Row  # defensive: callers must get dict rows
    filters = filters or {}
    where, params = _event_where(filters)
    total = connection.execute(
        f"SELECT COUNT(*) FROM events e{where}", params
    ).fetchone()[0]
    rows = connection.execute(
        f"{EVENT_SELECT}{where} ORDER BY e.created_at DESC, e.id DESC LIMIT ? OFFSET ?",
        [*params, limit, offset],
    ).fetchall()
    return {
        "items": [dict(r) for r in rows],
        "total": total,
        "limit": limit,
        "offset": offset,
    }


def get_event(connection: sqlite3.Connection, event_id: int) -> dict[str, Any] | None:
    connection.row_factory = sqlite3.Row
    row = connection.execute(
        f"{EVENT_SELECT} WHERE e.id = ?", (event_id,)
    ).fetchone()
    return dict(row) if row else None


def source_health(connection: sqlite3.Connection) -> list[dict[str, Any]]:
    """Latest task status + last error per source, newest run first."""

    connection.row_factory = sqlite3.Row
    rows = connection.execute(
        """
        SELECT rt.source_id, rt.status, rt.attempt, rt.error, rt.finished_at, rt.counts_json
        FROM run_tasks rt
        JOIN (
            SELECT source_id, MAX(rowid) AS last_rowid
            FROM run_tasks GROUP BY source_id
        ) latest ON latest.last_rowid = rt.rowid
        ORDER BY rt.source_id
        """
    ).fetchall()
    out = []
    for r in rows:
        last_line = (r["error"].strip().splitlines()[-1] if r["error"] else None)
        out.append(
            {
                "source_id": r["source_id"],
                "status": r["status"],
                "attempt": r["attempt"],
                "last_error": last_line,
                "finished_at": r["finished_at"],
            }
        )
    return out


def health_counts(connection: sqlite3.Connection) -> dict[str, int]:
    out = {}
    for table in ("events", "company_documents", "regulatory_documents", "clinical_trials"):
        out[table] = connection.execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0]
    return out


def _connect_operator_readonly(path: str | Path) -> sqlite3.Connection | None:
    target = Path(path)
    if not target.exists():
        return None
    uri = f"file:{target.resolve()}?mode=ro"
    con = sqlite3.connect(uri, uri=True)
    con.row_factory = sqlite3.Row
    return con


def _operator_entity_to_dict(row: sqlite3.Row) -> dict[str, Any]:
    out = dict(row)
    out["has_notes"] = bool(out.pop("user_notes", None))
    return out


def list_operator_entities(
    path: str | Path,
    *,
    statuses: list[str] | None = None,
) -> list[dict[str, Any]]:
    statuses = statuses or []
    invalid = sorted(set(statuses) - VALID_OPERATOR_STATUSES)
    if invalid:
        raise ValueError(f"invalid operator status: {', '.join(invalid)}")
    con = _connect_operator_readonly(path)
    if con is None:
        return []
    try:
        where = ""
        params: list[Any] = []
        if statuses:
            where = f"WHERE oe.status IN ({','.join('?' for _ in statuses)})"
            params.extend(statuses)
        rows = con.execute(
            f"""
            SELECT
              oe.entity_key,
              oe.display_name,
              oe.entity_type,
              oe.status,
              oe.priority,
              oe.first_seen_at,
              oe.last_seen_at,
              oe.appearance_count,
              oe.source_url_count,
              oe.user_notes,
              oe.created_by,
              oe.created_at,
              oe.updated_at,
              COUNT(oee.id) AS memory_event_count,
              MAX(oee.observed_at) AS latest_memory_event_at
            FROM operator_entities oe
            LEFT JOIN operator_entity_events oee ON oee.entity_key = oe.entity_key
            {where}
            GROUP BY oe.entity_key
            ORDER BY
              CASE oe.status WHEN 'watch' THEN 0 WHEN 'promoted' THEN 1 WHEN 'ignore' THEN 2 ELSE 3 END,
              CASE oe.priority WHEN 'high' THEN 0 WHEN 'normal' THEN 1 ELSE 2 END,
              oe.updated_at DESC,
              oe.display_name
            """,
            params,
        ).fetchall()
    except sqlite3.OperationalError:
        return []
    finally:
        con.close()
    return [_operator_entity_to_dict(row) for row in rows]


def get_operator_entity_detail(
    path: str | Path,
    *,
    entity_key: str,
    limit: int = 30,
) -> dict[str, Any] | None:
    con = _connect_operator_readonly(path)
    if con is None:
        return None
    try:
        row = con.execute(
            """
            SELECT
              entity_key,
              display_name,
              entity_type,
              status,
              priority,
              first_seen_at,
              last_seen_at,
              appearance_count,
              source_url_count,
              user_notes,
              created_by,
              created_at,
              updated_at
            FROM operator_entities
            WHERE entity_key = ?
            """,
            (entity_key,),
        ).fetchone()
        if row is None:
            return None
        events = con.execute(
            """
            SELECT id, run_id, event_type, source_family, source_url, observed_at, fact_summary
            FROM operator_entity_events
            WHERE entity_key = ?
            ORDER BY observed_at DESC, id DESC
            LIMIT ?
            """,
            (entity_key, limit),
        ).fetchall()
    except sqlite3.OperationalError:
        return None
    finally:
        con.close()
    return {
        "entity": _operator_entity_to_dict(row),
        "source_facts": [dict(event) for event in events],
    }
