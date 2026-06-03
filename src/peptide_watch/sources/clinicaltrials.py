"""ClinicalTrials.gov API v2 adapter."""

from __future__ import annotations

import hashlib
import json
import re
import sqlite3
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Iterable
from urllib.parse import urlencode
from urllib.request import Request, urlopen

from pydantic import BaseModel, ConfigDict, Field, field_validator

from peptide_watch.config import WatchConfig, load_config
from peptide_watch.database import init_db

CLINICALTRIALS_BASE_URL = "https://clinicaltrials.gov/api/v2"
CLINICALTRIALS_SOURCE_ID = "clinicaltrials"
NCT_RE = re.compile(r"\bNCT\d{8}\b", re.IGNORECASE)


class ClinicalTrialRecord(BaseModel):
    """Normalized ClinicalTrials.gov study record."""

    model_config = ConfigDict(extra="forbid")

    nct_id: str
    source_url: str
    brief_title: str | None = None
    official_title: str | None = None
    overall_status: str | None = None
    phase: str | None = None
    phases: list[str] = Field(default_factory=list)
    enrollment_count: int | None = None
    enrollment_type: str | None = None
    sponsor_name: str | None = None
    primary_completion_date: str | None = None
    completion_date: str | None = None
    last_update_post_date: str | None = None
    has_results: bool = False
    interventions: list[str] = Field(default_factory=list)
    conditions: list[str] = Field(default_factory=list)
    primary_outcomes: list[str] = Field(default_factory=list)
    locations: list[str] = Field(default_factory=list)
    peptide_ids: list[str] = Field(default_factory=list)
    matched_aliases: list[str] = Field(default_factory=list)
    query_terms: list[str] = Field(default_factory=list)
    raw: dict[str, Any]
    record_hash: str

    @field_validator("nct_id")
    @classmethod
    def normalize_nct_id(cls, value: str) -> str:
        value = value.strip().upper()
        if not NCT_RE.fullmatch(value):
            raise ValueError("nct_id must look like NCT followed by 8 digits")
        return value


class StoreResult(BaseModel):
    """Database persistence summary for one normalized trial."""

    nct_id: str
    inserted: bool
    changed: bool
    events_created: int


class ScanResult(BaseModel):
    """ClinicalTrials.gov scan summary."""

    fetched: int
    stored: int
    inserted: int
    changed: int
    events_created: int
    searched_terms: list[str]
    searched_nct_ids: list[str]


@dataclass(frozen=True)
class ClinicalTrialsClient:
    """Small ClinicalTrials.gov API v2 client with explicit rate limiting."""

    base_url: str = CLINICALTRIALS_BASE_URL
    timeout: float = 20.0
    rate_limit_seconds: float = 0.2
    user_agent: str = "peptide-watch/0.1 public-source research"

    def get_version(self) -> dict[str, Any]:
        return self._get_json("/version")

    def get_study(self, nct_id: str) -> dict[str, Any]:
        return self._get_json(f"/studies/{nct_id.upper()}")

    def search_studies(
        self,
        term: str,
        *,
        page_size: int = 25,
        max_pages: int = 1,
    ) -> list[dict[str, Any]]:
        if page_size < 1 or page_size > 1000:
            raise ValueError("page_size must be between 1 and 1000")
        if max_pages < 1:
            raise ValueError("max_pages must be at least 1")

        studies: list[dict[str, Any]] = []
        page_token: str | None = None
        for _ in range(max_pages):
            params: dict[str, str | int] = {
                "query.term": term,
                "pageSize": page_size,
                "format": "json",
            }
            if page_token:
                params["pageToken"] = page_token
            payload = self._get_json("/studies", params=params)
            studies.extend(payload.get("studies", []))
            page_token = payload.get("nextPageToken")
            if not page_token:
                break
        return studies

    def _get_json(self, path: str, params: dict[str, str | int] | None = None) -> dict[str, Any]:
        url = f"{self.base_url}{path}"
        if params:
            url = f"{url}?{urlencode(params)}"
        request = Request(
            url,
            headers={
                "Accept": "application/json",
                "User-Agent": self.user_agent,
            },
        )
        try:
            with urlopen(request, timeout=self.timeout) as response:
                return json.loads(response.read().decode("utf-8"))
        finally:
            if self.rate_limit_seconds > 0:
                time.sleep(self.rate_limit_seconds)


def normalize_study(
    study: dict[str, Any],
    *,
    query_terms: Iterable[str] = (),
    config: WatchConfig | None = None,
) -> ClinicalTrialRecord:
    """Normalize an API v2 study payload into a stable record."""

    protocol = study.get("protocolSection", {})
    identification = protocol.get("identificationModule", {})
    status = protocol.get("statusModule", {})
    sponsor = protocol.get("sponsorCollaboratorsModule", {})
    design = protocol.get("designModule", {})
    interventions_module = protocol.get("armsInterventionsModule", {})
    conditions_module = protocol.get("conditionsModule", {})
    outcomes = protocol.get("outcomesModule", {})
    locations_module = protocol.get("contactsLocationsModule", {})

    nct_id = str(identification["nctId"]).upper()
    phases = _strings(design.get("phases", []))
    interventions = _intervention_names(interventions_module.get("interventions", []))
    primary_outcomes = _outcome_measures(outcomes.get("primaryOutcomes", []))
    locations = _locations(locations_module.get("locations", []))
    match_text = _trial_match_text(study)
    peptide_ids, matched_aliases = _match_peptide_aliases(match_text, config)

    normalized = {
        "nct_id": nct_id,
        "source_url": f"https://clinicaltrials.gov/study/{nct_id}",
        "brief_title": identification.get("briefTitle"),
        "official_title": identification.get("officialTitle"),
        "overall_status": status.get("overallStatus"),
        "phase": ", ".join(phases) if phases else None,
        "phases": phases,
        "enrollment_count": _int_or_none(design.get("enrollmentInfo", {}).get("count")),
        "enrollment_type": design.get("enrollmentInfo", {}).get("type"),
        "sponsor_name": sponsor.get("leadSponsor", {}).get("name"),
        "primary_completion_date": _date_value(status.get("primaryCompletionDateStruct")),
        "completion_date": _date_value(status.get("completionDateStruct")),
        "last_update_post_date": _date_value(status.get("lastUpdatePostDateStruct")),
        "has_results": bool(study.get("hasResults", False)),
        "interventions": interventions,
        "conditions": _strings(conditions_module.get("conditions", [])),
        "primary_outcomes": primary_outcomes,
        "locations": locations,
        "peptide_ids": peptide_ids,
        "matched_aliases": matched_aliases,
        "query_terms": sorted(set(query_terms)),
        "raw": study,
    }
    normalized["record_hash"] = _hash_payload(
        {
            key: value
            for key, value in normalized.items()
            if key not in {"query_terms", "raw", "record_hash"}
        }
    )
    return ClinicalTrialRecord.model_validate(normalized)


def scan_clinicaltrials(
    db_path: str | Path,
    *,
    config_dir: str | Path = "config",
    client: ClinicalTrialsClient | None = None,
    nct_ids: Iterable[str] = (),
    query_terms: Iterable[str] = (),
    include_known_ncts: bool = True,
    include_alias_queries: bool = True,
    page_size: int = 25,
    max_pages: int = 1,
) -> ScanResult:
    """Scan ClinicalTrials.gov for configured aliases and known NCT IDs."""

    config = load_config(config_dir)
    api_client = client or ClinicalTrialsClient()
    terms = sorted(set(query_terms) | (_alias_query_terms(config) if include_alias_queries else set()))
    known_ncts = sorted(
        {nct.upper() for nct in nct_ids}
        | (_known_nct_ids(config) if include_known_ncts else set())
    )

    fetched = 0
    stored = 0
    inserted = 0
    changed = 0
    events_created = 0
    seen_ncts: set[str] = set()

    for nct_id in known_ncts:
        study = api_client.get_study(nct_id)
        fetched += 1
        record = normalize_study(study, query_terms=[nct_id], config=config)
        result = store_trial_record(db_path, record)
        seen_ncts.add(record.nct_id)
        stored += 1
        inserted += int(result.inserted)
        changed += int(result.changed)
        events_created += result.events_created

    for term in terms:
        for study in api_client.search_studies(term, page_size=page_size, max_pages=max_pages):
            fetched += 1
            record = normalize_study(study, query_terms=[term], config=config)
            if record.nct_id in seen_ncts:
                continue
            result = store_trial_record(db_path, record)
            seen_ncts.add(record.nct_id)
            stored += 1
            inserted += int(result.inserted)
            changed += int(result.changed)
            events_created += result.events_created

    return ScanResult(
        fetched=fetched,
        stored=stored,
        inserted=inserted,
        changed=changed,
        events_created=events_created,
        searched_terms=terms,
        searched_nct_ids=known_ncts,
    )


def store_trial_record(db_path: str | Path, record: ClinicalTrialRecord) -> StoreResult:
    """Upsert a normalized trial record and emit durable change events."""

    init_db(db_path)
    with _connect(db_path) as connection:
        existing = _existing_trial(connection, record.nct_id)
        source_document_id = _insert_source_document(connection, record)

        if existing is None:
            _insert_trial(connection, record)
            _insert_snapshot(connection, record)
            _create_event(
                connection,
                record,
                source_document_id,
                event_type="new_recruiting_trial"
                if record.overall_status == "RECRUITING"
                else "clinical_trial_record_detected",
                title=f"ClinicalTrials.gov record detected: {record.nct_id}",
                what_changed=(
                    f"Confirmed fact: official ClinicalTrials.gov record {record.nct_id} "
                    f"was detected with status {record.overall_status or 'unknown'}."
                ),
                severity="critical" if record.overall_status == "RECRUITING" else "high",
            )
            connection.commit()
            return StoreResult(nct_id=record.nct_id, inserted=True, changed=False, events_created=1)

        _insert_snapshot(connection, record)
        if existing["record_hash"] == record.record_hash:
            _merge_last_seen(connection, record)
            connection.commit()
            return StoreResult(nct_id=record.nct_id, inserted=False, changed=False, events_created=0)

        events = _detect_change_events(connection, existing, record, source_document_id)
        _update_trial(connection, record)
        connection.commit()
        return StoreResult(
            nct_id=record.nct_id,
            inserted=False,
            changed=True,
            events_created=events,
        )


def list_trials(db_path: str | Path, *, limit: int = 100) -> list[ClinicalTrialRecord]:
    """Return stored trial records ordered by last seen timestamp."""

    init_db(db_path)
    if limit < 1:
        raise ValueError("limit must be at least 1")

    with _connect(db_path) as connection:
        rows = connection.execute(
            """
            SELECT *
            FROM clinical_trials
            ORDER BY last_seen_at DESC, nct_id ASC
            LIMIT ?
            """,
            (limit,),
        ).fetchall()
    return [_row_to_record(row) for row in rows]


def export_trials_markdown(records: list[ClinicalTrialRecord]) -> str:
    """Export stored trial records as a concise markdown table."""

    columns = [
        "nct_id",
        "overall_status",
        "phase",
        "sponsor_name",
        "enrollment_count",
        "primary_completion_date",
        "has_results",
        "peptide_ids",
        "brief_title",
        "source_url",
    ]
    header = "| " + " | ".join(columns) + " |"
    separator = "| " + " | ".join("---" for _ in columns) + " |"
    rows = []
    for record in records:
        values = []
        for column in columns:
            value = getattr(record, column)
            if isinstance(value, list):
                value = ", ".join(value)
            values.append(_markdown_cell(value))
        rows.append("| " + " | ".join(values) + " |")
    return "\n".join([header, separator, *rows])


def _detect_change_events(
    connection: sqlite3.Connection,
    existing: sqlite3.Row,
    record: ClinicalTrialRecord,
    source_document_id: int,
) -> int:
    checks = [
        ("overall_status", "trial_status_change", "high"),
        ("phase", "trial_phase_change", "high"),
        ("enrollment_count", "trial_enrollment_change", "medium"),
        ("primary_completion_date", "trial_primary_completion_date_change", "medium"),
        ("last_update_post_date", "trial_last_update_post_date_change", "medium"),
        ("has_results", "trial_results_posted", "high"),
    ]
    events_created = 0
    for column, event_type, severity in checks:
        old_value = existing[column]
        new_value = getattr(record, column)
        if column == "has_results":
            old_value = bool(old_value)
            new_value = bool(new_value)
        if old_value == new_value:
            continue
        _create_event(
            connection,
            record,
            source_document_id,
            event_type=event_type,
            title=f"ClinicalTrials.gov {column.replace('_', ' ')} changed: {record.nct_id}",
            what_changed=f"Confirmed fact: {column} changed from {old_value!r} to {new_value!r}.",
            severity=severity,
        )
        events_created += 1
    return events_created


def _insert_trial(connection: sqlite3.Connection, record: ClinicalTrialRecord) -> None:
    connection.execute(
        """
        INSERT INTO clinical_trials (
          nct_id,
          source_url,
          brief_title,
          official_title,
          overall_status,
          phase,
          phases_json,
          enrollment_count,
          enrollment_type,
          sponsor_name,
          primary_completion_date,
          completion_date,
          last_update_post_date,
          has_results,
          interventions_json,
          conditions_json,
          primary_outcomes_json,
          locations_json,
          peptide_ids_json,
          matched_aliases_json,
          query_terms_json,
          record_hash,
          raw_json
        )
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
        _trial_values(record),
    )


def _update_trial(connection: sqlite3.Connection, record: ClinicalTrialRecord) -> None:
    connection.execute(
        """
        UPDATE clinical_trials
        SET source_url = ?,
            brief_title = ?,
            official_title = ?,
            overall_status = ?,
            phase = ?,
            phases_json = ?,
            enrollment_count = ?,
            enrollment_type = ?,
            sponsor_name = ?,
            primary_completion_date = ?,
            completion_date = ?,
            last_update_post_date = ?,
            has_results = ?,
            interventions_json = ?,
            conditions_json = ?,
            primary_outcomes_json = ?,
            locations_json = ?,
            peptide_ids_json = ?,
            matched_aliases_json = ?,
            query_terms_json = ?,
            record_hash = ?,
            raw_json = ?,
            last_seen_at = CURRENT_TIMESTAMP,
            updated_at = CURRENT_TIMESTAMP
        WHERE nct_id = ?
        """,
        (*_trial_values(record)[1:], record.nct_id),
    )


def _merge_last_seen(connection: sqlite3.Connection, record: ClinicalTrialRecord) -> None:
    connection.execute(
        """
        UPDATE clinical_trials
        SET query_terms_json = ?,
            peptide_ids_json = ?,
            matched_aliases_json = ?,
            last_seen_at = CURRENT_TIMESTAMP
        WHERE nct_id = ?
        """,
        (
            _json(record.query_terms),
            _json(record.peptide_ids),
            _json(record.matched_aliases),
            record.nct_id,
        ),
    )


def _trial_values(record: ClinicalTrialRecord) -> tuple[Any, ...]:
    return (
        record.nct_id,
        record.source_url,
        record.brief_title,
        record.official_title,
        record.overall_status,
        record.phase,
        _json(record.phases),
        record.enrollment_count,
        record.enrollment_type,
        record.sponsor_name,
        record.primary_completion_date,
        record.completion_date,
        record.last_update_post_date,
        int(record.has_results),
        _json(record.interventions),
        _json(record.conditions),
        _json(record.primary_outcomes),
        _json(record.locations),
        _json(record.peptide_ids),
        _json(record.matched_aliases),
        _json(record.query_terms),
        record.record_hash,
        _json(record.raw),
    )


def _insert_source_document(connection: sqlite3.Connection, record: ClinicalTrialRecord) -> int:
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
            CLINICALTRIALS_SOURCE_ID,
            record.source_url,
            record.brief_title,
            record.record_hash,
            "A",
        ),
    )
    return int(cursor.lastrowid)


def _insert_snapshot(connection: sqlite3.Connection, record: ClinicalTrialRecord) -> None:
    connection.execute(
        """
        INSERT OR IGNORE INTO clinical_trial_snapshots (
          nct_id,
          record_hash,
          source_url,
          raw_json
        )
        VALUES (?, ?, ?, ?)
        """,
        (record.nct_id, record.record_hash, record.source_url, _json(record.raw)),
    )


def _create_event(
    connection: sqlite3.Connection,
    record: ClinicalTrialRecord,
    source_document_id: int,
    *,
    event_type: str,
    title: str,
    what_changed: str,
    severity: str,
) -> None:
    peptide_id = record.peptide_ids[0] if record.peptide_ids else None
    connection.execute(
        """
        INSERT INTO events (
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
          needs_review
        )
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 1)
        """,
        (
            event_type,
            peptide_id,
            source_document_id,
            title,
            what_changed,
            (
                "Confirmed fact: ClinicalTrials.gov is the official public registry source. "
                "Inference: changes may warrant follow-up research. "
                "Speculation: any market relevance is possible only and requires review."
            ),
            "high",
            severity,
            "direct",
            "Possible market relevance only; this is not a buy/sell recommendation.",
        ),
    )


def _existing_trial(connection: sqlite3.Connection, nct_id: str) -> sqlite3.Row | None:
    return connection.execute(
        "SELECT * FROM clinical_trials WHERE nct_id = ?",
        (nct_id,),
    ).fetchone()


def _row_to_record(row: sqlite3.Row) -> ClinicalTrialRecord:
    return ClinicalTrialRecord.model_validate(
        {
            "nct_id": row["nct_id"],
            "source_url": row["source_url"],
            "brief_title": row["brief_title"],
            "official_title": row["official_title"],
            "overall_status": row["overall_status"],
            "phase": row["phase"],
            "phases": json.loads(row["phases_json"]),
            "enrollment_count": row["enrollment_count"],
            "enrollment_type": row["enrollment_type"],
            "sponsor_name": row["sponsor_name"],
            "primary_completion_date": row["primary_completion_date"],
            "completion_date": row["completion_date"],
            "last_update_post_date": row["last_update_post_date"],
            "has_results": bool(row["has_results"]),
            "interventions": json.loads(row["interventions_json"]),
            "conditions": json.loads(row["conditions_json"]),
            "primary_outcomes": json.loads(row["primary_outcomes_json"]),
            "locations": json.loads(row["locations_json"]),
            "peptide_ids": json.loads(row["peptide_ids_json"]),
            "matched_aliases": json.loads(row["matched_aliases_json"]),
            "query_terms": json.loads(row["query_terms_json"]),
            "record_hash": row["record_hash"],
            "raw": json.loads(row["raw_json"]),
        }
    )


def _connect(db_path: str | Path) -> sqlite3.Connection:
    connection = sqlite3.connect(db_path)
    connection.row_factory = sqlite3.Row
    connection.execute("PRAGMA foreign_keys = ON")
    return connection


def _known_nct_ids(config: WatchConfig) -> set[str]:
    nct_ids: set[str] = set()
    for source in config.sources.values():
        nct_ids.update(match.upper() for match in NCT_RE.findall(source.url))
    for queries in config.queries.values():
        for query in queries:
            nct_ids.update(match.upper() for match in NCT_RE.findall(query))
    return nct_ids


def _alias_query_terms(config: WatchConfig) -> set[str]:
    terms: set[str] = set()
    for peptide in config.peptides:
        terms.update(peptide.aliases)
    return terms


def _match_peptide_aliases(match_text: str, config: WatchConfig | None) -> tuple[list[str], list[str]]:
    if config is None:
        return [], []
    lowered = match_text.casefold()
    peptide_ids: list[str] = []
    aliases: list[str] = []
    for peptide in config.peptides:
        matched = [alias for alias in peptide.aliases if alias.casefold() in lowered]
        if matched:
            peptide_ids.append(peptide.id)
            aliases.extend(matched)
    return sorted(set(peptide_ids)), sorted(set(aliases), key=str.casefold)


def _trial_match_text(study: dict[str, Any]) -> str:
    protocol = study.get("protocolSection", {})
    pieces = [
        protocol.get("identificationModule", {}),
        protocol.get("conditionsModule", {}),
        protocol.get("armsInterventionsModule", {}),
        protocol.get("descriptionModule", {}),
        study.get("derivedSection", {}),
    ]
    return _json(pieces)


def _intervention_names(interventions: list[dict[str, Any]]) -> list[str]:
    names: list[str] = []
    for intervention in interventions:
        if intervention.get("name"):
            names.append(str(intervention["name"]))
        names.extend(_strings(intervention.get("otherNames", [])))
    return sorted(set(names), key=str.casefold)


def _outcome_measures(outcomes: list[dict[str, Any]]) -> list[str]:
    return [str(outcome["measure"]) for outcome in outcomes if outcome.get("measure")]


def _locations(locations: list[dict[str, Any]]) -> list[str]:
    simplified: list[str] = []
    for location in locations:
        parts = [
            location.get("facility"),
            location.get("city"),
            location.get("state"),
            location.get("country"),
            location.get("status"),
        ]
        simplified.append(", ".join(str(part) for part in parts if part))
    return simplified


def _strings(values: Iterable[Any]) -> list[str]:
    return [str(value) for value in values if value is not None]


def _date_value(date_struct: dict[str, Any] | None) -> str | None:
    if not date_struct:
        return None
    value = date_struct.get("date")
    return str(value) if value else None


def _int_or_none(value: Any) -> int | None:
    if value is None:
        return None
    try:
        return int(value)
    except (TypeError, ValueError):
        return None


def _hash_payload(payload: Any) -> str:
    return hashlib.sha256(_json(payload).encode("utf-8")).hexdigest()


def _json(value: Any) -> str:
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False)


def _markdown_cell(value: object) -> str:
    if value is None:
        return ""
    return str(value).replace("|", "\\|").replace("\n", " ")
