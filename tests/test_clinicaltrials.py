import sqlite3
from pathlib import Path

from typer.testing import CliRunner

from peptide_watch.cli import app
from peptide_watch.config import load_config
from peptide_watch.database import init_db
from peptide_watch.sources.clinicaltrials import (
    ClinicalTrialRecord,
    export_trials_markdown,
    list_trials,
    normalize_study,
    scan_clinicaltrials,
    store_trial_record,
)

ROOT = Path(__file__).resolve().parents[1]


class FakeClinicalTrialsClient:
    def __init__(self, study: dict) -> None:
        self.study = study

    def get_study(self, nct_id: str) -> dict:
        return self.study

    def search_studies(self, term: str, *, page_size: int = 25, max_pages: int = 1) -> list[dict]:
        return [self.study]


def test_normalize_study_extracts_core_trial_fields_and_alias_matches() -> None:
    config = load_config(ROOT / "config")

    record = normalize_study(_study_payload(), query_terms=["BPC-157"], config=config)

    assert record.nct_id == "NCT07437547"
    assert record.overall_status == "RECRUITING"
    assert record.phase == "PHASE2"
    assert record.enrollment_count == 120
    assert record.sponsor_name == "Hudson Biotech"
    assert record.primary_completion_date == "2027-02-14"
    assert record.has_results is False
    assert "Pentadecapeptide BPC 157" in record.interventions
    assert "bpc_157" in record.peptide_ids
    assert "BPC-157" in record.matched_aliases
    assert len(record.record_hash) == 64


def test_store_trial_record_creates_snapshot_and_new_trial_event(tmp_path) -> None:
    db_path = init_db(tmp_path / "watch.db")
    record = normalize_study(_study_payload(), query_terms=["NCT07437547"])

    result = store_trial_record(db_path, record)

    assert result.inserted is True
    assert result.changed is False
    assert result.events_created == 1
    with sqlite3.connect(db_path) as connection:
        assert connection.execute("SELECT COUNT(*) FROM clinical_trials").fetchone()[0] == 1
        assert connection.execute("SELECT COUNT(*) FROM clinical_trial_snapshots").fetchone()[0] == 1
        event = connection.execute("SELECT event_type, severity FROM events").fetchone()
    assert event == ("new_recruiting_trial", "critical")


def test_store_trial_record_detects_status_change(tmp_path) -> None:
    db_path = init_db(tmp_path / "watch.db")
    first = normalize_study(_study_payload(status="NOT_YET_RECRUITING"))
    second = normalize_study(_study_payload(status="RECRUITING"))

    store_trial_record(db_path, first)
    result = store_trial_record(db_path, second)

    assert result.inserted is False
    assert result.changed is True
    assert result.events_created == 1
    with sqlite3.connect(db_path) as connection:
        status = connection.execute(
            "SELECT overall_status FROM clinical_trials WHERE nct_id = 'NCT07437547'"
        ).fetchone()[0]
        event_types = [
            row[0]
            for row in connection.execute("SELECT event_type FROM events ORDER BY id").fetchall()
        ]
    assert status == "RECRUITING"
    assert event_types == ["clinical_trial_record_detected", "trial_status_change"]


def test_scan_clinicaltrials_stores_explicit_nct_without_alias_search(tmp_path) -> None:
    db_path = init_db(tmp_path / "watch.db")

    result = scan_clinicaltrials(
        db_path,
        config_dir=ROOT / "config",
        client=FakeClinicalTrialsClient(_study_payload()),
        nct_ids=["NCT07437547"],
        include_known_ncts=False,
        include_alias_queries=False,
    )

    assert result.fetched == 1
    assert result.stored == 1
    assert result.inserted == 1
    assert result.searched_nct_ids == ["NCT07437547"]


def test_list_and_export_trials_markdown(tmp_path) -> None:
    db_path = init_db(tmp_path / "watch.db")
    store_trial_record(db_path, normalize_study(_study_payload(), query_terms=["BPC-157"]))

    records = list_trials(db_path)
    output = export_trials_markdown(records)

    assert len(records) == 1
    assert isinstance(records[0], ClinicalTrialRecord)
    assert "NCT07437547" in output
    assert "Hudson Biotech" in output


def test_clinicaltrials_list_cli(tmp_path) -> None:
    db_path = init_db(tmp_path / "watch.db")
    store_trial_record(db_path, normalize_study(_study_payload(), query_terms=["BPC-157"]))

    result = CliRunner().invoke(app, ["clinicaltrials", "list", "--db", str(db_path)])

    assert result.exit_code == 0, result.output
    assert "NCT07437547" in result.output
    assert "RECRUITING" in result.output


def _study_payload(
    *,
    status: str = "RECRUITING",
    phase: str = "PHASE2",
    enrollment: int = 120,
    has_results: bool = False,
) -> dict:
    return {
        "protocolSection": {
            "identificationModule": {
                "nctId": "NCT07437547",
                "briefTitle": "BPC 157 for Acute Hamstring Muscle Strain Repair",
                "officialTitle": "Phase 2 Trial of Pentadecapeptide BPC 157",
            },
            "statusModule": {
                "overallStatus": status,
                "primaryCompletionDateStruct": {"date": "2027-02-14", "type": "ESTIMATED"},
                "completionDateStruct": {"date": "2028-02-17", "type": "ESTIMATED"},
                "lastUpdatePostDateStruct": {"date": "2026-02-27", "type": "ACTUAL"},
            },
            "sponsorCollaboratorsModule": {
                "leadSponsor": {"name": "Hudson Biotech", "class": "INDUSTRY"}
            },
            "conditionsModule": {
                "conditions": ["Hamstring Muscle Strain"],
                "keywords": ["BPC 157", "BPC-157"],
            },
            "designModule": {
                "phases": [phase],
                "enrollmentInfo": {"count": enrollment, "type": "ESTIMATED"},
            },
            "armsInterventionsModule": {
                "interventions": [
                    {
                        "type": "DRUG",
                        "name": "Pentadecapeptide BPC 157",
                        "otherNames": ["BPC-157"],
                    }
                ]
            },
            "outcomesModule": {
                "primaryOutcomes": [
                    {"measure": "Time to return to unrestricted sport participation"}
                ]
            },
            "contactsLocationsModule": {
                "locations": [
                    {
                        "facility": "Peking University Shenzhen Hospital",
                        "city": "Shenzhen",
                        "state": "Guangdong",
                        "country": "China",
                        "status": "RECRUITING",
                    }
                ]
            },
        },
        "hasResults": has_results,
    }
