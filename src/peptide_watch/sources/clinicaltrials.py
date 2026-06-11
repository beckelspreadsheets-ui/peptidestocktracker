"""ClinicalTrials.gov API v2 adapter."""

from __future__ import annotations

import hashlib
import json
import re
import sqlite3
from pathlib import Path
from typing import Any, Iterable

from pydantic import BaseModel, ConfigDict, Field, field_validator

from peptide_watch.config import WatchConfig, load_config
from peptide_watch.database import connect, init_db
from peptide_watch.events import ad_hoc_run_id, insert_event
from peptide_watch.net.client import DEFAULT_USER_AGENT, HttpClient

CLINICALTRIALS_BASE_URL = "https://clinicaltrials.gov/api/v2"
CLINICALTRIALS_SOURCE_ID = "clinicaltrials"
NCT_RE = re.compile(r"\bNCT\d{8}\b", re.IGNORECASE)
PARSER_VERSION = 1
MISS_THRESHOLD = 3


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
    raw_sha256: str = ""
    parser_version: int = PARSER_VERSION

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
    errors: list[str] = Field(default_factory=list)


class ClinicalTrialsClient:
    """Small ClinicalTrials.gov API v2 client on the shared HTTP layer."""

    def __init__(
        self,
        *,
        base_url: str = CLINICALTRIALS_BASE_URL,
        timeout: float = 20.0,
        # ClinicalTrials.gov throttles bursts with 403s (live-observed);
        # stay near 1 request/second.
        rate_limit_seconds: float = 1.0,
        user_agent: str = DEFAULT_USER_AGENT,
        http: HttpClient | None = None,
    ) -> None:
        self.base_url = base_url
        self._http = http or HttpClient(
            timeout=timeout, rate_limit_seconds=rate_limit_seconds, user_agent=user_agent
        )

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
        return self._http.get_json(f"{self.base_url}{path}", params=params)


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
        "raw_sha256": _hash_payload(study),
        "parser_version": PARSER_VERSION,
    }
    normalized["record_hash"] = _hash_payload(
        {
            key: value
            for key, value in normalized.items()
            if key not in {"query_terms", "raw", "record_hash", "raw_sha256", "parser_version"}
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
    run_id: str | None = None,
) -> ScanResult:
    """Scan ClinicalTrials.gov for configured aliases and known NCT IDs."""

    config = load_config(config_dir)
    api_client = client or ClinicalTrialsClient()
    run_id = run_id or ad_hoc_run_id()
    explicit_ncts = {nct.upper() for nct in nct_ids}
    explicit_terms = set(query_terms)
    terms = sorted(explicit_terms | (_alias_query_terms(config) if include_alias_queries else set()))
    known_ncts = sorted(
        explicit_ncts | (_known_nct_ids(config) if include_known_ncts else set())
    )

    init_db(db_path)
    connection = open_connection(db_path)
    fetched = 0
    stored = 0
    inserted = 0
    changed = 0
    events_created = 0
    errors: list[str] = []
    seen_ncts: set[str] = set()

    def _store(record: ClinicalTrialRecord) -> None:
        nonlocal stored, inserted, changed, events_created
        result = write_trial_record(connection, record, run_id=run_id)
        connection.commit()
        seen_ncts.add(record.nct_id)
        stored += 1
        inserted += int(result.inserted)
        changed += int(result.changed)
        events_created += result.events_created

    try:
        for nct_id in known_ncts:
            try:
                study = api_client.get_study(nct_id)
                fetched += 1
                _store(normalize_study(study, query_terms=[nct_id], config=config))
            except (KeyboardInterrupt, SystemExit):
                raise
            except Exception as exc:
                connection.rollback()
                errors.append(f"{nct_id}: {exc}")

        for term in terms:
            try:
                for study in api_client.search_studies(
                    term, page_size=page_size, max_pages=max_pages
                ):
                    fetched += 1
                    record = normalize_study(study, query_terms=[term], config=config)
                    if record.nct_id in seen_ncts:
                        continue
                    _store(record)
            except (KeyboardInterrupt, SystemExit):
                raise
            except Exception as exc:
                connection.rollback()
                errors.append(f"query {term!r}: {exc}")

        # Disappearance hysteresis only makes sense on a full, clean sweep:
        # partial scans and failed fetches would record false misses.
        full_scan = (
            include_known_ncts and include_alias_queries and not explicit_ncts and not explicit_terms
        )
        if full_scan and not errors:
            events_created += _track_disappearances(connection, seen_ncts, run_id=run_id)
            connection.commit()
    except BaseException:
        connection.rollback()
        connection.close()
        raise
    else:
        connection.close()

    if errors and stored == 0 and (known_ncts or terms):
        raise RuntimeError(
            f"ClinicalTrials.gov scan failed for all inputs: {'; '.join(errors[:5])}"
        )

    return ScanResult(
        fetched=fetched,
        stored=stored,
        inserted=inserted,
        changed=changed,
        events_created=events_created,
        searched_terms=terms,
        searched_nct_ids=known_ncts,
        errors=errors,
    )


def store_trial_record(
    db_path: str | Path,
    record: ClinicalTrialRecord,
    *,
    run_id: str | None = None,
) -> StoreResult:
    """Upsert a normalized trial record and emit durable change events."""

    init_db(db_path)
    connection = open_connection(db_path)
    try:
        result = write_trial_record(connection, record, run_id=run_id or ad_hoc_run_id())
        connection.commit()
        return result
    finally:
        connection.close()


def write_trial_record(
    connection: sqlite3.Connection,
    record: ClinicalTrialRecord,
    *,
    run_id: str,
) -> StoreResult:
    """Write one trial's full state (record + snapshot + events), no commit.

    The caller owns the transaction so the whole write set is atomic.
    """

    existing = _existing_trial(connection, record.nct_id)

    if existing is None:
        _insert_trial(connection, record)
        _insert_snapshot(connection, record)
        source_document_id = _insert_source_document(connection, record)
        created = _create_event(
            connection,
            record,
            source_document_id,
            run_id=run_id,
            event_type="new_recruiting_trial"
            if record.overall_status == "RECRUITING"
            else "clinical_trial_record_detected",
            field="",
            old_value="",
            new_value=record.record_hash,
            title=f"ClinicalTrials.gov record detected: {record.nct_id}",
            what_changed=(
                f"Confirmed fact: official ClinicalTrials.gov record {record.nct_id} "
                f"was detected with status {record.overall_status or 'unknown'}."
            ),
            severity="critical" if record.overall_status == "RECRUITING" else "high",
        )
        return StoreResult(
            nct_id=record.nct_id, inserted=True, changed=False, events_created=int(created)
        )

    _insert_snapshot(connection, record)
    if existing["record_hash"] == record.record_hash:
        _merge_last_seen(connection, record)
        return StoreResult(nct_id=record.nct_id, inserted=False, changed=False, events_created=0)

    previous_raw = _row_value(existing, "raw_sha256")
    if previous_raw and record.raw_sha256 and previous_raw == record.raw_sha256:
        # Identical fetched payload parsed differently: a parser upgrade, not
        # a registry change. Update stored state silently.
        _update_trial(connection, record)
        return StoreResult(nct_id=record.nct_id, inserted=False, changed=False, events_created=0)

    source_document_id = _insert_source_document(connection, record)
    events = _detect_change_events(connection, existing, record, source_document_id, run_id=run_id)
    _update_trial(connection, record)
    return StoreResult(
        nct_id=record.nct_id,
        inserted=False,
        changed=True,
        events_created=events,
    )


def _track_disappearances(
    connection: sqlite3.Connection,
    seen_ncts: set[str],
    *,
    run_id: str,
    threshold: int = MISS_THRESHOLD,
) -> int:
    """Count consecutive misses per stored trial; alert only at the threshold."""

    rows = connection.execute("SELECT nct_id, miss_count FROM clinical_trials").fetchall()
    events_created = 0
    for row in rows:
        nct_id = row["nct_id"]
        if nct_id in seen_ncts:
            continue
        miss_count = int(row["miss_count"] or 0) + 1
        connection.execute(
            "UPDATE clinical_trials SET miss_count = ? WHERE nct_id = ?",
            (miss_count, nct_id),
        )
        if miss_count != threshold:
            continue
        created = insert_event(
            connection,
            source_id=CLINICALTRIALS_SOURCE_ID,
            external_id=nct_id,
            event_type="record_disappeared",
            field="presence",
            old_value="present",
            new_value="missing",
            run_id=run_id,
            title=f"ClinicalTrials.gov record no longer returned: {nct_id}",
            what_changed=(
                f"Confirmed fact: {nct_id} was absent from {threshold} consecutive "
                "full scans of the configured queries and known NCT IDs."
            ),
            why_it_matters=(
                "Confirmed fact: the record stopped appearing in official query results. "
                "Inference: it may have been withdrawn, re-indexed, or renamed. "
                "Speculation: any significance is uncertain and requires manual review."
            ),
            confidence="medium",
            severity="low",
            directness="indirect",
            stock_market_relevance=(
                "Possible market relevance only; this is not a buy/sell recommendation. "
                "Verify independently."
            ),
        )
        events_created += int(created)
    return events_created


def list_trials(db_path: str | Path, *, limit: int = 100) -> list[ClinicalTrialRecord]:
    """Return stored trial records ordered by last seen timestamp."""

    init_db(db_path)
    if limit < 1:
        raise ValueError("limit must be at least 1")

    with open_connection(db_path) as connection:
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
    *,
    run_id: str,
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
        created = _create_event(
            connection,
            record,
            source_document_id,
            run_id=run_id,
            event_type=event_type,
            field=column,
            old_value="" if old_value is None else str(old_value),
            new_value="" if new_value is None else str(new_value),
            title=f"ClinicalTrials.gov {column.replace('_', ' ')} changed: {record.nct_id}",
            what_changed=f"Confirmed fact: {column} changed from {old_value!r} to {new_value!r}.",
            severity=severity,
        )
        events_created += int(created)
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
          raw_json,
          raw_sha256,
          parser_version,
          miss_count
        )
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 0)
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
            raw_sha256 = ?,
            parser_version = ?,
            miss_count = 0,
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
            raw_sha256 = ?,
            parser_version = ?,
            miss_count = 0,
            last_seen_at = CURRENT_TIMESTAMP
        WHERE nct_id = ?
        """,
        (
            _json(record.query_terms),
            _json(record.peptide_ids),
            _json(record.matched_aliases),
            record.raw_sha256,
            record.parser_version,
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
        record.raw_sha256,
        record.parser_version,
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
          raw_json,
          raw_sha256,
          parser_version
        )
        VALUES (?, ?, ?, ?, ?, ?)
        """,
        (
            record.nct_id,
            record.record_hash,
            record.source_url,
            _json(record.raw),
            record.raw_sha256,
            record.parser_version,
        ),
    )


def _create_event(
    connection: sqlite3.Connection,
    record: ClinicalTrialRecord,
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
        source_id=CLINICALTRIALS_SOURCE_ID,
        external_id=record.nct_id,
        event_type=event_type,
        field=field,
        old_value=old_value,
        new_value=new_value,
        run_id=run_id,
        title=title,
        what_changed=what_changed,
        why_it_matters=(
            "Confirmed fact: ClinicalTrials.gov is the official public registry source. "
            "Inference: changes may warrant follow-up research. "
            "Speculation: any market relevance is possible only and requires review."
        ),
        confidence="high",
        severity=severity,
        directness="direct",
        stock_market_relevance=(
            "Possible market relevance only; this is not a buy/sell recommendation."
        ),
        peptide_id=record.peptide_ids[0] if record.peptide_ids else None,
        source_document_id=source_document_id,
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
