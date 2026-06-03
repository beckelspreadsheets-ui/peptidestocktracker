from pathlib import Path

from peptide_watch.claims import (
    ClaimCreate,
    add_claim,
    export_claims,
    list_claims,
    seed_claims_from_markdown,
    update_claim_status,
)
from peptide_watch.config import UNVERIFIED_CLAIM_STATUS
from peptide_watch.database import init_db

ROOT = Path(__file__).resolve().parents[1]


def test_external_report_claims_are_stored_as_needs_verification(tmp_path) -> None:
    db_path = init_db(tmp_path / "watch.db")

    record, inserted = add_claim(
        db_path,
        ClaimCreate(
            claim_text="External report says a company will launch specific target peptides.",
            source_type="external_report",
            source_label="Kimi",
            status="confirmed_primary_source",
            target_status="confirmed_primary_source",
        ),
    )

    assert inserted is True
    assert record.status == UNVERIFIED_CLAIM_STATUS
    assert record.target_status == "confirmed_primary_source"
    assert record.needs_review is True


def test_seed_claims_to_verify_is_idempotent_and_does_not_promote_claims(tmp_path) -> None:
    db_path = init_db(tmp_path / "watch.db")
    seed_file = ROOT / "docs" / "CLAIMS_TO_VERIFY.md"

    first = seed_claims_from_markdown(db_path, seed_file)
    second = seed_claims_from_markdown(db_path, seed_file)
    claims = list_claims(db_path, limit=100)

    assert first.total == 14
    assert first.inserted == 14
    assert first.skipped == 0
    assert second.inserted == 0
    assert second.skipped == 14
    assert len(claims) == 14
    assert {claim.status for claim in claims} == {UNVERIFIED_CLAIM_STATUS}
    assert "confirmed_primary_source" in {claim.target_status for claim in claims}


def test_update_claim_status_clears_review_queue_for_resolved_claim(tmp_path) -> None:
    db_path = init_db(tmp_path / "watch.db")
    record, _ = add_claim(db_path, ClaimCreate(claim_text="Primary-source checked claim."))

    updated = update_claim_status(
        db_path,
        record.id,
        "confirmed_primary_source",
        reviewer_notes="Confirmed through primary source.",
    )

    assert updated.status == "confirmed_primary_source"
    assert updated.needs_review is False
    assert updated.last_checked_at is not None


def test_export_claims_supports_markdown_and_csv(tmp_path) -> None:
    db_path = init_db(tmp_path / "watch.db")
    add_claim(db_path, ClaimCreate(claim_text="Export me", source_label="unit-test"))
    claims = list_claims(db_path)

    markdown = export_claims(claims, "markdown")
    csv_output = export_claims(claims, "csv")

    assert "| id | status |" in markdown
    assert "Export me" in markdown
    assert "id,status,target_status" in csv_output
    assert "Export me" in csv_output
