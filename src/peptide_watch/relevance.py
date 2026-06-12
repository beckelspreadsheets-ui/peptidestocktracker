"""Deterministic relevance ranking + the briefing data contract.

This is the compliant core both the web dashboard and the alert agent consume.
It ORDERS public-source facts by signal strength — it makes no buy/sell calls or
judgments of investment merit. Scores are
explainable (every event carries factual ``score_reasons``) and deterministic
(inject ``now`` for stable tests). The ``briefing`` dict is the single shared
contract served by the CLI (`peptide-watch briefing`) and the API
(`GET /api/briefing`).
"""

from __future__ import annotations

import json
import sqlite3
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any, Mapping

from peptide_watch.config import WatchConfig

SCHEMA_VERSION = "1.0"

# Weight budget sums to 100 so a score reads as 0–100.
W_SEVERITY = 30.0
W_TYPE = 35.0
W_PROXIMITY = 20.0
W_RECENCY = 15.0
RECENCY_HALF_LIFE_DAYS = 14.0

SEVERITY_WEIGHTS = {"critical": 1.0, "high": 0.75, "medium": 0.45, "low": 0.2}
_DEFAULT_SEVERITY = 0.45

# Highest = the earliest, highest-value catalysts; lowest = routine mentions.
EVENT_TYPE_WEIGHTS = {
    "new_company_peptide_disclosure": 1.0,
    "patent_assignment_to_public_company": 1.0,
    "patent_assignment_to_watchlist_company": 0.85,
    "regulatory_rule_open_for_comment": 0.8,
    "regulatory_comment_period_open": 0.7,
    "drug_shortage": 0.7,
    "new_recruiting_trial": 0.6,
    "trial_status_change": 0.55,
    "trial_phase_change": 0.55,
    "trial_results_posted": 0.55,
    "drug_shortage_update": 0.5,
    "sec_filing_target_mention": 0.45,
    "grant_award": 0.4,
    "federal_register_notice_detected": 0.4,
    "federal_register_notice_changed": 0.4,
    "fda_503a_status_update": 0.45,
    "fda_pcac_update": 0.45,
    "fda_503a_document_detected": 0.4,
    "fda_pcac_document_detected": 0.4,
    "fda_enforcement_report": 0.35,
    "regulatory_public_comment": 0.35,
    "company_press_release_target_mention": 0.3,
    "commercial_launch_claim": 0.35,
    "pubmed_publication": 0.25,
    "patent_publication": 0.2,
    "regulatory_docket_activity": 0.2,
    "record_disappeared": 0.2,
}
_DEFAULT_TYPE_WEIGHT = 0.3

DISCLAIMERS = {
    "global": (
        "This is public-source research, not financial advice. This is not a "
        "buy/sell recommendation. Verify independently."
    ),
    "microcap": (
        "OTC/CSE/microcap names may carry liquidity, dilution, promotional, and "
        "regulatory risk."
    ),
    "regulatory": (
        "PCAC review and 503A/503B list movement are not FDA drug approval."
    ),
    "company_source": (
        "Company press releases and commercial claims are company-source claims, "
        "not independently verified clinical evidence."
    ),
}

BRIEFING_EVENT_COLUMNS = (
    "id, event_type, peptide_id, source_document_id, title, what_changed, "
    "why_it_matters, confidence, severity, directness, stock_market_relevance, "
    "needs_review, source_id, external_id, field, old_value, new_value, run_id, "
    "created_at"
)


@dataclass
class ScoredEvent:
    score: float
    components: dict[str, float]
    score_reasons: list[str] = field(default_factory=list)


# --------------------------------------------------------------------------- #
# Scoring
# --------------------------------------------------------------------------- #
def _severity_weight(severity: str | None) -> float:
    return SEVERITY_WEIGHTS.get((severity or "").lower(), _DEFAULT_SEVERITY)


def _type_weight(event_type: str | None) -> float:
    return EVENT_TYPE_WEIGHTS.get(event_type or "", _DEFAULT_TYPE_WEIGHT)


def _parse_dt(value: Any) -> datetime | None:
    if not value:
        return None
    text = str(value).strip().replace("Z", "+00:00")
    try:
        dt = datetime.fromisoformat(text)
    except ValueError:
        try:
            dt = datetime.strptime(text[:19], "%Y-%m-%d %H:%M:%S")
        except ValueError:
            return None
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt


def _recency_weight(created_at: Any, now: datetime) -> tuple[float, float | None]:
    dt = _parse_dt(created_at)
    if dt is None:
        return 0.5, None  # neutral when unparseable/NULL
    age_days = max(0.0, (now - dt).total_seconds() / 86400.0)
    weight = 0.5 ** (age_days / RECENCY_HALF_LIFE_DAYS)
    return max(0.0, min(1.0, weight)), age_days


def proximity_index(config: WatchConfig) -> dict[str, Any]:
    """Precompute source_id -> CompanyConfig and the set of primary peptide ids."""

    companies = {company.id: company for company in config.companies}
    source_company = {}
    for source_id, source in config.sources.items():
        if getattr(source, "company_id", None):
            source_company[source_id] = companies.get(source.company_id)
    primary = {p.id for p in config.peptides if p.primary}
    configured = {p.id for p in config.peptides}
    return {
        "source_company": source_company,
        "primary_peptides": primary,
        "configured_peptides": configured,
    }


def _proximity_weight(event: Mapping[str, Any], index: dict[str, Any]) -> tuple[float, str]:
    event_type = event.get("event_type") or ""
    if event_type == "new_company_peptide_disclosure":
        return 0.6, "Watchlist proximity: new non-watchlist public filer (fresh lead)."
    company = index["source_company"].get(event.get("source_id"))
    if company is not None:
        tier_base = {1: 1.0, 2: 0.6, 3: 0.3}.get(company.tier, 0.4)
        public = (company.public_private or "").startswith("public")
        base = tier_base if public else tier_base * 0.5
        if (company.liquidity_risk or "").lower() in {"extreme", "high", "illiquid"}:
            base *= 0.85
        kind = "public" if public else "private"
        return base, f"Watchlist proximity: {kind}, Tier {company.tier} ({company.name})."
    peptide = event.get("peptide_id")
    if peptide in index["primary_peptides"]:
        return 0.4, "Watchlist proximity: primary target peptide."
    if peptide in index["configured_peptides"]:
        return 0.25, "Watchlist proximity: tracked peptide."
    return 0.1, "Watchlist proximity: no direct watchlist link."


def relevance_score(
    event: Mapping[str, Any],
    config: WatchConfig,
    *,
    now: datetime | None = None,
    index: dict[str, Any] | None = None,
) -> ScoredEvent:
    """Deterministic 0–100 relevance score with factual reasons."""

    now = now or datetime.now(timezone.utc)
    index = index or proximity_index(config)

    sev = _severity_weight(event.get("severity"))
    typ = _type_weight(event.get("event_type"))
    prox, prox_reason = _proximity_weight(event, index)
    rec, age_days = _recency_weight(event.get("created_at"), now)

    components = {
        "severity": round(W_SEVERITY * sev, 1),
        "event_type": round(W_TYPE * typ, 1),
        "proximity": round(W_PROXIMITY * prox, 1),
        "recency": round(W_RECENCY * rec, 1),
    }
    score = round(sum(components.values()), 1)

    reasons = [
        f"Severity: {(event.get('severity') or 'medium')} (curated tier).",
        f"Event type: {event.get('event_type') or 'unknown'} "
        f"(novelty weight {typ:.2f}).",
        prox_reason,
        ("Recency: not dated."
         if age_days is None else f"Recency: {age_days:.0f} day(s) old."),
    ]
    return ScoredEvent(score=score, components=components, score_reasons=reasons)


# --------------------------------------------------------------------------- #
# Briefing data contract
# --------------------------------------------------------------------------- #
def discoveries_rows(connection: sqlite3.Connection, limit: int = 30) -> list[dict[str, Any]]:
    """Non-watchlist SEC filers that disclosed a target peptide, freshest first.

    Fund/passive-holder filings are excluded. Shared by the `discoveries` CLI
    command, the briefing, and the API so there is one query.
    """

    rows = connection.execute(
        """
        SELECT company_name,
               COUNT(*) AS filings,
               COUNT(DISTINCT peptide_ids_json) AS peptide_sets,
               MAX(filing_date) AS latest,
               GROUP_CONCAT(DISTINCT filing_type) AS forms
        FROM company_documents
        WHERE json_extract(metadata_json, '$.discovery') = 1
          AND company_name IS NOT NULL
          AND COALESCE(filing_type, '') NOT LIKE 'NPORT%'
          AND COALESCE(filing_type, '') NOT LIKE 'N-CSR%'
          AND COALESCE(filing_type, '') NOT LIKE 'N-CEN%'
          AND COALESCE(filing_type, '') NOT LIKE '13F%'
          AND COALESCE(filing_type, '') NOT LIKE '497%'
          AND COALESCE(filing_type, '') NOT LIKE 'SC 13%'
        GROUP BY company_name
        ORDER BY latest DESC, filings DESC
        LIMIT ?
        """,
        (limit,),
    ).fetchall()
    return [
        {
            "company_name": name,
            "filings": filings,
            "peptide_sets": sets,
            "latest": latest,
            "forms": forms,
        }
        for name, filings, sets, latest, forms in rows
    ]


def _active_comment_periods(connection: sqlite3.Connection, limit: int = 20) -> list[dict[str, Any]]:
    rows = connection.execute(
        """
        SELECT title, url, document_number, publication_date, metadata_json
        FROM regulatory_documents
        WHERE source_id LIKE 'regulations%'
          AND json_extract(metadata_json, '$.open_for_comment') = 1
        ORDER BY publication_date DESC
        LIMIT ?
        """,
        (limit,),
    ).fetchall()
    out = []
    for title, url, docnum, posted, meta_json in rows:
        meta = json.loads(meta_json) if meta_json else {}
        out.append(
            {
                "title": title,
                "url": url,
                "docket_id": meta.get("docket_id") or docnum,
                "document_type": meta.get("document_type"),
                "comment_end_date": meta.get("comment_end_date") or None,
                "publication_date": posted,
            }
        )
    return out


def _active_shortages(connection: sqlite3.Connection, limit: int = 20) -> list[dict[str, Any]]:
    rows = connection.execute(
        """
        SELECT title, url, publication_date, metadata_json
        FROM regulatory_documents
        WHERE source_type = 'drug_shortage'
          AND lower(COALESCE(json_extract(metadata_json, '$.status'), '')) NOT LIKE '%resolv%'
        ORDER BY publication_date DESC
        LIMIT ?
        """,
        (limit,),
    ).fetchall()
    out = []
    for title, url, posted, meta_json in rows:
        meta = json.loads(meta_json) if meta_json else {}
        out.append(
            {
                "title": title,
                "url": url,
                "generic_name": meta.get("generic_name"),
                "status": meta.get("status"),
                "update_type": meta.get("update_type"),
                "company_name": meta.get("company_name"),
                "publication_date": posted,
            }
        )
    return out


def _source_health(connection: sqlite3.Connection, db_path: str | None) -> dict[str, Any]:
    from peptide_watch.runtime import ledger

    runs = ledger.list_runs(connection, limit=10)
    if not runs:
        return {"latest_run": None, "errors": {}, "skipped": {}, "recent_failed_runs": []}
    latest = runs[0]
    summary = latest["summary"] or {}
    return {
        "latest_run": {
            "run_id": latest["run_id"],
            "status": latest["status"],
            "started_at": latest["started_at"],
            "finished_at": latest["finished_at"],
            "tasks_by_status": summary.get("tasks_by_status", {}),
        },
        "errors": summary.get("errors", {}),
        "skipped": summary.get("skipped", {}),
        "recent_failed_runs": [r["run_id"] for r in runs if r["status"] == "failed"],
    }


def briefing(
    connection: sqlite3.Connection,
    config: WatchConfig,
    *,
    limit: int = 25,
    now: datetime | None = None,
    recent_days: int = 90,
) -> dict[str, Any]:
    """Build the ranked, compliant briefing dict — the shared data contract."""

    now = now or datetime.now(timezone.utc)
    index = proximity_index(config)

    cur = connection.cursor()
    cur.row_factory = sqlite3.Row
    cutoff = now.replace(microsecond=0).isoformat()
    candidate_rows = cur.execute(
        f"""
        SELECT {BRIEFING_EVENT_COLUMNS}
        FROM events
        WHERE created_at >= datetime(?, '-{int(recent_days)} days')
        ORDER BY created_at DESC
        LIMIT 1000
        """,
        (cutoff,),
    ).fetchall()

    scored = []
    for row in candidate_rows:
        event = dict(row)
        result = relevance_score(event, config, now=now, index=index)
        event["score"] = result.score
        event["score_components"] = result.components
        event["score_reasons"] = result.score_reasons
        scored.append(event)
    scored.sort(key=lambda e: e["score"], reverse=True)
    top_events = scored[:limit]

    immediate = sum(1 for e in scored if (e.get("severity") or "") in ("critical", "high"))
    discoveries = discoveries_rows(connection, limit=30)
    comment_periods = _active_comment_periods(connection)
    shortages = _active_shortages(connection)

    return {
        "schema_version": SCHEMA_VERSION,
        "generated_at": now.replace(microsecond=0).isoformat(),
        "disclaimers": dict(DISCLAIMERS),
        "counts": {
            "events_window": len(scored),
            "events_immediate": immediate,
            "events_digest": len(scored) - immediate,
            "discoveries": len(discoveries),
            "active_comment_periods": len(comment_periods),
            "active_shortages": len(shortages),
        },
        "top_events": top_events,
        "discoveries": discoveries,
        "active_comment_periods": comment_periods,
        "active_shortages": shortages,
        "source_health": _source_health(connection, None),
    }


# --------------------------------------------------------------------------- #
# Markdown rendering
# --------------------------------------------------------------------------- #
def render_briefing_markdown(data: Mapping[str, Any]) -> str:
    lines: list[str] = []
    lines.append(f"# Peptide-watch briefing — {data['generated_at']}")
    lines.append("")
    lines.append(data["disclaimers"]["global"])
    counts = data["counts"]
    lines.append("")
    lines.append(
        f"_{counts['events_immediate']} immediate / {counts['events_digest']} digest events, "
        f"{counts['discoveries']} discoveries, {counts['active_comment_periods']} open comment "
        f"period(s), {counts['active_shortages']} active shortage(s)._"
    )

    lines.append("\n## Top signals")
    if not data["top_events"]:
        lines.append("(none in window)")
    for i, e in enumerate(data["top_events"], 1):
        lines.append(
            f"{i}. **[{e['score']}] {e['title']}** — {e.get('severity', '')} / {e['event_type']}"
        )
        if e.get("what_changed"):
            lines.append(f"   {e['what_changed']}")
        lines.append(f"   _why ranked: {'; '.join(e.get('score_reasons', []))}_")

    lines.append("\n## Discovery queue (new non-watchlist filers)")
    if not data["discoveries"]:
        lines.append("(none)")
    for d in data["discoveries"][:15]:
        lines.append(
            f"- {d['company_name']} — {d['filings']} filing(s), latest {d.get('latest') or '?'} "
            f"({d.get('forms') or ''})"
        )

    lines.append("\n## Open comment periods")
    if not data["active_comment_periods"]:
        lines.append("(none)")
    for c in data["active_comment_periods"]:
        end = c.get("comment_end_date") or "?"
        lines.append(f"- {c['title']} — closes {end} ({c.get('docket_id') or ''})")
        lines.append(f"  {c['url']}")

    lines.append("\n## Active shortages")
    if not data["active_shortages"]:
        lines.append("(none)")
    for s in data["active_shortages"]:
        lines.append(f"- {s.get('generic_name') or s['title']} — {s.get('status') or ''}")

    health = data["source_health"]
    if health.get("latest_run"):
        run = health["latest_run"]
        lines.append("\n## Source health")
        lines.append(f"- latest run {run['run_id']}: {run['status']} {run['tasks_by_status']}")
        for src, msg in health.get("errors", {}).items():
            lines.append(f"  - error {src}: {msg}")

    lines.append("")
    lines.append(data["disclaimers"]["regulatory"])
    lines.append(data["disclaimers"]["microcap"])
    return "\n".join(lines)
