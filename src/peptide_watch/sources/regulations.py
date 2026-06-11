"""Regulations.gov monitor — the leading-edge regulatory signal.

The Federal Register announces a rule; Regulations.gov shows the docket open,
the comment period running, and who is filing comments — months earlier. A
notice or proposed rule *open for comment* is the regulatory door opening; a
public submission reveals which companies/groups are positioning. Uses the
public DEMO_KEY by default (works out of the box, rate-limited); set
PEPTIDE_WATCH_REGULATIONS_API_KEY to a free key from api.data.gov for headroom.
"""

from __future__ import annotations

import json
import os
import re
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

REGULATIONS_SOURCE_ID = "regulations_gov"
REGULATIONS_URL = "https://api.regulations.gov/v4/documents"
REGULATIONS_API_KEY_ENV = "PEPTIDE_WATCH_REGULATIONS_API_KEY"
PUBLIC_DEMO_KEY = "DEMO_KEY"
PARSER_VERSION = 1
_TAG_RE = re.compile(r"<[^>]+>")


class RegulationsClient:
    """Regulations.gov v4 documents search client."""

    def __init__(
        self,
        *,
        url: str = REGULATIONS_URL,
        api_key: str | None = None,
        agency_id: str | None = "FDA",
        timeout: float = 30.0,
        rate_limit_seconds: float = 2.0,
        user_agent: str = DEFAULT_USER_AGENT,
        http: HttpClient | None = None,
    ) -> None:
        self.url = url
        self.agency_id = agency_id
        self.api_key = api_key or os.environ.get(REGULATIONS_API_KEY_ENV) or PUBLIC_DEMO_KEY
        self._http = http or HttpClient(
            timeout=timeout, rate_limit_seconds=rate_limit_seconds, user_agent=user_agent
        )

    def search(self, term: str, *, page_size: int = 20) -> list[dict[str, Any]]:
        params: dict[str, Any] = {
            "filter[searchTerm]": term,
            "page[size]": page_size,
            "sort": "-postedDate",
        }
        # Restrict to the relevant agency (FDA by default) — searchTerm
        # tokenizes, so cross-agency matches ("503A" in EPA dockets) are noise.
        if self.agency_id:
            params["filter[agencyId]"] = self.agency_id
        payload = self._http.get_json(
            self.url, params=params, extra_headers={"X-Api-Key": self.api_key}
        )
        return list(payload.get("data", []))


def default_regulations_queries(config: WatchConfig) -> list[str]:
    queries = list(config.queries.get("regulations", []))
    if queries:
        return queries
    terms = [peptide.aliases[0] for peptide in config.primary_peptides]
    terms += ["peptide compounding", "503A bulk drug substances"]
    return terms


def scan_regulations(
    db_path: str | Path,
    *,
    config_dir: str | Path = "config",
    client: RegulationsClient | None = None,
    queries: list[str] | None = None,
    run_id: str | None = None,
) -> RegulatoryScanResult:
    """Search Regulations.gov for watch terms and store dockets/comments.

    Each query fails independently; a document's writes are one transaction.
    """

    config = load_config(config_dir)
    api_client = client or RegulationsClient()
    selected_queries = queries or default_regulations_queries(config)
    run_id = run_id or ad_hoc_run_id()

    init_db(db_path)
    connection = open_connection(db_path)
    fetched = stored = inserted = changed = events_created = 0
    errors: list[str] = []
    seen_ids: set[str] = set()
    try:
        for query in selected_queries:
            try:
                documents = api_client.search(query)
            except (KeyboardInterrupt, SystemExit):
                raise
            except Exception as exc:
                errors.append(f"query {query!r}: {exc}")
                continue
            for entry in documents:
                doc_id = str(entry.get("id") or "")
                if not doc_id or doc_id in seen_ids:
                    continue
                seen_ids.add(doc_id)
                try:
                    fetched += 1
                    document = normalize_regulations_document(doc_id, entry, query, config)
                    result = write_regulatory_document(connection, document, run_id=run_id)
                    connection.commit()
                except (KeyboardInterrupt, SystemExit):
                    raise
                except Exception as exc:
                    connection.rollback()
                    errors.append(f"document {doc_id}: {exc}")
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
        raise RuntimeError(f"Regulations.gov scan failed for all queries: {'; '.join(errors[:5])}")

    return RegulatoryScanResult(
        fetched=fetched,
        stored=stored,
        inserted=inserted,
        changed=changed,
        events_created=events_created,
        source_ids=[REGULATIONS_SOURCE_ID],
        queries=selected_queries,
        errors=errors,
    )


def normalize_regulations_document(
    doc_id: str, entry: dict[str, Any], query: str, config: WatchConfig
):
    attributes = entry.get("attributes") or {}
    title = str(attributes.get("title") or "")
    doc_type = str(attributes.get("documentType") or "")
    agency = str(attributes.get("agencyId") or "")
    docket_id = str(attributes.get("docketId") or "")
    open_for_comment = bool(attributes.get("openForComment"))
    comment_end = str(attributes.get("commentEndDate") or "")
    posted = str(attributes.get("postedDate") or "")[:10]
    highlighted = _TAG_RE.sub(" ", str(attributes.get("highlightedContent") or ""))

    comment_status = (
        f"OPEN for comment until {comment_end}" if open_for_comment else "comment period closed"
    )
    text = ". ".join(
        part
        for part in [
            title,
            f"{doc_type} ({agency})",
            f"Docket {docket_id}",
            comment_status,
            highlighted,
            f"Regulations.gov match for {query}",
        ]
        if part
    )
    return build_regulatory_document(
        document_key=f"regulations:{doc_id}",
        source_id=REGULATIONS_SOURCE_ID,
        source_type="regulations_document",
        url=f"https://www.regulations.gov/document/{doc_id}",
        title=title or doc_id,
        document_number=docket_id or None,
        publication_date=posted or None,
        content_text=text,
        config=config,
        metadata={
            "query": query,
            "document_type": doc_type,
            "agency": agency,
            "docket_id": docket_id,
            "open_for_comment": open_for_comment,
            "comment_end_date": comment_end,
        },
        raw_content=json.dumps(entry, sort_keys=True, separators=(",", ":")).encode("utf-8"),
        parser_version=PARSER_VERSION,
    )
