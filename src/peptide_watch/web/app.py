"""Read-only FastAPI app over data/watch.db.

Localhost-bound, single-operator. Config is loaded once at startup; every request
gets a fresh read-only SQLite connection so the API can never write/migrate the
DB the cron scanner owns. Handlers are sync (sqlite runs in the threadpool).
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

from fastapi import Depends, FastAPI, HTTPException, Query
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse

from peptide_watch.config import load_config
from peptide_watch.database import connect_readonly
from peptide_watch.relevance import DISCLAIMERS, briefing, discoveries_rows
from peptide_watch.runtime import ledger
from peptide_watch.web import queries

DEFAULT_CORS = ["http://localhost:3000", "http://127.0.0.1:3000"]


def create_app(
    *,
    db_path: str | Path = "data/watch.db",
    config_dir: str | Path = "config",
    cors_origins: list[str] | None = None,
    dashboard_dist: str | Path | None = None,
) -> FastAPI:
    db_path = Path(db_path)
    config = load_config(config_dir)  # fail fast if config is broken
    dist = Path(dashboard_dist).resolve() if dashboard_dist else None

    app = FastAPI(title="peptide-watch", version="1.0", docs_url="/api/docs")
    # Private localhost tool: allow any localhost/127.0.0.1 port (dev server,
    # preview, reverse proxy) so the dashboard origin port never matters.
    app.add_middleware(
        CORSMiddleware,
        allow_origins=cors_origins or [],
        allow_origin_regex=r"http://(localhost|127\.0\.0\.1)(:\d+)?",
        allow_methods=["GET"],
        allow_headers=["*"],
    )
    app.state.db_path = db_path
    app.state.config = config

    def get_db():
        connection = connect_readonly(app.state.db_path)
        try:
            yield connection
        finally:
            connection.close()

    def with_disclaimers(payload: dict[str, Any]) -> dict[str, Any]:
        payload.setdefault("disclaimers", dict(DISCLAIMERS))
        return payload

    # ----- health & config -------------------------------------------------- #
    @app.get("/api/health")
    def health(db=Depends(get_db)) -> dict[str, Any]:
        runs = ledger.list_runs(db, limit=1)
        return {
            "status": "ok",
            "db_ok": True,
            "counts": queries.health_counts(db),
            "latest_run": runs[0] if runs else None,
        }

    @app.get("/api/config/peptides")
    def config_peptides() -> list[dict[str, Any]]:
        return [p.model_dump() for p in app.state.config.peptides]

    @app.get("/api/config/companies")
    def config_companies() -> list[dict[str, Any]]:
        return [c.model_dump() for c in app.state.config.companies]

    @app.get("/api/config/sources")
    def config_sources() -> dict[str, Any]:
        return {sid: s.model_dump() for sid, s in app.state.config.sources.items()}

    @app.get("/api/watchlist")
    def watchlist() -> list[dict[str, Any]]:
        peptide_names = {p.id: p.name for p in app.state.config.peptides}
        out = []
        for c in app.state.config.companies:
            out.append(
                {
                    "id": c.id,
                    "name": c.name,
                    "ticker": c.ticker,
                    "exchange": c.exchange,
                    "tier": c.tier,
                    "public_private": c.public_private,
                    "liquidity_risk": c.liquidity_risk,
                    "relationship": c.relationship,
                    "confidence": c.confidence,
                    "peptides": [peptide_names.get(p, p) for p in c.peptides],
                }
            )
        return out

    # ----- events ----------------------------------------------------------- #
    @app.get("/api/events")
    def events(
        db=Depends(get_db),
        q: str | None = None,
        peptide: str | None = None,
        severity: str | None = None,
        confidence: str | None = None,
        source_type: str | None = None,
        event_type: str | None = None,
        date_from: str | None = None,
        date_to: str | None = None,
        review_status: str | None = None,
        limit: int = Query(50, ge=1, le=200),
        offset: int = Query(0, ge=0),
    ) -> dict[str, Any]:
        filters = {
            "q": q,
            "peptide": peptide,
            "severity": severity,
            "confidence": confidence,
            "source_type": source_type,
            "event_type": event_type,
            "date_from": date_from,
            "date_to": date_to,
            "review_status": review_status,
        }
        result = queries.list_events(db, filters=filters, limit=limit, offset=offset)
        return with_disclaimers(result)

    @app.get("/api/events/{event_id}")
    def event_detail(event_id: int, db=Depends(get_db)) -> dict[str, Any]:
        event = queries.get_event(db, event_id)
        if event is None:
            raise HTTPException(status_code=404, detail="event not found")
        return with_disclaimers({"event": event})

    # ----- briefing / discoveries / health --------------------------------- #
    @app.get("/api/briefing")
    def briefing_endpoint(
        db=Depends(get_db), limit: int = Query(25, ge=1, le=100)
    ) -> dict[str, Any]:
        return briefing(db, app.state.config, limit=limit)

    @app.get("/api/discoveries")
    def discoveries(
        db=Depends(get_db), limit: int = Query(30, ge=1, le=200)
    ) -> dict[str, Any]:
        return with_disclaimers({"items": discoveries_rows(db, limit=limit)})

    @app.get("/api/source-health")
    def source_health(db=Depends(get_db)) -> list[dict[str, Any]]:
        return queries.source_health(db)

    @app.get("/api/job-runs")
    def job_runs(
        db=Depends(get_db),
        run_id: str | None = None,
        limit: int = Query(20, ge=1, le=100),
    ) -> Any:
        if run_id:
            run = ledger.get_run(db, run_id)
            if run is None:
                raise HTTPException(status_code=404, detail="run not found")
            return run
        return ledger.list_runs(db, limit=limit)

    # ----- optional: serve the built dashboard on the same origin ---------- #
    # Registered LAST so it never shadows /api/*. Serves the static file if it
    # exists, else index.html (SPA fallback for client routes like /events).
    if dist and (dist / "index.html").exists():

        @app.get("/{full_path:path}", include_in_schema=False)
        def spa(full_path: str) -> FileResponse:
            candidate = (dist / full_path).resolve()
            if full_path and dist in candidate.parents and candidate.is_file():
                return FileResponse(candidate)
            return FileResponse(dist / "index.html")

    return app
