"""openFDA drug shortage monitor — a compounding-demand signal.

When an FDA-approved peptide-class drug (GLP-1s and the like) goes into
shortage, compounders may legally fill the gap — the semaglutide shortage is
what created the compounding GLP-1 boom. A *new* shortage of a peptide drug is
therefore a leading demand signal for compounding-exposed companies, and a
*resolved* shortage is the reverse. Public openFDA API, no key required.
"""

from __future__ import annotations

import json
import re
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

OPENFDA_SHORTAGES_SOURCE_ID = "openfda_shortages"
OPENFDA_SHORTAGES_URL = "https://api.fda.gov/drug/shortages.json"
PARSER_VERSION = 1
_SLUG_RE = re.compile(r"[^a-z0-9]+")


class OpenFdaShortageClient:
    """openFDA drug shortage API client."""

    def __init__(
        self,
        *,
        base_url: str = OPENFDA_SHORTAGES_URL,
        timeout: float = 30.0,
        rate_limit_seconds: float = 0.5,
        user_agent: str = DEFAULT_USER_AGENT,
        http: HttpClient | None = None,
    ) -> None:
        self.base_url = base_url
        self._http = http or HttpClient(
            timeout=timeout, rate_limit_seconds=rate_limit_seconds, user_agent=user_agent
        )

    def search(self, term: str, *, limit: int = 50) -> list[dict[str, Any]]:
        try:
            payload = self._http.get_json(
                self.base_url, params={"search": term, "limit": limit}
            )
        except httpx.HTTPStatusError as exc:
            if exc.response.status_code == 404:
                return []  # openFDA answers 404 when a search matches nothing
            raise
        return list(payload.get("results", []))


def default_shortage_terms(config: WatchConfig) -> list[str]:
    terms = ['"peptide"', '"Glucagon-Like Peptide"']
    for peptide in config.primary_peptides:
        terms.append(f'"{peptide.aliases[0]}"')
    return terms


def scan_openfda_shortages(
    db_path: str | Path,
    *,
    config_dir: str | Path = "config",
    client: OpenFdaShortageClient | None = None,
    terms: list[str] | None = None,
    run_id: str | None = None,
) -> RegulatoryScanResult:
    """Search openFDA drug shortages for peptide-class drugs and store them.

    Each term fails independently; a record's writes are one transaction.
    """

    config = load_config(config_dir)
    api_client = client or OpenFdaShortageClient()
    selected_terms = terms or list(config.queries.get("openfda_shortages", [])) or default_shortage_terms(config)
    run_id = run_id or ad_hoc_run_id()

    init_db(db_path)
    connection = open_connection(db_path)
    fetched = stored = inserted = changed = events_created = 0
    errors: list[str] = []
    seen_keys: set[str] = set()
    try:
        for term in selected_terms:
            try:
                records = api_client.search(term)
            except (KeyboardInterrupt, SystemExit):
                raise
            except Exception as exc:
                errors.append(f"term {term!r}: {exc}")
                continue
            for record in records:
                document = normalize_shortage_record(record, term, config)
                if document is None or document.document_key in seen_keys:
                    continue
                seen_keys.add(document.document_key)
                try:
                    fetched += 1
                    result = write_regulatory_document(connection, document, run_id=run_id)
                    connection.commit()
                except (KeyboardInterrupt, SystemExit):
                    raise
                except Exception as exc:
                    connection.rollback()
                    errors.append(f"{document.document_key}: {exc}")
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
            f"openFDA shortage scan failed for all terms: {'; '.join(errors[:5])}"
        )

    return RegulatoryScanResult(
        fetched=fetched,
        stored=stored,
        inserted=inserted,
        changed=changed,
        events_created=events_created,
        source_ids=[OPENFDA_SHORTAGES_SOURCE_ID],
        queries=selected_terms,
        errors=errors,
    )


def normalize_shortage_record(record: dict[str, Any], term: str, config: WatchConfig):
    generic = str(record.get("generic_name") or "")
    ndc = str(record.get("package_ndc") or "")
    identity = ndc or _SLUG_RE.sub("-", generic.casefold()).strip("-")
    if not identity:
        return None

    status = str(record.get("status") or "")
    update_type = str(record.get("update_type") or "")
    company = str(record.get("company_name") or "")
    dosage = str(record.get("dosage_form") or "")
    category = "; ".join(record.get("therapeutic_category") or [])
    related = str(record.get("related_info") or "")
    openfda = record.get("openfda") or {}
    pharm_class = "; ".join(openfda.get("pharm_class_cs", []) or [])
    substances = "; ".join(openfda.get("substance_name", []) or [])
    posted = str(record.get("initial_posting_date") or "")

    text = ". ".join(
        part
        for part in [
            f"{generic} ({dosage}) shortage status: {status}",
            f"Update type {update_type}" if update_type else "",
            f"Company {company}" if company else "",
            category,
            pharm_class,
            substances,
            related,
            f"openFDA shortage match for {term}",
        ]
        if part
    )
    return build_regulatory_document(
        document_key=f"openfda_shortage:{identity}",
        source_id=OPENFDA_SHORTAGES_SOURCE_ID,
        source_type="drug_shortage",
        url="https://www.accessdata.fda.gov/scripts/drugshortages/",
        title=f"Drug shortage: {generic or identity} ({status})",
        publication_date=posted or None,
        content_text=text,
        config=config,
        metadata={
            "term": term,
            "generic_name": generic,
            "status": status,
            "update_type": update_type,
            "company_name": company,
            "pharm_class": pharm_class,
        },
        raw_content=json.dumps(record, sort_keys=True, separators=(",", ":")).encode("utf-8"),
        parser_version=PARSER_VERSION,
    )
