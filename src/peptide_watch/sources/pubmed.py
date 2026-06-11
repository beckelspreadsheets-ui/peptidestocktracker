"""PubMed E-utilities monitor for new publications mentioning watch terms."""

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

PUBMED_SOURCE_ID = "pubmed"
PUBMED_EUTILS_BASE_URL = "https://eutils.ncbi.nlm.nih.gov/entrez/eutils"
PARSER_VERSION = 1


class PubMedClient:
    """NCBI E-utilities client (esearch + esummary), JSON mode."""

    def __init__(
        self,
        *,
        base_url: str = PUBMED_EUTILS_BASE_URL,
        timeout: float = 30.0,
        rate_limit_seconds: float = 0.5,
        user_agent: str = DEFAULT_USER_AGENT,
        http: HttpClient | None = None,
    ) -> None:
        self.base_url = base_url.rstrip("/")
        self._http = http or HttpClient(
            timeout=timeout, rate_limit_seconds=rate_limit_seconds, user_agent=user_agent
        )

    def search(self, term: str, *, retmax: int = 20) -> list[str]:
        payload = self._http.get_json(
            f"{self.base_url}/esearch.fcgi",
            params={
                "db": "pubmed",
                "term": term,
                "retmode": "json",
                "retmax": retmax,
                "sort": "date",
            },
        )
        return [str(pmid) for pmid in payload.get("esearchresult", {}).get("idlist", [])]

    def summaries(self, pmids: list[str]) -> dict[str, dict[str, Any]]:
        if not pmids:
            return {}
        payload = self._http.get_json(
            f"{self.base_url}/esummary.fcgi",
            params={"db": "pubmed", "id": ",".join(pmids), "retmode": "json"},
        )
        result = payload.get("result", {})
        return {pmid: result[pmid] for pmid in result.get("uids", []) if pmid in result}


def default_pubmed_queries(config: WatchConfig) -> list[str]:
    """Quoted alias queries for the primary watch targets."""

    terms: list[str] = []
    for peptide in config.primary_peptides:
        joined = " OR ".join(f'"{alias}"' for alias in peptide.aliases[:4])
        terms.append(joined)
    return terms


def scan_pubmed(
    db_path: str | Path,
    *,
    config_dir: str | Path = "config",
    client: PubMedClient | None = None,
    queries: list[str] | None = None,
    retmax: int = 20,
    run_id: str | None = None,
) -> RegulatoryScanResult:
    """Search PubMed for configured terms and store new publications.

    Each query fails independently; a publication's writes are one transaction.
    """

    config = load_config(config_dir)
    api_client = client or PubMedClient()
    selected_queries = queries or list(config.queries.get("pubmed", [])) or default_pubmed_queries(config)
    run_id = run_id or ad_hoc_run_id()

    init_db(db_path)
    connection = open_connection(db_path)
    fetched = stored = inserted = changed = events_created = 0
    errors: list[str] = []
    seen_pmids: set[str] = set()
    try:
        for query in selected_queries:
            try:
                pmids = [p for p in api_client.search(query, retmax=retmax) if p not in seen_pmids]
                seen_pmids.update(pmids)
                summaries = api_client.summaries(pmids)
            except (KeyboardInterrupt, SystemExit):
                raise
            except Exception as exc:
                errors.append(f"query {query!r}: {exc}")
                continue
            for pmid, summary in summaries.items():
                try:
                    fetched += 1
                    document = normalize_pubmed_summary(pmid, summary, query, config)
                    result = write_regulatory_document(connection, document, run_id=run_id)
                    connection.commit()
                except (KeyboardInterrupt, SystemExit):
                    raise
                except Exception as exc:
                    connection.rollback()
                    errors.append(f"pmid {pmid}: {exc}")
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
        raise RuntimeError(f"PubMed scan failed for all queries: {'; '.join(errors[:5])}")

    return RegulatoryScanResult(
        fetched=fetched,
        stored=stored,
        inserted=inserted,
        changed=changed,
        events_created=events_created,
        source_ids=[PUBMED_SOURCE_ID],
        queries=selected_queries,
        errors=errors,
    )


def normalize_pubmed_summary(
    pmid: str, summary: dict[str, Any], query: str, config: WatchConfig
):
    title = str(summary.get("title") or "").strip()
    journal = str(summary.get("fulljournalname") or summary.get("source") or "").strip()
    pubdate = str(summary.get("pubdate") or "").strip()
    authors = ", ".join(
        str(author.get("name", "")) for author in summary.get("authors", [])[:6]
    )
    text = ". ".join(part for part in [title, journal, authors, pubdate] if part)
    raw = json.dumps(summary, sort_keys=True, separators=(",", ":"), ensure_ascii=False)
    return build_regulatory_document(
        document_key=f"pubmed:{pmid}",
        source_id=PUBMED_SOURCE_ID,
        source_type="pubmed_publication",
        url=f"https://pubmed.ncbi.nlm.nih.gov/{pmid}/",
        title=title or f"PubMed {pmid}",
        publication_date=pubdate or None,
        content_text=text,
        config=config,
        metadata={"query": query, "pmid": pmid},
        raw_content=raw.encode("utf-8"),
        parser_version=PARSER_VERSION,
    )
