"""Shared company/news/filing document normalization and storage."""

from __future__ import annotations

import hashlib
import json
import re
import sqlite3
from pathlib import Path
from typing import Any

from pydantic import BaseModel, ConfigDict, Field

from peptide_watch.config import CompanyConfig, WatchConfig
from peptide_watch.database import connect, init_db
from peptide_watch.events import ad_hoc_run_id, insert_event
from peptide_watch.sources.regulatory import match_peptide_aliases, normalize_text

CATALYST_KEYWORD_PATTERNS = {
    "regulatory_or_compounding": re.compile(
        r"\bFDA\b|\b503A\b|\b503B\b|\bPCAC\b|\bcompounding\b|\bcompound(?:ed|ing)?\b",
        re.IGNORECASE,
    ),
    "commercial_launch": re.compile(
        r"\bcommercial\s+(?:launch|release)\b|\bproduct\s+launch\b|"
        r"\blaunched\b|\bpurchase\s+order\b|\border(?:ed|s)?\b",
        re.IGNORECASE,
    ),
    "patent_or_ip": re.compile(
        r"\bpatent\b|\bprovisional\b|\bUSPTO\b|\bWIPO\b|\bPCT\b|"
        r"\bintellectual\s+property\b",
        re.IGNORECASE,
    ),
    "licensing_or_acquisition": re.compile(
        r"\blicens(?:e|ed|ing)\b|\bacquir(?:e|ed|es|ing|s)\b|"
        r"\bacquisition\b|\bpartnership\b|\bagreement\b|\bmerger\b",
        re.IGNORECASE,
    ),
    "clinical_asset": re.compile(
        r"\bclinical\s+trial\b|\bPhase\s+[123]\b|\bIND\b|\bNDA\b|"
        r"\bpivotal\b|\btop[- ]line\b|\brecruiting\b",
        re.IGNORECASE,
    ),
    "infrastructure": re.compile(
        r"\bpeptide\s+facility\b|\bpharmacy\b|\btelehealth\b|"
        r"\bmanufactur(?:e|ing)\b|\bCDMO\b|\bAPI\b",
        re.IGNORECASE,
    ),
    "ticker_or_listing": re.compile(
        r"\bticker\b|\blisting\b|\bOTC\b|\bCSE\b|\bNASDAQ\b|\bNYSE\b",
        re.IGNORECASE,
    ),
}


class CompanyDocument(BaseModel):
    """Normalized company page, news page, or public filing state."""

    model_config = ConfigDict(extra="forbid")

    document_key: str
    source_id: str
    source_type: str
    url: str
    title: str | None = None
    company_key: str | None = None
    company_name: str | None = None
    ticker: str | None = None
    exchange: str | None = None
    filing_type: str | None = None
    accession_number: str | None = None
    filing_date: str | None = None
    source_tier: str | None = None
    content_hash: str
    content_text: str
    raw_sha256: str = ""
    parser_version: int = 1
    raw_content: bytes | None = Field(default=None, exclude=True, repr=False)
    peptide_ids: list[str] = Field(default_factory=list)
    matched_aliases: list[str] = Field(default_factory=list)
    company_matches: list[str] = Field(default_factory=list)
    keyword_matches: list[str] = Field(default_factory=list)
    metadata: dict[str, Any] = Field(default_factory=dict)


class StoreResult(BaseModel):
    """Persistence result for one company/news/filing document."""

    document_key: str
    inserted: bool
    changed: bool
    events_created: int


class CompanyMonitorScanResult(BaseModel):
    """Company/news/filing scan summary."""

    fetched: int
    stored: int
    inserted: int
    changed: int
    events_created: int
    source_ids: list[str] = Field(default_factory=list)
    company_ids: list[str] = Field(default_factory=list)
    errors: list[str] = Field(default_factory=list)


def build_company_document(
    *,
    document_key: str,
    source_id: str,
    source_type: str,
    url: str,
    content_text: str,
    config: WatchConfig,
    title: str | None = None,
    company_key: str | None = None,
    company_name: str | None = None,
    ticker: str | None = None,
    exchange: str | None = None,
    filing_type: str | None = None,
    accession_number: str | None = None,
    filing_date: str | None = None,
    source_tier: str | None = None,
    metadata: dict[str, Any] | None = None,
    content_hash: str | None = None,
    raw_content: bytes | None = None,
    parser_version: int = 1,
) -> CompanyDocument:
    """Create a normalized company/news/filing document with review metadata.

    ``content_hash`` is canonical (over the normalized text) and drives change
    detection; ``raw_content`` is the exact fetched payload, hashed separately
    so volatile markup never looks like a content change.
    """

    normalized_text = normalize_text(content_text)
    peptide_ids, matched_aliases = match_peptide_aliases(normalized_text, config)
    company = _company_by_id(config, company_key)
    resolved_company_name = company_name or (company.name if company else None)
    resolved_ticker = ticker or (company.ticker if company else None)
    resolved_exchange = exchange or (company.exchange if company else None)
    company_matches = match_company_mentions(normalized_text, config, assigned_company_id=company_key)

    return CompanyDocument(
        document_key=document_key,
        source_id=source_id,
        source_type=source_type,
        url=url,
        title=title,
        company_key=company_key,
        company_name=resolved_company_name,
        ticker=resolved_ticker,
        exchange=resolved_exchange,
        filing_type=filing_type,
        accession_number=accession_number,
        filing_date=filing_date,
        source_tier=source_tier,
        content_hash=content_hash or hash_bytes(normalized_text.encode("utf-8")),
        content_text=normalized_text,
        raw_sha256=hash_bytes(raw_content) if raw_content is not None else "",
        parser_version=parser_version,
        raw_content=raw_content,
        peptide_ids=peptide_ids,
        matched_aliases=matched_aliases,
        company_matches=company_matches,
        keyword_matches=extract_keyword_matches(normalized_text),
        metadata=metadata or {},
    )


def store_company_document(
    db_path: str | Path,
    document: CompanyDocument,
    *,
    run_id: str | None = None,
) -> StoreResult:
    """Upsert a company/news/filing document and emit reviewable events for matches."""

    init_db(db_path)
    connection = open_connection(db_path)
    try:
        result = write_company_document(
            connection, document, run_id=run_id or ad_hoc_run_id()
        )
        connection.commit()
        return result
    finally:
        connection.close()


def write_company_document(
    connection: sqlite3.Connection,
    document: CompanyDocument,
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
        events_created = _create_event_if_relevant(
            connection,
            document,
            run_id=run_id,
            changed=False,
            previous_hash=None,
        )
        return StoreResult(
            document_key=document.document_key,
            inserted=True,
            changed=False,
            events_created=events_created,
        )

    if existing["content_hash"] == document.content_hash:
        _touch_document(connection, document)
        return StoreResult(
            document_key=document.document_key,
            inserted=False,
            changed=False,
            events_created=0,
        )

    previous_raw = _row_value(existing, "raw_sha256")
    if previous_raw and document.raw_sha256 and previous_raw == document.raw_sha256:
        # Identical fetched bytes parsed differently: a parser upgrade, not a
        # content change. Update stored state silently.
        _insert_snapshot(connection, document)
        _update_document(connection, document)
        return StoreResult(
            document_key=document.document_key,
            inserted=False,
            changed=False,
            events_created=0,
        )

    _insert_snapshot(connection, document)
    _update_document(connection, document)
    events_created = _create_event_if_relevant(
        connection,
        document,
        run_id=run_id,
        changed=True,
        previous_hash=str(existing["content_hash"]),
    )
    return StoreResult(
        document_key=document.document_key,
        inserted=False,
        changed=True,
        events_created=events_created,
    )


def list_company_documents(
    db_path: str | Path,
    *,
    source_type: str | None = None,
    limit: int = 100,
) -> list[CompanyDocument]:
    """List stored company/news/filing documents."""

    init_db(db_path)
    if limit < 1:
        raise ValueError("limit must be at least 1")

    params: list[str | int] = []
    where = ""
    if source_type:
        where = "WHERE source_type = ?"
        params.append(source_type)
    params.append(limit)
    with open_connection(db_path) as connection:
        rows = connection.execute(
            f"""
            SELECT *
            FROM company_documents
            {where}
            ORDER BY last_seen_at DESC, document_key ASC
            LIMIT ?
            """,
            params,
        ).fetchall()
    return [_row_to_document(row) for row in rows]


def export_company_documents_markdown(documents: list[CompanyDocument]) -> str:
    """Export company/news/filing documents as a concise markdown table."""

    columns = [
        "source_id",
        "source_type",
        "company_name",
        "ticker",
        "filing_type",
        "filing_date",
        "keyword_matches",
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


def extract_keyword_matches(text: str) -> list[str]:
    """Return catalyst keyword buckets found in text."""

    return sorted(
        label for label, pattern in CATALYST_KEYWORD_PATTERNS.items() if pattern.search(text)
    )


def match_company_mentions(
    text: str,
    config: WatchConfig,
    *,
    assigned_company_id: str | None = None,
) -> list[str]:
    """Match configured company names and tickers in document text."""

    lowered = text.casefold()
    matches: set[str] = set()
    if assigned_company_id:
        matches.add(assigned_company_id)
    for company in config.companies:
        terms = [company.name, *_ticker_terms(company.ticker)]
        if any(_contains_term(lowered, term) for term in terms if term):
            matches.add(company.id)
    return sorted(matches)


def source_tier_confidence(source_tier: str | None) -> str:
    tier = (source_tier or "").upper()
    if tier == "A":
        return "high"
    if "B" in tier:
        return "medium"
    return "low"


def _create_event_if_relevant(
    connection: sqlite3.Connection,
    document: CompanyDocument,
    *,
    run_id: str,
    changed: bool,
    previous_hash: str | None,
) -> int:
    if not _has_relevant_match(document):
        return 0

    source_document_id = _insert_source_document(connection, document)
    created = insert_event(
        connection,
        source_id=document.source_id,
        external_id=document.document_key,
        event_type=_event_type(document),
        field="content" if changed else "",
        old_value=previous_hash or "",
        new_value=document.content_hash,
        run_id=run_id,
        title=_event_title(document, changed=changed),
        what_changed=_what_changed(document, changed=changed, previous_hash=previous_hash),
        why_it_matters=_why_it_matters(document),
        confidence=source_tier_confidence(document.source_tier),
        severity=_severity(document),
        directness=_directness(document),
        stock_market_relevance=_stock_market_relevance(document),
        peptide_id=document.peptide_ids[0] if document.peptide_ids else None,
        source_document_id=source_document_id,
    )
    return int(created)


def _has_relevant_match(document: CompanyDocument) -> bool:
    if document.source_type == "watched_feed_item":
        # Feed items come from already-scoped feeds (e.g. patent search
        # feeds), so generic catalyst keywords alone are noise; require a
        # watch-term match.
        return bool(document.peptide_ids)
    return bool(document.peptide_ids or document.keyword_matches)


def _is_discovery(document: CompanyDocument) -> bool:
    """A filer not on the watchlist, found via full-text search — a new name."""

    return document.metadata.get("discovery") is True


def _event_type(document: CompanyDocument) -> str:
    if document.source_type == "sec_filing":
        if _is_discovery(document):
            # A company we don't track disclosing a target peptide for the
            # first time — the highest-value early signal in the system.
            return "new_company_peptide_disclosure"
        return "sec_filing_target_mention"
    if "commercial_launch" in document.keyword_matches:
        return "commercial_launch_claim"
    return "company_press_release_target_mention"


def _severity(document: CompanyDocument) -> str:
    if document.source_type == "sec_filing":
        if _is_discovery(document):
            return "high"  # new filer = candidate gem -> immediate review
        # A routine filing from a company we already track is not news; the
        # genuine catalysts (status changes, launches) come through other
        # event types. Keep known-company mentions in the digest.
        return "medium"
    if "clinical_asset" in document.keyword_matches and document.peptide_ids:
        return "high"
    if "licensing_or_acquisition" in document.keyword_matches and document.peptide_ids:
        return "high"
    # Commercial-launch claims from microcaps are often promotional; keep them
    # in the digest (medium) per the alert taxonomy.
    return "medium" if document.peptide_ids or document.keyword_matches else "low"


def _directness(document: CompanyDocument) -> str:
    company_tier = document.metadata.get("company_tier")
    if company_tier == 1 and document.peptide_ids:
        return "direct"
    if company_tier == 3:
        return "speculative"
    return "indirect"


def _event_title(document: CompanyDocument, *, changed: bool) -> str:
    action = "changed" if changed else "detected"
    company = document.company_name or document.company_key or "company source"
    label = document.filing_type or document.source_type.replace("_", " ")
    return f"{label} {action}: {company}"


def _what_changed(
    document: CompanyDocument,
    *,
    changed: bool,
    previous_hash: str | None,
) -> str:
    match_summary = []
    if document.peptide_ids:
        match_summary.append(f"peptide matches {', '.join(document.peptide_ids)}")
    if document.keyword_matches:
        match_summary.append(f"keyword matches {', '.join(document.keyword_matches)}")
    matches = "; ".join(match_summary) if match_summary else "no target terms"
    if changed and previous_hash:
        return (
            "Confirmed fact: a public company/news/filing source content hash changed "
            f"from {previous_hash} to {document.content_hash}; {matches}."
        )
    return f"Confirmed fact: a public company/news/filing source was detected; {matches}."


def _why_it_matters(document: CompanyDocument) -> str:
    return (
        "Confirmed fact: this event comes from a public source. "
        "Inference: matched terms may warrant manual follow-up on company exposure. "
        "Speculation: any market relevance is uncertain and requires review; company "
        "press releases and filings are not clinical proof or FDA approval."
    )


def _stock_market_relevance(document: CompanyDocument) -> str:
    message = "Possible market relevance only; This is not a buy/sell recommendation. Verify independently."
    if _is_microcap_or_otc(document):
        message += (
            " OTC/CSE/microcap context may carry liquidity, dilution, promotional, "
            "and regulatory risk."
        )
    return message


def _is_microcap_or_otc(document: CompanyDocument) -> bool:
    text = " ".join(
        str(value)
        for value in [
            document.source_id,
            document.ticker,
            document.exchange,
            document.metadata.get("public_private"),
            document.metadata.get("liquidity_risk"),
        ]
        if value
    ).casefold()
    return any(term in text for term in ["otc", "cse", "microcap", "liquidity_risk", "extreme"])


def _insert_document(connection: sqlite3.Connection, document: CompanyDocument) -> None:
    connection.execute(
        """
        INSERT INTO company_documents (
          document_key,
          source_id,
          source_type,
          url,
          title,
          company_key,
          company_name,
          ticker,
          exchange,
          filing_type,
          accession_number,
          filing_date,
          source_tier,
          content_hash,
          content_text,
          peptide_ids_json,
          matched_aliases_json,
          company_matches_json,
          keyword_matches_json,
          metadata_json,
          raw_sha256,
          parser_version
        )
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
        _document_values(document),
    )


def _update_document(connection: sqlite3.Connection, document: CompanyDocument) -> None:
    connection.execute(
        """
        UPDATE company_documents
        SET source_id = ?,
            source_type = ?,
            url = ?,
            title = ?,
            company_key = ?,
            company_name = ?,
            ticker = ?,
            exchange = ?,
            filing_type = ?,
            accession_number = ?,
            filing_date = ?,
            source_tier = ?,
            content_hash = ?,
            content_text = ?,
            peptide_ids_json = ?,
            matched_aliases_json = ?,
            company_matches_json = ?,
            keyword_matches_json = ?,
            metadata_json = ?,
            raw_sha256 = ?,
            parser_version = ?,
            last_seen_at = CURRENT_TIMESTAMP,
            updated_at = CURRENT_TIMESTAMP
        WHERE document_key = ?
        """,
        (*_document_values(document)[1:], document.document_key),
    )


def _touch_document(connection: sqlite3.Connection, document: CompanyDocument) -> None:
    connection.execute(
        """
        UPDATE company_documents
        SET last_seen_at = CURRENT_TIMESTAMP,
            peptide_ids_json = ?,
            matched_aliases_json = ?,
            company_matches_json = ?,
            keyword_matches_json = ?,
            raw_sha256 = ?,
            parser_version = ?
        WHERE document_key = ?
        """,
        (
            _json(document.peptide_ids),
            _json(document.matched_aliases),
            _json(document.company_matches),
            _json(document.keyword_matches),
            document.raw_sha256,
            document.parser_version,
            document.document_key,
        ),
    )


def _document_values(document: CompanyDocument) -> tuple[Any, ...]:
    return (
        document.document_key,
        document.source_id,
        document.source_type,
        document.url,
        document.title,
        document.company_key,
        document.company_name,
        document.ticker,
        document.exchange,
        document.filing_type,
        document.accession_number,
        document.filing_date,
        document.source_tier,
        document.content_hash,
        document.content_text,
        _json(document.peptide_ids),
        _json(document.matched_aliases),
        _json(document.company_matches),
        _json(document.keyword_matches),
        _json(document.metadata),
        document.raw_sha256,
        document.parser_version,
    )


def _insert_snapshot(connection: sqlite3.Connection, document: CompanyDocument) -> None:
    if document.raw_content is not None and document.raw_sha256:
        connection.execute(
            "INSERT OR IGNORE INTO raw_blobs (raw_sha256, content) VALUES (?, ?)",
            (document.raw_sha256, document.raw_content),
        )
    connection.execute(
        """
        INSERT OR IGNORE INTO company_document_snapshots (
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


def _insert_source_document(connection: sqlite3.Connection, document: CompanyDocument) -> int:
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
        VALUES (?, ?, ?, CURRENT_TIMESTAMP, ?, ?)
        """,
        (
            document.source_id,
            document.url,
            document.title,
            document.content_hash,
            document.source_tier,
        ),
    )
    return int(cursor.lastrowid)


def _existing_document(connection: sqlite3.Connection, document_key: str) -> sqlite3.Row | None:
    return connection.execute(
        "SELECT * FROM company_documents WHERE document_key = ?",
        (document_key,),
    ).fetchone()


def _row_to_document(row: sqlite3.Row) -> CompanyDocument:
    return CompanyDocument.model_validate(
        {
            "document_key": row["document_key"],
            "source_id": row["source_id"],
            "source_type": row["source_type"],
            "url": row["url"],
            "title": row["title"],
            "company_key": row["company_key"],
            "company_name": row["company_name"],
            "ticker": row["ticker"],
            "exchange": row["exchange"],
            "filing_type": row["filing_type"],
            "accession_number": row["accession_number"],
            "filing_date": row["filing_date"],
            "source_tier": row["source_tier"],
            "content_hash": row["content_hash"],
            "content_text": row["content_text"],
            "peptide_ids": json.loads(row["peptide_ids_json"]),
            "matched_aliases": json.loads(row["matched_aliases_json"]),
            "company_matches": json.loads(row["company_matches_json"]),
            "keyword_matches": json.loads(row["keyword_matches_json"]),
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


def _company_by_id(config: WatchConfig, company_id: str | None) -> CompanyConfig | None:
    if not company_id:
        return None
    return next((company for company in config.companies if company.id == company_id), None)


def _ticker_terms(ticker: str | None) -> list[str]:
    if not ticker:
        return []
    return [term for term in re.split(r"[^A-Za-z0-9]+", ticker) if term]


def _contains_term(lowered_text: str, term: str) -> bool:
    lowered_term = term.casefold().strip()
    if not lowered_term:
        return False
    if len(lowered_term) <= 5 and re.fullmatch(r"[a-z0-9]+", lowered_term):
        return re.search(rf"\b{re.escape(lowered_term)}\b", lowered_text) is not None
    return lowered_term in lowered_text


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
