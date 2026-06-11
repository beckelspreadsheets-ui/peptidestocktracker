"""Shared event insertion with a real identity key for idempotent writes."""

from __future__ import annotations

import hashlib
import sqlite3
import uuid

IDENTITY_SEPARATOR = "\x1f"


def ad_hoc_run_id() -> str:
    """Run id for stores invoked outside a tracked scan run."""

    return "adhoc-" + uuid.uuid4().hex[:12]


def identity_key(
    source_id: str,
    external_id: str,
    event_type: str,
    field: str,
    old_value: str,
    new_value: str,
    run_id: str,
) -> str:
    parts = (source_id, external_id, event_type, field, old_value, new_value, run_id)
    return hashlib.sha256(IDENTITY_SEPARATOR.join(parts).encode("utf-8")).hexdigest()


def insert_event(
    connection: sqlite3.Connection,
    *,
    source_id: str,
    external_id: str,
    event_type: str,
    field: str,
    old_value: str,
    new_value: str,
    run_id: str,
    title: str,
    what_changed: str,
    why_it_matters: str,
    confidence: str,
    severity: str,
    directness: str,
    stock_market_relevance: str,
    peptide_id: str | None = None,
    source_document_id: int | None = None,
) -> bool:
    """Insert an event idempotently; returns False when the identity already exists."""

    cursor = connection.execute(
        """
        INSERT OR IGNORE INTO events (
          event_type,
          peptide_id,
          source_document_id,
          title,
          what_changed,
          why_it_matters,
          confidence,
          severity,
          directness,
          stock_market_relevance,
          needs_review,
          source_id,
          external_id,
          field,
          old_value,
          new_value,
          run_id,
          identity_key
        )
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 1, ?, ?, ?, ?, ?, ?, ?)
        """,
        (
            event_type,
            peptide_id,
            source_document_id,
            title,
            what_changed,
            why_it_matters,
            confidence,
            severity,
            directness,
            stock_market_relevance,
            source_id,
            external_id,
            field,
            old_value,
            new_value,
            run_id,
            identity_key(source_id, external_id, event_type, field, old_value, new_value, run_id),
        ),
    )
    return cursor.rowcount > 0
