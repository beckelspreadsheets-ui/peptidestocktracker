"""Federal Register API monitor for FDA regulatory notices."""

from __future__ import annotations

import json
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any
from urllib.parse import urlencode
from urllib.request import Request, urlopen

from peptide_watch.config import WatchConfig, load_config
from peptide_watch.sources.regulatory import (
    RegulatoryDocument,
    RegulatoryScanResult,
    build_regulatory_document,
    export_regulatory_documents_markdown,
    hash_bytes,
    list_regulatory_documents,
    store_regulatory_document,
)

FEDERAL_REGISTER_BASE_URL = "https://www.federalregister.gov/api/v1"
FEDERAL_REGISTER_SOURCE_ID = "federal_register"


@dataclass(frozen=True)
class FederalRegisterClient:
    """Federal Register public API client with explicit rate limiting."""

    base_url: str = FEDERAL_REGISTER_BASE_URL
    timeout: float = 30.0
    rate_limit_seconds: float = 0.2
    user_agent: str = "peptide-watch/0.1 public-source research"

    def search_documents(self, query: str, *, per_page: int = 20) -> list[dict[str, Any]]:
        if per_page < 1 or per_page > 1000:
            raise ValueError("per_page must be between 1 and 1000")
        payload = self._get_json(
            "/documents.json",
            {
                "conditions[term]": query,
                "conditions[agencies][]": "food-and-drug-administration",
                "per_page": per_page,
                "order": "newest",
            },
        )
        return list(payload.get("results", []))

    def get_document(self, document_number: str) -> dict[str, Any]:
        return self._get_json(f"/documents/{document_number}.json")

    def get_text(self, url: str) -> str:
        request = Request(
            url,
            headers={"Accept": "text/plain,*/*", "User-Agent": self.user_agent},
        )
        try:
            with urlopen(request, timeout=self.timeout) as response:
                return response.read().decode("utf-8", errors="ignore")
        finally:
            if self.rate_limit_seconds > 0:
                time.sleep(self.rate_limit_seconds)

    def _get_json(self, path: str, params: dict[str, str | int] | None = None) -> dict[str, Any]:
        url = f"{self.base_url}{path}"
        if params:
            url = f"{url}?{urlencode(params)}"
        request = Request(
            url,
            headers={"Accept": "application/json", "User-Agent": self.user_agent},
        )
        try:
            with urlopen(request, timeout=self.timeout) as response:
                return json.loads(response.read().decode("utf-8"))
        finally:
            if self.rate_limit_seconds > 0:
                time.sleep(self.rate_limit_seconds)


def scan_federal_register(
    db_path: str | Path,
    *,
    config_dir: str | Path = "config",
    client: FederalRegisterClient | None = None,
    queries: list[str] | None = None,
    per_page: int = 20,
) -> RegulatoryScanResult:
    """Search FDA Federal Register notices and store matching documents."""

    config = load_config(config_dir)
    api_client = client or FederalRegisterClient()
    selected_queries = queries or _default_queries(config)

    fetched = stored = inserted = changed = events_created = 0
    seen_document_numbers: set[str] = set()
    for query in selected_queries:
        results = api_client.search_documents(query, per_page=per_page)
        fetched += len(results)
        for result in results:
            document_number = str(result.get("document_number") or "").strip()
            if not document_number or document_number in seen_document_numbers:
                continue
            seen_document_numbers.add(document_number)
            detail = api_client.get_document(document_number)
            if result.get("excerpts") and not detail.get("excerpts"):
                detail["excerpts"] = result["excerpts"]
            raw_text_url = detail.get("raw_text_url")
            if raw_text_url:
                detail["_raw_text"] = api_client.get_text(str(raw_text_url))
            document = normalize_federal_register_document(detail, query, config)
            store_result = store_regulatory_document(db_path, document)
            stored += 1
            inserted += int(store_result.inserted)
            changed += int(store_result.changed)
            events_created += store_result.events_created

    return RegulatoryScanResult(
        fetched=fetched,
        stored=stored,
        inserted=inserted,
        changed=changed,
        events_created=events_created,
        source_ids=[FEDERAL_REGISTER_SOURCE_ID],
        queries=selected_queries,
    )


def normalize_federal_register_document(
    document: dict[str, Any],
    query: str,
    config: WatchConfig,
) -> RegulatoryDocument:
    """Normalize detailed Federal Register document JSON."""

    document_number = str(document["document_number"])
    text = _document_text(document)
    raw = json.dumps(document, sort_keys=True, separators=(",", ":"), ensure_ascii=False)
    return build_regulatory_document(
        document_key=f"federal_register:{document_number}",
        source_id=FEDERAL_REGISTER_SOURCE_ID,
        source_type="federal_register_notice",
        url=str(document.get("html_url") or document.get("json_url") or ""),
        title=document.get("title"),
        document_number=document_number,
        publication_date=document.get("publication_date"),
        docket_ids=_docket_ids(document),
        content_text=text,
        config=config,
        metadata={"query": query, "raw": document},
        content_hash=hash_bytes(raw.encode("utf-8")),
    )


def list_federal_register_documents(
    db_path: str | Path,
    *,
    limit: int = 100,
) -> list[RegulatoryDocument]:
    return list_regulatory_documents(db_path, source_prefix=FEDERAL_REGISTER_SOURCE_ID, limit=limit)


def export_federal_register_documents_markdown(documents: list[RegulatoryDocument]) -> str:
    return export_regulatory_documents_markdown(documents)


def _default_queries(config: WatchConfig) -> list[str]:
    return list(config.queries.get("pcac_docket", [])) or [
        "BPC-157 KPV TB-500 MOTs-C Semax Epitalon Pharmacy Compounding Advisory Committee"
    ]


def _document_text(document: dict[str, Any]) -> str:
    pieces = [
        document.get("title"),
        document.get("abstract"),
        document.get("action"),
        document.get("dates"),
        document.get("excerpts"),
        document.get("_raw_text"),
        " ".join(document.get("docket_ids") or []),
    ]
    for docket in document.get("dockets") or []:
        pieces.append(docket.get("id"))
        pieces.append(docket.get("title"))
    return " ".join(str(piece) for piece in pieces if piece)


def _docket_ids(document: dict[str, Any]) -> list[str]:
    docket_ids = [str(value) for value in document.get("docket_ids") or []]
    docket_ids.extend(str(docket.get("id")) for docket in document.get("dockets") or [] if docket.get("id"))
    return sorted(set(docket_ids))
