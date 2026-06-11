"""NIH RePORTER monitor — federal research grant awards.

Grant money is the earliest public signal of peptide research activity, often
years before a trial or filing. SBIR/STTR awards in particular go to small
companies, so this doubles as a stock-discovery source. Uses descriptive
multi-word queries with RePORTER's AND operator (short hyphenated codes
tokenize too loosely; full names like "thymosin beta-4" are precise —
live-verified).
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

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

NIH_REPORTER_SOURCE_ID = "nih_reporter"
NIH_REPORTER_URL = "https://api.reporter.nih.gov/v2/projects/search"
SEARCH_FIELDS = "projecttitle,abstracttext,terms"
PARSER_VERSION = 1


class NihReporterClient:
    """NIH RePORTER v2 projects search client (POST)."""

    def __init__(
        self,
        *,
        url: str = NIH_REPORTER_URL,
        timeout: float = 30.0,
        rate_limit_seconds: float = 1.0,
        user_agent: str = DEFAULT_USER_AGENT,
        http: HttpClient | None = None,
    ) -> None:
        self.url = url
        self._http = http or HttpClient(
            timeout=timeout, rate_limit_seconds=rate_limit_seconds, user_agent=user_agent
        )

    def search(self, text: str, *, limit: int = 25) -> list[dict[str, Any]]:
        payload = self._http.post_json(
            self.url,
            json_body={
                "criteria": {
                    "advanced_text_search": {
                        "operator": "and",
                        "search_field": SEARCH_FIELDS,
                        "search_text": text,
                    }
                },
                "limit": limit,
                "sort_field": "award_notice_date",
                "sort_order": "desc",
            },
        )
        return list(payload.get("results", []))


def default_reporter_queries(config: WatchConfig) -> list[str]:
    queries = list(config.queries.get("nih_reporter", []))
    if queries:
        return queries
    # Descriptive multi-word names only (AND-tokenized precisely).
    descriptive: list[str] = []
    for peptide in config.primary_peptides:
        for alias in peptide.aliases:
            if " " in alias and len(alias) > 6:
                descriptive.append(alias)
                break
    return descriptive or ["thymosin beta-4"]


def scan_nih_reporter(
    db_path: str | Path,
    *,
    config_dir: str | Path = "config",
    client: NihReporterClient | None = None,
    queries: list[str] | None = None,
    run_id: str | None = None,
) -> RegulatoryScanResult:
    """Search NIH RePORTER for watch terms and store matching grant projects.

    Each query fails independently; a project's writes are one transaction.
    """

    config = load_config(config_dir)
    api_client = client or NihReporterClient()
    selected_queries = queries or default_reporter_queries(config)
    run_id = run_id or ad_hoc_run_id()

    init_db(db_path)
    connection = open_connection(db_path)
    fetched = stored = inserted = changed = events_created = 0
    errors: list[str] = []
    seen_ids: set[str] = set()
    try:
        for query in selected_queries:
            try:
                projects = api_client.search(query)
            except (KeyboardInterrupt, SystemExit):
                raise
            except Exception as exc:
                errors.append(f"query {query!r}: {exc}")
                continue
            for project in projects:
                project_id = str(project.get("project_num") or project.get("appl_id") or "")
                if not project_id or project_id in seen_ids:
                    continue
                seen_ids.add(project_id)
                try:
                    fetched += 1
                    document = normalize_reporter_project(project_id, project, query, config)
                    result = write_regulatory_document(connection, document, run_id=run_id)
                    connection.commit()
                except (KeyboardInterrupt, SystemExit):
                    raise
                except Exception as exc:
                    connection.rollback()
                    errors.append(f"project {project_id}: {exc}")
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

    if errors and stored == 0 and selected_queries:
        raise RuntimeError(f"NIH RePORTER scan failed for all queries: {'; '.join(errors[:5])}")

    return RegulatoryScanResult(
        fetched=fetched,
        stored=stored,
        inserted=inserted,
        changed=changed,
        events_created=events_created,
        source_ids=[NIH_REPORTER_SOURCE_ID],
        queries=selected_queries,
        errors=errors,
    )


def normalize_reporter_project(
    project_id: str, project: dict[str, Any], query: str, config: WatchConfig
):
    org = project.get("organization") or {}
    org_name = str(org.get("org_name") or "")
    title = str(project.get("project_title") or "")
    abstract = str(project.get("abstract_text") or "")
    activity = str(project.get("activity_code") or "")
    award_date = str(project.get("award_notice_date") or "")[:10]
    # SBIR/STTR activity codes (R41/R42/R43/R44) flag small-company awards.
    is_small_business = activity.upper() in {"R41", "R42", "R43", "R44"}
    text = ". ".join(
        part for part in [title, org_name, abstract, f"Activity {activity}", award_date] if part
    )
    raw = json.dumps(project, sort_keys=True, separators=(",", ":"), ensure_ascii=False)
    return build_regulatory_document(
        document_key=f"nih_reporter:{project_id}",
        source_id=NIH_REPORTER_SOURCE_ID,
        source_type="nih_grant",
        url=f"https://reporter.nih.gov/project-details/{project.get('appl_id') or project_id}",
        title=title or f"NIH project {project_id}",
        publication_date=award_date or None,
        content_text=text,
        config=config,
        metadata={
            "query": query,
            "organization": org_name,
            "activity_code": activity,
            "small_business_award": is_small_business,
        },
        raw_content=raw.encode("utf-8"),
        parser_version=PARSER_VERSION,
    )
