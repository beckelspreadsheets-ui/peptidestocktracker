"""Read queries for the API. The only place the web layer holds SQL.

Every event row is returned with its source URL + evidence and the compliance
fields, per the product's disclosure posture.
"""

from __future__ import annotations

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


def _event_where(filters: dict[str, Any]) -> tuple[str, list[Any]]:
    clauses: list[str] = []
    params: list[Any] = []
    for key, sql in _FILTERABLE.items():
        value = filters.get(key)
        if value is not None:
            clauses.append(sql)
            params.append(value)
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
    row = connection.execute(
        f"{EVENT_SELECT} WHERE e.id = ?", (event_id,)
    ).fetchone()
    return dict(row) if row else None


def source_health(connection: sqlite3.Connection) -> list[dict[str, Any]]:
    """Latest task status + last error per source, newest run first."""

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
