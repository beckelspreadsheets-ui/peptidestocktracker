"""openFDA drug enforcement (recall) monitor.

Public JSON API, no key required. Catches recalls/enforcement actions whose
product description or recall reason mentions a watch term — e.g. a
compounded peptide injectable recalled for sterility failures.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import httpx

from peptide_watch.config import WatchConfig, load_config
from peptide_watch.database import init_db
from peptide_watch.events import ad_hoc_run_id
from peptide_watch.net.client import DEFAULT_USER_AGENT, HttpClient
from peptide_watch.sources.regulatory import (
    RegulatoryScanResult,
    build_regulatory_document,
    open_connection,
    write_regulatory_document,
)

OPENFDA_SOURCE_ID = "openfda_enforcement"
OPENFDA_BASE_URL = "https://api.fda.gov/drug/enforcement.json"
PARSER_VERSION = 1


class OpenFdaClient:
    """openFDA drug enforcement API client."""

    def __init__(
        self,
        *,
        base_url: str = OPENFDA_BASE_URL,
        timeout: float = 30.0,
        rate_limit_seconds: float = 0.5,
        user_agent: str = DEFAULT_USER_AGENT,
        http: HttpClient | None = None,
    ) -> None:
        self.base_url = base_url
        self._http = http or HttpClient(
            timeout=timeout, rate_limit_seconds=rate_limit_seconds, user_agent=user_agent
        )

    def search_enforcements(self, term: str, *, limit: int = 50) -> list[dict[str, Any]]:
        # Field-qualified OR queries are unreliable on openFDA (live-tested),
        # so each field is searched separately and merged.
        results: list[dict[str, Any]] = []
        for field in ("product_description", "reason_for_recall"):
            try:
                payload = self._http.get_json(
                    self.base_url,
                    params={"search": f'{field}:"{term}"', "limit": limit},
                )
            except httpx.HTTPStatusError as exc:
                if exc.response.status_code == 404:
                    continue  # openFDA answers 404 when a search matches nothing
                raise
            results.extend(payload.get("results", []))
        return results


def default_enforcement_terms(config: WatchConfig) -> list[str]:
    terms = ["peptide"]
    for peptide in config.primary_peptides:
        terms.append(peptide.aliases[0])
    return terms


def scan_openfda_enforcement(
    db_path: str | Path,
    *,
    config_dir: str | Path = "config",
    client: OpenFdaClient | None = None,
    terms: list[str] | None = None,
    run_id: str | None = None,
) -> RegulatoryScanResult:
    """Search openFDA enforcement reports for watch terms and store matches.

    Each term fails independently; a report's writes are one transaction.
    """

    config = load_config(config_dir)
    api_client = client or OpenFdaClient()
    selected_terms = terms or list(config.queries.get("openfda", [])) or default_enforcement_terms(config)
    run_id = run_id or ad_hoc_run_id()

    init_db(db_path)
    connection = open_connection(db_path)
    fetched = stored = inserted = changed = events_created = 0
    errors: list[str] = []
    seen_recalls: set[str] = set()
    try:
        for term in selected_terms:
            try:
                reports = api_client.search_enforcements(term)
            except (KeyboardInterrupt, SystemExit):
                raise
            except Exception as exc:
                errors.append(f"term {term!r}: {exc}")
                continue
            for report in reports:
                recall_number = str(report.get("recall_number") or "").strip()
                if not recall_number or recall_number in seen_recalls:
                    continue
                seen_recalls.add(recall_number)
                try:
                    fetched += 1
                    document = normalize_enforcement_report(recall_number, report, term, config)
                    result = write_regulatory_document(connection, document, run_id=run_id)
                    connection.commit()
                except (KeyboardInterrupt, SystemExit):
                    raise
                except Exception as exc:
                    connection.rollback()
                    errors.append(f"recall {recall_number}: {exc}")
                    continue
                stored += 1
                inserted += int(result.inserted)
                changed += int(result.changed)
                events_created += result.events_created
    except BaseException:
        connection.rollback()
        connection.close()
        raise
    else:
        connection.close()

    if errors and stored == 0 and selected_terms:
        raise RuntimeError(
            f"openFDA enforcement scan failed for all terms: {'; '.join(errors[:5])}"
        )

    return RegulatoryScanResult(
        fetched=fetched,
        stored=stored,
        inserted=inserted,
        changed=changed,
        events_created=events_created,
        source_ids=[OPENFDA_SOURCE_ID],
        queries=selected_terms,
        errors=errors,
    )


def normalize_enforcement_report(
    recall_number: str, report: dict[str, Any], term: str, config: WatchConfig
):
    classification = str(report.get("classification") or "")
    status = str(report.get("status") or "")
    description = str(report.get("product_description") or "")
    reason = str(report.get("reason_for_recall") or "")
    firm = str(report.get("recalling_firm") or "")
    report_date = str(report.get("report_date") or "")
    text = (
        f"{classification} {status} enforcement {recall_number}: {description} "
        f"Reason: {reason} Recalling firm: {firm}. Reported {report_date}."
    )
    raw = json.dumps(report, sort_keys=True, separators=(",", ":"), ensure_ascii=False)
    return build_regulatory_document(
        document_key=f"openfda:{recall_number}",
        source_id=OPENFDA_SOURCE_ID,
        source_type="fda_enforcement",
        url=(
            "https://api.fda.gov/drug/enforcement.json?search="
            f"recall_number:%22{recall_number}%22"
        ),
        title=f"FDA enforcement {recall_number}: {firm}".strip(),
        publication_date=report_date or None,
        content_text=text,
        config=config,
        metadata={
            "term": term,
            "event_id": str(report.get("event_id") or ""),
            "classification": classification,
            "status": status,
        },
        raw_content=raw.encode("utf-8"),
        parser_version=PARSER_VERSION,
    )
