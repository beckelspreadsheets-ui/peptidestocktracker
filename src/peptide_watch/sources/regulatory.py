"""Shared regulatory document normalization and storage."""

from __future__ import annotations

import hashlib
import json
import re
import sqlite3
from pathlib import Path
from typing import Any

from pydantic import BaseModel, ConfigDict, Field

from peptide_watch.config import WatchConfig
from peptide_watch.database import connect, init_db
from peptide_watch.events import ad_hoc_run_id, insert_event

STATUS_PATTERNS = {
    "503A Bulks List": re.compile(r"\b503A\s+Bulks?\s+List\b", re.IGNORECASE),
    "503B Bulks List": re.compile(r"\b503B\s+Bulks?\s+List\b", re.IGNORECASE),
    "Category 1": re.compile(r"\bCategory\s+1\b", re.IGNORECASE),
    "Category 2": re.compile(r"\bCategory\s+2\b", re.IGNORECASE),
    "Category 3": re.compile(r"\bCategory\s+3\b", re.IGNORECASE),
    "PCAC": re.compile(r"\bPCAC\b|Pharmacy Compounding Advisory Committee", re.IGNORECASE),
    "advisory committee": re.compile(r"\badvisory committee\b", re.IGNORECASE),
    "briefing": re.compile(r"\bbriefing\b", re.IGNORECASE),
    "transcript": re.compile(r"\btranscript\b", re.IGNORECASE),
    "minutes": re.compile(r"\bminutes\b", re.IGNORECASE),
    "included": re.compile(r"\bincluded?\b|\binclusion\b", re.IGNORECASE),
    "removed": re.compile(r"\bremoved?\b|\bremoval\b", re.IGNORECASE),
    "injectable": re.compile(r"\binjectable\b|\binjection\b", re.IGNORECASE),
    "non-injectable": re.compile(r"\bnon[- ]injectable\b", re.IGNORECASE),
}


class RegulatoryDocument(BaseModel):
    """Normalized FDA/Federal Register document state."""

    model_config = ConfigDict(extra="forbid")

    document_key: str
    source_id: str
    source_type: str
    url: str
    title: str | None = None
    document_number: str | None = None
    publication_date: str | None = None
    docket_ids: list[str] = Field(default_factory=list)
    content_hash: str
    content_text: str
    raw_sha256: str = ""
    parser_version: int = 1
    raw_content: bytes | None = Field(default=None, exclude=True, repr=False)
    peptide_ids: list[str] = Field(default_factory=list)
    matched_aliases: list[str] = Field(default_factory=list)
    route_notes: dict[str, list[str]] = Field(default_factory=dict)
    status_terms: list[str] = Field(default_factory=list)
    metadata: dict[str, Any] = Field(default_factory=dict)


class StoreResult(BaseModel):
    """Persistence result for one regulatory document."""

    document_key: str
    inserted: bool
    changed: bool
    events_created: int


class RegulatoryScanResult(BaseModel):
    """Regulatory scan summary."""

    fetched: int
    stored: int
    inserted: int
    changed: int
    events_created: int
    source_ids: list[str] = Field(default_factory=list)
    queries: list[str] = Field(default_factory=list)
    errors: list[str] = Field(default_factory=list)


def build_regulatory_document(
    *,
    document_key: str,
    source_id: str,
    source_type: str,
    url: str,
    content_text: str,
    config: WatchConfig,
    title: str | None = None,
    document_number: str | None = None,
    publication_date: str | None = None,
    docket_ids: list[str] | None = None,
    metadata: dict[str, Any] | None = None,
    content_hash: str | None = None,
    raw_content: bytes | None = None,
    parser_version: int = 1,
) -> RegulatoryDocument:
    """Create a normalized regulatory document with peptide/status matches.

    ``content_hash`` is canonical (over the normalized text) and drives change
    detection; ``raw_content`` is the exact fetched payload, hashed separately
    so volatile markup never looks like a content change.
    """

    normalized_text = normalize_text(content_text)
    peptide_ids, matched_aliases = match_peptide_aliases(normalized_text, config)
    return RegulatoryDocument(
        document_key=document_key,
        source_id=source_id,
        source_type=source_type,
        url=url,
        title=title,
        document_number=document_number,
        publication_date=publication_date,
        docket_ids=sorted(set(docket_ids or [])),
        content_hash=content_hash or hash_bytes(normalized_text.encode("utf-8")),
        content_text=normalized_text,
        raw_sha256=hash_bytes(raw_content) if raw_content is not None else "",
        parser_version=parser_version,
        raw_content=raw_content,
        peptide_ids=peptide_ids,
        matched_aliases=matched_aliases,
        route_notes=extract_route_notes(normalized_text, peptide_ids, matched_aliases, config),
        status_terms=extract_status_terms(normalized_text),
        metadata=metadata or {},
    )


def store_regulatory_document(
    db_path: str | Path,
    document: RegulatoryDocument,
    *,
    run_id: str | None = None,
) -> StoreResult:
    """Upsert a regulatory document and emit reviewable new/change events."""

    init_db(db_path)
    connection = open_connection(db_path)
    try:
        result = write_regulatory_document(
            connection, document, run_id=run_id or ad_hoc_run_id()
        )
        connection.commit()
        return result
    finally:
        connection.close()


def write_regulatory_document(
    connection: sqlite3.Connection,
    document: RegulatoryDocument,
    *,
    run_id: str,
) -> StoreResult:
    """Write one document's full state (record + snapshot + events), no commit.

    The caller owns the transaction so the whole write set is atomic.
    """

    existing = _existing_document(connection, document.document_key)

    if existing is None:
        _insert_document(connection, document)
        _insert_snapshot(connection, document)
        source_document_id = _insert_source_document(connection, document)
        created = _create_event(
            connection,
            document,
            source_document_id,
            run_id=run_id,
            event_type=_new_event_type(document),
            field="",
            old_value="",
            new_value=document.content_hash,
            title=f"Regulatory document detected: {document.title or document.document_key}",
            what_changed=(
                "Confirmed fact: an official public regulatory source was detected and "
                f"stored from {document.url}."
            ),
            severity=_severity_for_document(document, changed=False),
        )
        return StoreResult(
            document_key=document.document_key,
            inserted=True,
            changed=False,
            events_created=int(created),
        )

    if existing["content_hash"] == document.content_hash:
        _touch_document(connection, document)
        return StoreResult(document_key=document.document_key, inserted=False, changed=False, events_created=0)

    previous_raw = _row_value(existing, "raw_sha256")
    if previous_raw and document.raw_sha256 and previous_raw == document.raw_sha256:
        # Identical fetched bytes parsed differently: a parser upgrade, not a
        # content change. Update stored state silently.
        _insert_snapshot(connection, document)
        _update_document(connection, document)
        return StoreResult(document_key=document.document_key, inserted=False, changed=False, events_created=0)

    _insert_snapshot(connection, document)
    _update_document(connection, document)
    source_document_id = _insert_source_document(connection, document)
    created = _create_event(
        connection,
        document,
        source_document_id,
        run_id=run_id,
        event_type=_changed_event_type(document),
        field="content",
        old_value=str(existing["content_hash"]),
        new_value=document.content_hash,
        title=f"Regulatory document changed: {document.title or document.document_key}",
        what_changed=(
            "Confirmed fact: content hash changed for an official public regulatory source. "
            f"Previous hash {existing['content_hash']} changed to {document.content_hash}."
        ),
        severity=_severity_for_document(document, changed=True),
    )
    return StoreResult(
        document_key=document.document_key,
        inserted=False,
        changed=True,
        events_created=int(created),
    )


def list_regulatory_documents(
    db_path: str | Path,
    *,
    source_prefix: str | None = None,
    limit: int = 100,
) -> list[RegulatoryDocument]:
    """List stored regulatory documents."""

    init_db(db_path)
    if limit < 1:
        raise ValueError("limit must be at least 1")
    params: list[str | int] = []
    where = ""
    if source_prefix:
        where = "WHERE source_id LIKE ?"
        params.append(f"{source_prefix}%")
    params.append(limit)
    with open_connection(db_path) as connection:
        rows = connection.execute(
            f"""
            SELECT *
            FROM regulatory_documents
            {where}
            ORDER BY last_seen_at DESC, document_key ASC
            LIMIT ?
            """,
            params,
        ).fetchall()
    return [_row_to_document(row) for row in rows]


def export_regulatory_documents_markdown(documents: list[RegulatoryDocument]) -> str:
    """Export regulatory documents as a concise markdown table."""

    columns = [
        "source_id",
        "source_type",
        "document_number",
        "publication_date",
        "status_terms",
        "peptide_ids",
        "title",
        "url",
    ]
    header = "| " + " | ".join(columns) + " |"
    separator = "| " + " | ".join("---" for _ in columns) + " |"
    rows = []
    for document in documents:
        values = []
        for column in columns:
            value = getattr(document, column)
            if isinstance(value, list):
                value = ", ".join(value)
            values.append(_markdown_cell(value))
        rows.append("| " + " | ".join(values) + " |")
    return "\n".join([header, separator, *rows])


def hash_bytes(content: bytes) -> str:
    return hashlib.sha256(content).hexdigest()


def normalize_text(text: str) -> str:
    return " ".join(text.split())


def match_peptide_aliases(text: str, config: WatchConfig) -> tuple[list[str], list[str]]:
    lowered = text.casefold()
    peptide_ids: list[str] = []
    aliases: list[str] = []
    for peptide in config.peptides:
        matched = [alias for alias in peptide.aliases if alias.casefold() in lowered]
        if matched:
            peptide_ids.append(peptide.id)
            aliases.extend(matched)
    return sorted(set(peptide_ids)), sorted(set(aliases), key=str.casefold)


def extract_status_terms(text: str) -> list[str]:
    return sorted(term for term, pattern in STATUS_PATTERNS.items() if pattern.search(text))


def extract_route_notes(
    text: str,
    peptide_ids: list[str],
    matched_aliases: list[str],
    config: WatchConfig,
) -> dict[str, list[str]]:
    notes: dict[str, list[str]] = {}
    sentences = _sentences(text)
    aliases_by_peptide = {
        peptide.id: [alias for alias in peptide.aliases if alias in matched_aliases]
        for peptide in config.peptides
    }
    route_or_status = re.compile(
        r"injectable|non[- ]injectable|route|Category\s+[123]|503A|503B|Bulks?\s+List|PCAC|removed|included",
        re.IGNORECASE,
    )
    for peptide_id in peptide_ids:
        snippets: list[str] = []
        for sentence in sentences:
            lowered = sentence.casefold()
            if not route_or_status.search(sentence):
                continue
            if any(alias.casefold() in lowered for alias in aliases_by_peptide.get(peptide_id, [])):
                snippets.append(sentence[:500])
        if snippets:
            notes[peptide_id] = sorted(set(snippets))
    return notes


def _sentences(text: str) -> list[str]:
    return [part.strip() for part in re.split(r"(?<=[.!?])\s+", text) if part.strip()]


def _insert_document(connection: sqlite3.Connection, document: RegulatoryDocument) -> None:
    connection.execute(
        """
        INSERT INTO regulatory_documents (
          document_key,
          source_id,
          source_type,
          url,
          title,
          document_number,
          publication_date,
          docket_ids_json,
          content_hash,
          content_text,
          peptide_ids_json,
          matched_aliases_json,
          route_notes_json,
          status_terms_json,
          metadata_json,
          raw_sha256,
          parser_version
        )
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
        _document_values(document),
    )


def _update_document(connection: sqlite3.Connection, document: RegulatoryDocument) -> None:
    connection.execute(
        """
        UPDATE regulatory_documents
        SET source_id = ?,
            source_type = ?,
            url = ?,
            title = ?,
            document_number = ?,
            publication_date = ?,
            docket_ids_json = ?,
            content_hash = ?,
            content_text = ?,
            peptide_ids_json = ?,
            matched_aliases_json = ?,
            route_notes_json = ?,
            status_terms_json = ?,
            metadata_json = ?,
            raw_sha256 = ?,
            parser_version = ?,
            last_seen_at = CURRENT_TIMESTAMP,
            updated_at = CURRENT_TIMESTAMP
        WHERE document_key = ?
        """,
        (*_document_values(document)[1:], document.document_key),
    )


def _touch_document(connection: sqlite3.Connection, document: RegulatoryDocument) -> None:
    connection.execute(
        """
        UPDATE regulatory_documents
        SET last_seen_at = CURRENT_TIMESTAMP,
            matched_aliases_json = ?,
            peptide_ids_json = ?,
            status_terms_json = ?,
            raw_sha256 = ?,
            parser_version = ?
        WHERE document_key = ?
        """,
        (
            _json(document.matched_aliases),
            _json(document.peptide_ids),
            _json(document.status_terms),
            document.raw_sha256,
            document.parser_version,
            document.document_key,
        ),
    )


def _document_values(document: RegulatoryDocument) -> tuple[Any, ...]:
    return (
        document.document_key,
        document.source_id,
        document.source_type,
        document.url,
        document.title,
        document.document_number,
        document.publication_date,
        _json(document.docket_ids),
        document.content_hash,
        document.content_text,
        _json(document.peptide_ids),
        _json(document.matched_aliases),
        _json(document.route_notes),
        _json(document.status_terms),
        _json(document.metadata),
        document.raw_sha256,
        document.parser_version,
    )


def _insert_snapshot(connection: sqlite3.Connection, document: RegulatoryDocument) -> None:
    if document.raw_content is not None and document.raw_sha256:
        connection.execute(
            "INSERT OR IGNORE INTO raw_blobs (raw_sha256, content) VALUES (?, ?)",
            (document.raw_sha256, document.raw_content),
        )
    connection.execute(
        """
        INSERT OR IGNORE INTO regulatory_document_snapshots (
          document_key,
          content_hash,
          url,
          content_text,
          metadata_json,
          raw_sha256,
          parser_version
        )
        VALUES (?, ?, ?, ?, ?, ?, ?)
        """,
        (
            document.document_key,
            document.content_hash,
            document.url,
            document.content_text,
            _json(document.metadata),
            document.raw_sha256,
            document.parser_version,
        ),
    )


def _insert_source_document(connection: sqlite3.Connection, document: RegulatoryDocument) -> int:
    cursor = connection.execute(
        """
        INSERT INTO source_documents (
          source_id,
          url,
          title,
          retrieved_at,
          content_hash,
          evidence_tier
        )
        VALUES (?, ?, ?, CURRENT_TIMESTAMP, ?, 'A')
        """,
        (document.source_id, document.url, document.title, document.content_hash),
    )
    return int(cursor.lastrowid)


def _create_event(
    connection: sqlite3.Connection,
    document: RegulatoryDocument,
    source_document_id: int,
    *,
    run_id: str,
    event_type: str,
    field: str,
    old_value: str,
    new_value: str,
    title: str,
    what_changed: str,
    severity: str,
) -> bool:
    return insert_event(
        connection,
        source_id=document.source_id,
        external_id=document.document_key,
        event_type=event_type,
        field=field,
        old_value=old_value,
        new_value=new_value,
        run_id=run_id,
        title=title,
        what_changed=what_changed,
        why_it_matters=(
            "Confirmed fact: this event comes from an official public regulatory source. "
            "Inference: regulatory-source changes may warrant follow-up research. "
            "Speculation: possible market relevance is uncertain and requires review; "
            "PCAC or 503A movement is not FDA drug approval."
        ),
        confidence="high",
        severity=severity,
        directness="direct",
        stock_market_relevance=(
            "Possible market relevance only; this is not a buy/sell recommendation. "
            "Verify independently."
        ),
        peptide_id=document.peptide_ids[0] if document.peptide_ids else None,
        source_document_id=source_document_id,
    )


def _uspto_event_type(document: RegulatoryDocument) -> str:
    if document.metadata.get("assigned_company_public"):
        return "patent_assignment_to_public_company"
    if document.metadata.get("assigned_company_id"):
        return "patent_assignment_to_watchlist_company"
    return "patent_publication"


def _regulations_event_type(document: RegulatoryDocument) -> str:
    doc_type = str(document.metadata.get("document_type") or "").lower()
    if document.metadata.get("open_for_comment"):
        if "rule" in doc_type:
            return "regulatory_rule_open_for_comment"
        return "regulatory_comment_period_open"
    if "submission" in doc_type or "comment" in doc_type:
        return "regulatory_public_comment"
    return "regulatory_docket_activity"


def _new_event_type(document: RegulatoryDocument) -> str:
    if document.source_id.startswith("openfda_shortage"):
        return "drug_shortage"
    if document.source_id.startswith("regulations"):
        return _regulations_event_type(document)
    if document.source_id.startswith("nih_reporter"):
        return "grant_award"
    if document.source_id.startswith("uspto"):
        return _uspto_event_type(document)
    if document.source_id.startswith("openfda"):
        return "fda_enforcement_report"
    if document.source_id.startswith("pubmed"):
        return "pubmed_publication"
    if document.source_id.startswith("federal_register"):
        return "federal_register_notice_detected"
    if "503a" in document.source_id.lower():
        return "fda_503a_document_detected"
    if "pcac" in document.source_id.lower():
        return "fda_pcac_document_detected"
    if "safety" in document.source_id.lower():
        return "fda_safety_risk_document_detected"
    return "regulatory_document_detected"


def _changed_event_type(document: RegulatoryDocument) -> str:
    if document.source_id.startswith("openfda_shortage"):
        return "drug_shortage_update"
    if document.source_id.startswith("regulations"):
        return _regulations_event_type(document)
    if document.source_id.startswith("nih_reporter"):
        return "grant_award"
    if document.source_id.startswith("uspto"):
        return _uspto_event_type(document)
    if document.source_id.startswith("openfda"):
        return "fda_enforcement_report"
    if document.source_id.startswith("pubmed"):
        return "pubmed_publication"
    if document.source_id.startswith("federal_register"):
        return "federal_register_notice_changed"
    if "503a" in document.source_id.lower():
        return "fda_503a_status_update"
    if "pcac" in document.source_id.lower():
        return "fda_pcac_update"
    if "safety" in document.source_id.lower():
        return "fda_safety_risk_update"
    return "regulatory_document_changed"


def _severity_for_document(document: RegulatoryDocument, *, changed: bool) -> str:
    source_id = document.source_id.lower()
    if source_id.startswith("regulations"):
        doc_type = str(document.metadata.get("document_type") or "").lower()
        if document.metadata.get("open_for_comment"):
            # A rule being written that you can still comment on is the most
            # actionable leading signal; a notice/meeting docket is high.
            return "critical" if "rule" in doc_type else "high"
        if "submission" in doc_type or "comment" in doc_type:
            return "medium"  # a filed comment reveals who is positioning
        return "medium"
    if source_id.startswith("uspto"):
        if document.metadata.get("assigned_company_public"):
            return "critical"  # peptide patent assigned to a public watchlist company
        if document.metadata.get("assigned_company_id"):
            return "high"  # assigned to a private watchlist company
        return "medium"  # peptide patent with no watchlist owner: context
    if source_id.startswith("openfda_shortage"):
        status = str(document.metadata.get("status") or "").lower()
        update_type = str(document.metadata.get("update_type") or "").lower()
        if "resolv" in status:
            return "low"  # shortage cleared: compounding-demand tailwind fading
        if update_type == "new":
            return "high"  # a new peptide-drug shortage opens compounding demand
        return "medium"
    if source_id.startswith("openfda") and document.peptide_ids:
        return "high"
    if source_id.startswith("nih_reporter"):
        if document.metadata.get("small_business_award"):
            return "high"  # SBIR/STTR award to a small company
        return "medium"
    if changed and ("503a" in source_id or "pcac" in source_id):
        return "critical"
    if document.source_id.startswith("federal_register") or "pcac" in source_id or "503a" in source_id:
        return "high"
    return "medium"


def _existing_document(connection: sqlite3.Connection, document_key: str) -> sqlite3.Row | None:
    return connection.execute(
        "SELECT * FROM regulatory_documents WHERE document_key = ?",
        (document_key,),
    ).fetchone()


def _row_to_document(row: sqlite3.Row) -> RegulatoryDocument:
    return RegulatoryDocument.model_validate(
        {
            "document_key": row["document_key"],
            "source_id": row["source_id"],
            "source_type": row["source_type"],
            "url": row["url"],
            "title": row["title"],
            "document_number": row["document_number"],
            "publication_date": row["publication_date"],
            "docket_ids": json.loads(row["docket_ids_json"]),
            "content_hash": row["content_hash"],
            "content_text": row["content_text"],
            "peptide_ids": json.loads(row["peptide_ids_json"]),
            "matched_aliases": json.loads(row["matched_aliases_json"]),
            "route_notes": json.loads(row["route_notes_json"]),
            "status_terms": json.loads(row["status_terms_json"]),
            "metadata": json.loads(row["metadata_json"]),
            "raw_sha256": _row_value(row, "raw_sha256") or "",
            "parser_version": _row_value(row, "parser_version") or 0,
        }
    )


def _row_value(row: sqlite3.Row, key: str) -> Any:
    try:
        return row[key]
    except IndexError:
        return None


def open_connection(db_path: str | Path) -> sqlite3.Connection:
    connection = connect(db_path)
    connection.row_factory = sqlite3.Row
    return connection


def _json(value: Any) -> str:
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False)


def _markdown_cell(value: object) -> str:
    if value is None:
        return ""
    return str(value).replace("|", "\\|").replace("\n", " ")
