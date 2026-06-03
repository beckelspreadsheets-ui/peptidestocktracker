"""Claim registry CRUD, seeding, and export helpers."""

from __future__ import annotations

import csv
import hashlib
import io
import sqlite3
from pathlib import Path
from typing import Literal

from pydantic import BaseModel, ConfigDict, field_validator

from peptide_watch.config import UNVERIFIED_CLAIM_STATUS
from peptide_watch.database import init_db

CLAIM_STATUSES = frozenset(
    {
        "confirmed_primary_source",
        "confirmed_secondary_source",
        UNVERIFIED_CLAIM_STATUS,
        "contradicted",
        "stale",
        "excluded",
    }
)

EXTERNAL_REPORT_SOURCE_TYPES = frozenset(
    {
        "ai_report",
        "external_report",
        "research_report",
        "third_party_report",
        "trial_mirror",
    }
)

CLAIM_COLUMNS = (
    "id",
    "claim_hash",
    "claim_text",
    "company_name",
    "peptide_id",
    "claim_category",
    "source_type",
    "source_label",
    "source_url",
    "target_status",
    "status",
    "confidence",
    "priority",
    "verification_path",
    "evidence_excerpt",
    "reviewer_notes",
    "first_seen_at",
    "last_checked_at",
    "needs_review",
    "imported_from",
    "created_at",
    "updated_at",
)

EXPORT_COLUMNS = (
    "id",
    "status",
    "target_status",
    "needs_review",
    "priority",
    "confidence",
    "company_name",
    "peptide_id",
    "claim_category",
    "claim_text",
    "source_type",
    "source_label",
    "source_url",
    "verification_path",
    "reviewer_notes",
)


class ClaimCreate(BaseModel):
    """Validated claim payload for insertion into the registry."""

    model_config = ConfigDict(extra="forbid")

    claim_text: str
    company_name: str | None = None
    peptide_id: str | None = None
    claim_category: str | None = "external_report_claim"
    source_type: str = "external_report"
    source_label: str | None = None
    source_url: str | None = None
    target_status: str | None = None
    status: str = UNVERIFIED_CLAIM_STATUS
    confidence: str = "low"
    priority: str | None = None
    verification_path: str | None = None
    evidence_excerpt: str | None = None
    reviewer_notes: str | None = None
    needs_review: bool = True
    imported_from: str | None = None

    @field_validator(
        "claim_text",
        "company_name",
        "peptide_id",
        "claim_category",
        "source_type",
        "source_label",
        "source_url",
        "target_status",
        "status",
        "confidence",
        "priority",
        "verification_path",
        "evidence_excerpt",
        "reviewer_notes",
        "imported_from",
        mode="before",
    )
    @classmethod
    def strip_text(cls, value: str | None) -> str | None:
        if value is None:
            return None
        value = str(value).strip()
        return value or None

    @field_validator("claim_text")
    @classmethod
    def require_claim_text(cls, value: str) -> str:
        if not value:
            raise ValueError("claim_text must not be blank")
        return value

    @field_validator("status")
    @classmethod
    def validate_status(cls, value: str) -> str:
        if value not in CLAIM_STATUSES:
            allowed = ", ".join(sorted(CLAIM_STATUSES))
            raise ValueError(f"status must be one of: {allowed}")
        return value


class ClaimRecord(ClaimCreate):
    """Claim row returned from SQLite."""

    id: int
    claim_hash: str | None
    first_seen_at: str | None = None
    last_checked_at: str | None = None
    created_at: str
    updated_at: str | None = None


class SeedResult(BaseModel):
    """Summary for seeded claim imports."""

    total: int
    inserted: int
    skipped: int


def add_claim(db_path: str | Path, claim: ClaimCreate) -> tuple[ClaimRecord, bool]:
    """Insert a claim, returning the record and whether it was newly inserted."""

    init_db(db_path)
    normalized = _normalize_claim(claim)
    claim_hash = _claim_hash(normalized)

    with _connect(db_path) as connection:
        existing = _get_claim_by_hash(connection, claim_hash)
        if existing is not None:
            return existing, False

        connection.execute(
            """
            INSERT INTO claims (
              claim_hash,
              claim_text,
              company_name,
              peptide_id,
              claim_category,
              source_type,
              source_label,
              source_url,
              target_status,
              status,
              confidence,
              priority,
              verification_path,
              evidence_excerpt,
              reviewer_notes,
              needs_review,
              imported_from
            )
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                claim_hash,
                normalized.claim_text,
                normalized.company_name,
                normalized.peptide_id,
                normalized.claim_category,
                normalized.source_type,
                normalized.source_label,
                normalized.source_url,
                normalized.target_status,
                normalized.status,
                normalized.confidence,
                normalized.priority,
                normalized.verification_path,
                normalized.evidence_excerpt,
                normalized.reviewer_notes,
                int(normalized.needs_review),
                normalized.imported_from,
            ),
        )
        connection.commit()
        record = _get_claim_by_hash(connection, claim_hash)
        if record is None:
            raise RuntimeError("inserted claim could not be retrieved")
        return record, True


def get_claim(db_path: str | Path, claim_id: int) -> ClaimRecord | None:
    """Fetch one claim by id."""

    init_db(db_path)
    with _connect(db_path) as connection:
        row = connection.execute(
            f"SELECT {', '.join(CLAIM_COLUMNS)} FROM claims WHERE id = ?",
            (claim_id,),
        ).fetchone()
    return _row_to_claim(row) if row else None


def list_claims(
    db_path: str | Path,
    *,
    status: str | None = None,
    needs_review: bool | None = None,
    limit: int = 100,
) -> list[ClaimRecord]:
    """List claims with optional status and review-queue filters."""

    init_db(db_path)
    if status is not None:
        _validate_status(status)
    if limit < 1:
        raise ValueError("limit must be at least 1")

    filters: list[str] = []
    params: list[str | int] = []
    if status is not None:
        filters.append("status = ?")
        params.append(status)
    if needs_review is not None:
        filters.append("needs_review = ?")
        params.append(int(needs_review))

    where = f"WHERE {' AND '.join(filters)}" if filters else ""
    query = f"""
        SELECT {', '.join(CLAIM_COLUMNS)}
        FROM claims
        {where}
        ORDER BY id ASC
        LIMIT ?
    """
    params.append(limit)

    with _connect(db_path) as connection:
        rows = connection.execute(query, params).fetchall()
    return [_row_to_claim(row) for row in rows]


def update_claim_status(
    db_path: str | Path,
    claim_id: int,
    status: str,
    *,
    reviewer_notes: str | None = None,
) -> ClaimRecord:
    """Update a claim verification status after review."""

    init_db(db_path)
    _validate_status(status)
    needs_review = status == UNVERIFIED_CLAIM_STATUS

    with _connect(db_path) as connection:
        existing = get_claim(db_path, claim_id)
        if existing is None:
            raise ValueError(f"claim not found: {claim_id}")
        connection.execute(
            """
            UPDATE claims
            SET status = ?,
                reviewer_notes = COALESCE(?, reviewer_notes),
                needs_review = ?,
                last_checked_at = CURRENT_TIMESTAMP,
                updated_at = CURRENT_TIMESTAMP
            WHERE id = ?
            """,
            (status, _blank_to_none(reviewer_notes), int(needs_review), claim_id),
        )
        connection.commit()

    updated = get_claim(db_path, claim_id)
    if updated is None:
        raise RuntimeError("updated claim could not be retrieved")
    return updated


def seed_claims_from_markdown(
    db_path: str | Path,
    markdown_path: str | Path = "docs/CLAIMS_TO_VERIFY.md",
) -> SeedResult:
    """Seed claims from the controlled markdown table in docs/CLAIMS_TO_VERIFY.md."""

    path = Path(markdown_path)
    claims = parse_claims_to_verify(path)
    inserted = 0
    skipped = 0
    for claim in claims:
        _, was_inserted = add_claim(db_path, claim)
        inserted += int(was_inserted)
        skipped += int(not was_inserted)
    return SeedResult(total=len(claims), inserted=inserted, skipped=skipped)


def parse_claims_to_verify(markdown_path: str | Path) -> list[ClaimCreate]:
    """Parse claim seed rows from docs/CLAIMS_TO_VERIFY.md."""

    path = Path(markdown_path)
    if not path.exists():
        raise FileNotFoundError(f"claim seed file not found: {path}")

    claims: list[ClaimCreate] = []
    for line in path.read_text(encoding="utf-8").splitlines():
        cells = _split_markdown_table_row(line)
        if not cells or cells[0] in {"Claim", "---"} or cells[0].startswith("---"):
            continue
        if len(cells) != 5:
            continue
        claim_text, target_status, priority, verification_path, notes = cells
        claims.append(
            ClaimCreate(
                claim_text=claim_text,
                source_type="external_report",
                source_label=path.as_posix(),
                target_status=target_status,
                status=UNVERIFIED_CLAIM_STATUS,
                confidence=_confidence_from_priority(priority),
                priority=priority,
                verification_path=verification_path,
                reviewer_notes=notes,
                needs_review=True,
                imported_from=path.as_posix(),
            )
        )
    return claims


def export_claims(
    claims: list[ClaimRecord],
    output_format: Literal["csv", "markdown"] = "markdown",
) -> str:
    """Export claim records as markdown or CSV text."""

    if output_format == "markdown":
        return export_claims_markdown(claims)
    if output_format == "csv":
        return export_claims_csv(claims)
    raise ValueError("output_format must be 'markdown' or 'csv'")


def export_claims_markdown(claims: list[ClaimRecord]) -> str:
    """Export claim records as a markdown table."""

    header = "| " + " | ".join(EXPORT_COLUMNS) + " |"
    separator = "| " + " | ".join("---" for _ in EXPORT_COLUMNS) + " |"
    rows = [
        "| " + " | ".join(_markdown_cell(getattr(claim, column)) for column in EXPORT_COLUMNS) + " |"
        for claim in claims
    ]
    return "\n".join([header, separator, *rows])


def export_claims_csv(claims: list[ClaimRecord]) -> str:
    """Export claim records as CSV text."""

    output = io.StringIO()
    writer = csv.DictWriter(output, fieldnames=list(EXPORT_COLUMNS))
    writer.writeheader()
    for claim in claims:
        writer.writerow({column: getattr(claim, column) for column in EXPORT_COLUMNS})
    return output.getvalue()


def _normalize_claim(claim: ClaimCreate) -> ClaimCreate:
    status = claim.status
    needs_review = claim.needs_review
    if claim.source_type in EXTERNAL_REPORT_SOURCE_TYPES:
        status = UNVERIFIED_CLAIM_STATUS
        needs_review = True
    return claim.model_copy(update={"status": status, "needs_review": needs_review})


def _claim_hash(claim: ClaimCreate) -> str:
    components = (
        claim.claim_text.casefold(),
        claim.source_label or "",
        claim.source_url or "",
        claim.imported_from or "",
    )
    payload = "\0".join(components).encode("utf-8")
    return hashlib.sha256(payload).hexdigest()


def _get_claim_by_hash(connection: sqlite3.Connection, claim_hash: str) -> ClaimRecord | None:
    row = connection.execute(
        f"SELECT {', '.join(CLAIM_COLUMNS)} FROM claims WHERE claim_hash = ?",
        (claim_hash,),
    ).fetchone()
    return _row_to_claim(row) if row else None


def _row_to_claim(row: sqlite3.Row) -> ClaimRecord:
    data = dict(row)
    data["needs_review"] = bool(data["needs_review"])
    return ClaimRecord.model_validate(data)


def _connect(db_path: str | Path) -> sqlite3.Connection:
    connection = sqlite3.connect(db_path)
    connection.row_factory = sqlite3.Row
    return connection


def _validate_status(status: str) -> None:
    if status not in CLAIM_STATUSES:
        allowed = ", ".join(sorted(CLAIM_STATUSES))
        raise ValueError(f"status must be one of: {allowed}")


def _split_markdown_table_row(line: str) -> list[str]:
    stripped = line.strip()
    if not stripped.startswith("|") or not stripped.endswith("|"):
        return []
    return [cell.strip() for cell in stripped.strip("|").split("|")]


def _confidence_from_priority(priority: str) -> str:
    normalized = priority.strip().lower()
    if normalized == "critical":
        return "high"
    if normalized == "high":
        return "medium"
    return "low"


def _markdown_cell(value: object) -> str:
    if value is None:
        return ""
    return str(value).replace("|", "\\|").replace("\n", " ")


def _blank_to_none(value: str | None) -> str | None:
    if value is None:
        return None
    value = value.strip()
    return value or None
