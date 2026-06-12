from pathlib import Path

import typer

from peptide_watch.claims import (
    CLAIM_STATUSES,
    ClaimCreate,
    add_claim,
    export_claims,
    list_claims,
    seed_claims_from_markdown,
    update_claim_status,
)
from peptide_watch.config import load_config
from peptide_watch.database import backup_db as backup_database
from peptide_watch.database import connect
from peptide_watch.database import init_db as initialize_database
from peptide_watch.runtime import ledger
from peptide_watch.runtime.scan import (
    ScanLocked,
    configure_json_logging,
    format_summary,
    run_scan,
)
from peptide_watch.sources.company_pages import (
    CompanyPageClient,
    export_company_page_documents_markdown,
    list_company_page_documents,
    scan_company_pages,
)
from peptide_watch.sources.clinicaltrials import (
    ClinicalTrialsClient,
    export_trials_markdown,
    list_trials,
    scan_clinicaltrials,
)
from peptide_watch.sources.fda import (
    FdaClient,
    export_fda_documents_markdown,
    list_fda_documents,
    scan_fda_sources,
)
from peptide_watch.sources.federal_register import (
    FederalRegisterClient,
    export_federal_register_documents_markdown,
    list_federal_register_documents,
    scan_federal_register,
)
from peptide_watch.sources.sec import (
    DEFAULT_SEC_FORMS,
    SecEdgarClient,
    export_sec_documents_markdown,
    list_sec_documents,
    scan_sec_filings,
)

app = typer.Typer(help="Peptide Stock Tracker CLI", no_args_is_help=True)
config_app = typer.Typer(help="Validate repository configuration.", no_args_is_help=True)
claims_app = typer.Typer(help="Manage claim registry records.", no_args_is_help=True)
clinicaltrials_app = typer.Typer(
    help="Scan and inspect official ClinicalTrials.gov records.",
    no_args_is_help=True,
)
fda_app = typer.Typer(help="Scan and inspect official FDA page/PDF sources.", no_args_is_help=True)
federal_register_app = typer.Typer(
    help="Scan and inspect official Federal Register notices.",
    no_args_is_help=True,
)
company_pages_app = typer.Typer(
    help="Scan and inspect public company IR/news/page sources.",
    no_args_is_help=True,
)
sec_app = typer.Typer(help="Scan and inspect public SEC EDGAR filings.", no_args_is_help=True)
runs_app = typer.Typer(help="Inspect tracked scan runs.", no_args_is_help=True)
app.add_typer(config_app, name="config")
app.add_typer(runs_app, name="runs")
app.add_typer(claims_app, name="claims")
app.add_typer(clinicaltrials_app, name="clinicaltrials")
app.add_typer(fda_app, name="fda")
app.add_typer(federal_register_app, name="federal-register")
app.add_typer(company_pages_app, name="company-pages")
app.add_typer(sec_app, name="sec")


@app.callback()
def main() -> None:
    """Peptide Stock Tracker command group."""


@app.command("init-db")
def init_db(
    db: Path = typer.Option(
        Path("data/watch.db"),
        "--db",
        help="SQLite database path to create or initialize.",
    ),
) -> None:
    """Initialize a SQLite database from schema/schema.sql."""

    initialized_path = initialize_database(db)
    typer.echo(f"Initialized SQLite database at {initialized_path}")


@app.command("scan")
def scan(
    db: Path = typer.Option(Path("data/watch.db"), "--db", help="SQLite database path."),
    config_dir: Path = typer.Option(Path("config"), "--config-dir", help="Config directory."),
    resume: bool = typer.Option(
        True,
        "--resume/--no-resume",
        help="Resume the latest interrupted run instead of starting a new one.",
    ),
    source: list[str] | None = typer.Option(
        None,
        "--source",
        help="Limit a new run to specific source families. Can be repeated.",
    ),
) -> None:
    """Run one tracked scan over all source families with failure isolation."""

    initialize_database(db)
    configure_json_logging()
    try:
        summary = run_scan(
            db,
            config_dir=config_dir,
            source_ids=source,
            resume=resume,
        )
    except ScanLocked as exc:
        typer.echo(f"Scan not started: {exc}", err=True)
        raise typer.Exit(code=1) from exc
    except ValueError as exc:
        typer.echo(f"Scan not started: {exc}", err=True)
        raise typer.Exit(code=1) from exc
    typer.echo(format_summary(summary))
    if summary.get("status") == "failed":
        raise typer.Exit(code=1)


@runs_app.command("list")
def runs_list(
    db: Path = typer.Option(Path("data/watch.db"), "--db", help="SQLite database path."),
    limit: int = typer.Option(20, "--limit", min=1, help="Maximum runs to list."),
) -> None:
    """List tracked scan runs, newest first."""

    connection = connect(db)
    try:
        records = ledger.list_runs(connection, limit=limit)
    finally:
        connection.close()
    typer.echo("| run_id | status | started_at | finished_at | sources | errors |")
    typer.echo("| --- | --- | --- | --- | --- | --- |")
    for record in records:
        summary = record["summary"] or {}
        typer.echo(
            f"| {record['run_id']} | {record['status']} | {record['started_at']} "
            f"| {record['finished_at'] or ''} | {summary.get('sources', '')} "
            f"| {len(summary.get('errors', {}))} |"
        )


@runs_app.command("show")
def runs_show(
    run_id: str = typer.Argument(..., help="Run id to inspect."),
    db: Path = typer.Option(Path("data/watch.db"), "--db", help="SQLite database path."),
) -> None:
    """Show one run with its per-source task states."""

    connection = connect(db)
    try:
        record = ledger.get_run(connection, run_id)
    finally:
        connection.close()
    if record is None:
        typer.echo(f"Run not found: {run_id}", err=True)
        raise typer.Exit(code=1)
    typer.echo(f"Run {record['run_id']}: {record['status']}")
    typer.echo(f"  started:  {record['started_at']}")
    typer.echo(f"  finished: {record['finished_at'] or '-'}")
    for task in record["tasks"]:
        counts = task["counts"] or {}
        details = ", ".join(f"{value} {key}" for key, value in counts.items()) or "-"
        typer.echo(
            f"  {task['source_id']}: {task['status']} (attempt {task['attempt']}) {details}"
        )
        if task["error"]:
            last_line = task["error"].strip().splitlines()[-1]
            typer.echo(f"    error: {last_line}")


@app.command("deliver")
def deliver(
    db: Path = typer.Option(Path("data/watch.db"), "--db", help="SQLite database path."),
    channel: str = typer.Option("console", "--channel", help="Delivery channel: console, file, webhook, or telegram."),
    outbox_dir: Path = typer.Option(
        Path("alerts_outbox"),
        "--outbox-dir",
        help="Directory for the file channel.",
    ),
) -> None:
    """Send pending immediate-tier events, batched per source per run."""

    from peptide_watch.alerts import deliver_immediate, get_channel

    initialize_database(db)
    try:
        target = get_channel(channel, directory=outbox_dir)
    except ValueError as exc:
        typer.echo(str(exc), err=True)
        raise typer.Exit(code=1) from exc
    connection = connect(db)
    try:
        result = deliver_immediate(connection, target)
    finally:
        connection.close()
    typer.echo(
        f"Delivered {result['events_sent']} event(s) in {result['messages_sent']} message(s); "
        f"{result['events_pending']} pending, {result['batches_failed']} batch(es) failed."
    )
    if result["batches_failed"]:
        raise typer.Exit(code=1)


@app.command("digest")
def digest(
    db: Path = typer.Option(Path("data/watch.db"), "--db", help="SQLite database path."),
    channel: str = typer.Option("console", "--channel", help="Delivery channel: console, file, webhook, or telegram."),
    outbox_dir: Path = typer.Option(
        Path("alerts_outbox"),
        "--outbox-dir",
        help="Directory for the file channel.",
    ),
    dry_run: bool = typer.Option(
        False,
        "--dry-run",
        help="Print the digest without marking events sent.",
    ),
) -> None:
    """Render pending digest-tier events (medium/low) and mark them sent."""

    from peptide_watch.alerts import build_digest, get_channel, mark_digest_sent

    initialize_database(db)
    try:
        target = get_channel(channel, directory=outbox_dir)
    except ValueError as exc:
        typer.echo(str(exc), err=True)
        raise typer.Exit(code=1) from exc
    connection = connect(db)
    try:
        text, event_ids = build_digest(connection, target.name)
        if dry_run:
            typer.echo(text)
            return
        target.send(text)
        mark_digest_sent(connection, target.name, event_ids)
    finally:
        connection.close()
    typer.echo(f"Digest delivered with {len(event_ids)} event(s).")


@app.command("replay")
def replay(
    db: Path = typer.Option(Path("data/watch.db"), "--db", help="SQLite database path."),
    config_dir: Path = typer.Option(Path("config"), "--config-dir", help="Config directory."),
    source: str = typer.Option(
        "clinicaltrials",
        "--source",
        help="Source family to replay (clinicaltrials has full snapshot history).",
    ),
    since: str | None = typer.Option(
        None,
        "--since",
        help="Only replay snapshots captured at or after this timestamp.",
    ),
    rebuild: bool = typer.Option(
        False,
        "--rebuild",
        help="Drop and rebuild the records table from snapshots before replaying.",
    ),
    deliver: bool = typer.Option(
        False,
        "--deliver",
        help="Allow replay events to be delivered instead of suppressed.",
    ),
) -> None:
    """Re-derive records and events from stored snapshots, with zero network."""

    from peptide_watch.replay import replay_clinicaltrials

    if source != "clinicaltrials":
        typer.echo(
            f"Replay for {source!r} is not available yet: raw payloads for that family "
            "are only captured from this version on (raw_blobs).",
            err=True,
        )
        raise typer.Exit(code=1)
    result = replay_clinicaltrials(
        db, config_dir=config_dir, since=since, rebuild=rebuild, deliver=deliver
    )
    typer.echo(
        f"Replay {result['run_id']}: {result['snapshots_replayed']} snapshots replayed, "
        f"{result['inserted']} inserted, {result['changed']} changed, "
        f"{result['events_created']} events created"
        + ("." if deliver else " (deliveries suppressed).")
    )


@app.command("verify")
def verify(
    db: Path = typer.Option(Path("data/watch.db"), "--db", help="SQLite database path."),
) -> None:
    """Re-hash stored raw payloads against their recorded checksums."""

    from peptide_watch.replay import verify_integrity

    result = verify_integrity(db)
    typer.echo(
        f"Verified {result['blobs_checked']} blob(s) and "
        f"{result['snapshots_checked']} snapshot(s): "
        f"{len(result['corrupted'])} corrupted."
    )
    for item in result["corrupted"]:
        typer.echo(f"  corrupted: {item}", err=True)
    if result["corrupted"]:
        raise typer.Exit(code=1)


@app.command("uspto-check")
def uspto_check(
    query: str = typer.Option('"BPC-157"', "--query", help="Search phrase to test with."),
) -> None:
    """Verify the USPTO API key and print the live response shape.

    Run this once after setting PEPTIDE_WATCH_USPTO_API_KEY; when it passes,
    the uspto_patents family joins the scheduled scan automatically.
    """

    import json as json_module

    from peptide_watch.sources.uspto import (
        USPTO_API_KEY_ENV,
        UsptoClient,
        _extract_records,
        api_key_present,
    )

    if not api_key_present():
        typer.echo(f"{USPTO_API_KEY_ENV} is not set; export the key first.", err=True)
        raise typer.Exit(code=1)
    client = UsptoClient()
    try:
        payload = client.raw_search(query)
    except Exception as exc:
        typer.echo(f"USPTO check failed: {exc}", err=True)
        raise typer.Exit(code=1) from exc
    records = _extract_records(payload)
    typer.echo(f"Top-level keys: {', '.join(payload.keys())}")
    typer.echo(f"Records extracted: {len(records)}")
    if records:
        record = records[0]
        typer.echo(f"First record keys: {', '.join(list(record.keys())[:20])}")
        # The two stock-relevant nested bags, shown in full; the noisy
        # eventDataBag/correspondence fields are omitted from the preview.
        for key in ("applicationMetaData", "assignmentBag", "recordAttorney"):
            if key in record:
                typer.echo(f"\n--- {key} ---")
                typer.echo(json_module.dumps(record[key], indent=1)[:1800])
    typer.echo(
        "\nUSPTO key works. The uspto_patents family now joins every scan run "
        "while the key is set (confirm with: peptide-watch list-adapters)."
    )


@app.command("discoveries")
def discoveries(
    db: Path = typer.Option(Path("data/watch.db"), "--db", help="SQLite database path."),
    limit: int = typer.Option(30, "--limit", min=1, help="Maximum companies to show."),
) -> None:
    """Rank non-watchlist companies found via SEC full-text — the gem-review queue.

    These are filers not on your watchlist that disclosed a target peptide.
    Promote the promising ones into config/companies.yaml.
    """

    from peptide_watch.relevance import discoveries_rows

    initialize_database(db)
    connection = connect(db)
    try:
        rows = discoveries_rows(connection, limit=limit)
    finally:
        connection.close()
    if not rows:
        typer.echo("No discoveries yet. Run a scan with the sec_fulltext family first.")
        return
    typer.echo("| company | filings | latest | forms |")
    typer.echo("| --- | --- | --- | --- |")
    for row in rows:
        typer.echo(
            f"| {row['company_name']} | {row['filings']} | {row['latest'] or ''} "
            f"| {row['forms'] or ''} |"
        )
    typer.echo(
        f"\n{len(rows)} non-watchlist filers disclosed a target peptide. "
        "Review and promote promising names to config/companies.yaml."
    )


@app.command("briefing")
def briefing_command(
    db: Path = typer.Option(Path("data/watch.db"), "--db", help="SQLite database path."),
    config_dir: Path = typer.Option(Path("config"), "--config-dir", help="Config directory."),
    output_format: str = typer.Option(
        "markdown", "--format", help="Output format: markdown or json."
    ),
    limit: int = typer.Option(25, "--limit", min=1, help="Maximum ranked events to include."),
    output: Path | None = typer.Option(None, "--output", help="Optional output file."),
) -> None:
    """Ranked factual snapshot of current public-source signals (markdown or JSON).

    The JSON form is the shared data contract for the dashboard API and the
    alert agent. It orders facts by signal strength; it issues no buy/sell calls.
    """

    import json as json_module

    from peptide_watch.relevance import briefing, render_briefing_markdown

    if output_format not in {"markdown", "json"}:
        raise typer.BadParameter("format must be 'markdown' or 'json'")
    initialize_database(db)
    config = load_config(config_dir)
    connection = connect(db)
    try:
        data = briefing(connection, config, limit=limit)
    finally:
        connection.close()
    rendered = (
        json_module.dumps(data, indent=2)
        if output_format == "json"
        else render_briefing_markdown(data)
    )
    if output is None:
        typer.echo(rendered)
        return
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(rendered, encoding="utf-8")
    typer.echo(f"Wrote briefing ({output_format}) to {output}")


@app.command("check-language")
def check_language_command(
    stdin: bool = typer.Option(False, "--stdin", help="Read text to check from stdin."),
    text: str | None = typer.Option(None, "--text", help="Text to check instead of stdin."),
) -> None:
    """Check text against the forbidden-language patterns (runtime compliance gate).

    The alert agent pipes its drafted briefing through this before sending so a
    runtime LLM output is held to the same rule as the source-code CI gate.
    Exits non-zero and prints each forbidden phrase if any are found.
    """

    import sys

    from peptide_watch.language_gate import check_text

    if text is None:
        if not stdin:
            typer.echo("Provide --text or pipe text with --stdin.", err=True)
            raise typer.Exit(code=2)
        text = sys.stdin.read()
    violations = check_text(text)
    if violations:
        for phrase in violations:
            typer.echo(f"forbidden language: {phrase!r}", err=True)
        typer.echo(f"{len(violations)} forbidden phrase(s) found.", err=True)
        raise typer.Exit(code=1)
    typer.echo("clean")


@app.command("serve")
def serve(
    db: Path = typer.Option(Path("data/watch.db"), "--db", help="SQLite database path."),
    config_dir: Path = typer.Option(Path("config"), "--config-dir", help="Config directory."),
    host: str = typer.Option("127.0.0.1", "--host", help="Bind host (localhost by default)."),
    port: int = typer.Option(8000, "--port", help="Bind port."),
    dashboard: Path | None = typer.Option(
        None,
        "--dashboard",
        help="Serve a built dashboard dir (default: dashboard/dist if it exists).",
    ),
) -> None:
    """Launch the read-only dashboard API (requires the [web] extra).

    If a built dashboard exists (dashboard/dist), it is served on the same port
    — one process, one port, no CORS. Localhost-bound; reach it via SSH tunnel.
    """

    try:
        import uvicorn

        from peptide_watch.web.app import create_app
    except ImportError as exc:
        typer.echo("Web dependencies missing. Install with: uv sync --extra web", err=True)
        raise typer.Exit(code=1) from exc
    initialize_database(db)
    dist = dashboard
    if dist is None:
        default_dist = Path("dashboard/dist")
        dist = default_dist if (default_dist / "index.html").exists() else None
    application = create_app(db_path=db, config_dir=config_dir, dashboard_dist=dist)
    if dist:
        typer.echo(f"Serving dashboard from {dist} + API at http://{host}:{port}")
    uvicorn.run(application, host=host, port=port)


@app.command("list-adapters")
def list_adapters() -> None:
    """List registered source-family adapters."""

    from peptide_watch.runtime.scan import SCANNER_REGISTRY

    for name in sorted(SCANNER_REGISTRY):
        doc = (SCANNER_REGISTRY[name].__doc__ or "").strip().splitlines()
        typer.echo(f"{name}: {doc[0] if doc else ''}")


@app.command("prune")
def prune_command(
    db: Path = typer.Option(Path("data/watch.db"), "--db", help="SQLite database path."),
    older_than_days: int = typer.Option(
        180, "--older-than-days", min=1, help="Delete delivered events/source rows older than this."
    ),
) -> None:
    """Prune old delivered events, deliveries, and source_documents.

    Snapshots and raw blobs are immutable (the replay/audit trail) and are
    never pruned — keep them via dated backups.
    """

    from peptide_watch.retention import prune

    deleted = prune(db, older_than_days=older_than_days)
    typer.echo(
        f"Pruned (older than {older_than_days}d): "
        + ", ".join(f"{count} {table}" for table, count in deleted.items())
    )


@app.command("status")
def status(
    db: Path = typer.Option(Path("data/watch.db"), "--db", help="SQLite database path."),
) -> None:
    """Health check: latest run, errors, and storage — for unattended monitoring."""

    from peptide_watch.retention import storage_report

    initialize_database(db)
    connection = connect(db)
    try:
        runs = ledger.list_runs(connection, limit=1)
        recent = ledger.list_runs(connection, limit=10)
    finally:
        connection.close()

    if not runs:
        typer.echo("No runs yet. Run `peptide-watch scan`.")
        raise typer.Exit(code=0)

    latest = runs[0]
    summary = latest["summary"] or {}
    errors = summary.get("errors", {})
    skipped = summary.get("skipped", {})
    typer.echo(f"Latest run:  {latest['run_id']}  [{latest['status']}]")
    typer.echo(f"  started:   {latest['started_at']}")
    typer.echo(f"  finished:  {latest['finished_at'] or '(running)'}")
    typer.echo(f"  sources:   {summary.get('tasks_by_status', {})}")
    if errors:
        for source_id, message in errors.items():
            typer.echo(f"  ERROR {source_id}: {message}")
    if skipped:
        for source_id, message in skipped.items():
            typer.echo(f"  SKIPPED {source_id}: {message}")

    failed_runs = [r["run_id"] for r in recent if r["status"] == "failed"]
    if failed_runs:
        typer.echo(f"  recent failed runs: {', '.join(failed_runs)}")

    report = storage_report(db)
    typer.echo(
        f"Storage: {report['events']} events, {report['deliveries']} deliveries, "
        f"{report['raw_blobs']} blobs ({report['raw_blob_bytes'] / 1e6:.1f} MB)"
    )
    # Non-zero exit if the latest run failed — lets cron/monitoring detect trouble.
    if latest["status"] == "failed":
        raise typer.Exit(code=1)


@app.command("backup-db")
def backup_db(
    db: Path = typer.Option(
        Path("data/watch.db"),
        "--db",
        help="SQLite database path to back up.",
    ),
    backups_dir: Path = typer.Option(
        Path("backups"),
        "--backups-dir",
        help="Directory to write dated backup files into.",
    ),
) -> None:
    """Write a consistent dated backup of the database via VACUUM INTO."""

    try:
        target = backup_database(db, backups_dir)
    except FileNotFoundError as exc:
        typer.echo(f"Backup failed: {exc}", err=True)
        raise typer.Exit(code=1) from exc
    typer.echo(f"Backed up {db} to {target}")


@config_app.command("check")
def config_check(
    config_dir: Path = typer.Option(Path("config"), "--config-dir", help="Config directory."),
) -> None:
    """Validate config, dry-run-instantiate clients, and verify source coverage."""

    from peptide_watch.coverage import UNCLAIMED, source_coverage
    from peptide_watch.sources.openfda import OpenFdaClient
    from peptide_watch.sources.openfda_shortages import OpenFdaShortageClient
    from peptide_watch.sources.pubmed import PubMedClient
    from peptide_watch.sources.regulations import RegulationsClient
    from peptide_watch.sources.sec_fulltext import SecFullTextClient

    try:
        config = load_config(config_dir)
    except Exception as exc:
        typer.echo(f"Config check failed: {exc}", err=True)
        raise typer.Exit(code=1) from exc

    clients = {
        "clinicaltrials": ClinicalTrialsClient,
        "fda": FdaClient,
        "federal_register": FederalRegisterClient,
        "company_pages": CompanyPageClient,
        "sec_edgar": SecEdgarClient,
        "sec_fulltext": SecFullTextClient,
        "pubmed": PubMedClient,
        "openfda_enforcement": OpenFdaClient,
        "openfda_shortages": OpenFdaShortageClient,
        "regulations_gov": RegulationsClient,
    }
    failures: list[str] = []
    for name, client_class in clients.items():
        try:
            client_class()
        except Exception as exc:
            failures.append(f"{name}: {exc}")
    if failures:
        for failure in failures:
            typer.echo(f"Client instantiation failed: {failure}", err=True)
        raise typer.Exit(code=1)

    coverage = source_coverage(config)
    by_family: dict[str, int] = {}
    for family in coverage.values():
        by_family[family] = by_family.get(family, 0) + 1
    unclaimed = sorted(sid for sid, family in coverage.items() if family == UNCLAIMED)
    typer.echo(
        "Config OK: "
        f"{len(config.peptides)} peptides, {len(config.companies)} companies, "
        f"{len(config.sources)} sources, {len(config.queries)} query groups, "
        f"{len(clients)} source clients instantiated."
    )
    typer.echo(
        "Source coverage: "
        + ", ".join(f"{family}={count}" for family, count in sorted(by_family.items()))
    )
    if unclaimed:
        typer.echo(
            f"Config check failed: no scanner claims these sources: {', '.join(unclaimed)}",
            err=True,
        )
        raise typer.Exit(code=1)


@claims_app.command("add")
def claims_add(
    text: str = typer.Option(..., "--text", help="Claim text to register."),
    db: Path = typer.Option(Path("data/watch.db"), "--db", help="SQLite database path."),
    source_url: str | None = typer.Option(None, "--source-url", help="Public source URL, if known."),
    source_type: str = typer.Option("external_report", "--source-type", help="Source type label."),
    source_label: str | None = typer.Option(None, "--source-label", help="Human-readable source label."),
    category: str | None = typer.Option(
        "external_report_claim",
        "--category",
        help="Claim category label.",
    ),
    company: str | None = typer.Option(None, "--company", help="Company name, if explicit."),
    peptide: str | None = typer.Option(None, "--peptide", help="Peptide id, if explicit."),
    confidence: str = typer.Option("low", "--confidence", help="Confidence label."),
    evidence: str | None = typer.Option(None, "--evidence", help="Evidence excerpt."),
    notes: str | None = typer.Option(None, "--notes", help="Reviewer notes."),
) -> None:
    """Add a claim. External-report claims are stored as needs_verification."""

    record, inserted = add_claim(
        db,
        ClaimCreate(
            claim_text=text,
            company_name=company,
            peptide_id=peptide,
            claim_category=category,
            source_type=source_type,
            source_label=source_label,
            source_url=source_url,
            confidence=confidence,
            evidence_excerpt=evidence,
            reviewer_notes=notes,
        ),
    )
    action = "Added" if inserted else "Already exists"
    typer.echo(f"{action} claim {record.id} with status {record.status}")


@claims_app.command("seed")
def claims_seed(
    db: Path = typer.Option(Path("data/watch.db"), "--db", help="SQLite database path."),
    file: Path = typer.Option(
        Path("docs/CLAIMS_TO_VERIFY.md"),
        "--file",
        help="Markdown seed file to import.",
    ),
) -> None:
    """Seed claims from docs/CLAIMS_TO_VERIFY.md without promoting them to confirmed."""

    result = seed_claims_from_markdown(db, file)
    typer.echo(
        f"Seeded {result.total} claims from {file} "
        f"({result.inserted} inserted, {result.skipped} existing)"
    )


@claims_app.command("list")
def claims_list(
    db: Path = typer.Option(Path("data/watch.db"), "--db", help="SQLite database path."),
    status: str | None = typer.Option(None, "--status", help="Filter by claim status."),
    review_queue: bool = typer.Option(False, "--review-queue", help="Show only claims needing review."),
    limit: int = typer.Option(100, "--limit", min=1, help="Maximum records to return."),
) -> None:
    """List claims as a markdown table."""

    records = list_claims(
        db,
        status=status,
        needs_review=True if review_queue else None,
        limit=limit,
    )
    typer.echo(export_claims(records, "markdown"))


@claims_app.command("export")
def claims_export(
    db: Path = typer.Option(Path("data/watch.db"), "--db", help="SQLite database path."),
    output_format: str = typer.Option(
        "markdown",
        "--format",
        help="Export format: markdown or csv.",
    ),
    status: str | None = typer.Option(None, "--status", help="Filter by claim status."),
    review_queue: bool = typer.Option(False, "--review-queue", help="Export only claims needing review."),
    limit: int = typer.Option(1000, "--limit", min=1, help="Maximum records to export."),
    output: Path | None = typer.Option(None, "--output", help="Optional output file."),
) -> None:
    """Export claims as markdown or CSV."""

    if output_format not in {"markdown", "csv"}:
        raise typer.BadParameter("format must be 'markdown' or 'csv'")
    records = list_claims(
        db,
        status=status,
        needs_review=True if review_queue else None,
        limit=limit,
    )
    exported = export_claims(records, output_format)  # type: ignore[arg-type]
    if output is None:
        typer.echo(exported)
        return
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(exported, encoding="utf-8")
    typer.echo(f"Exported {len(records)} claims to {output}")


@claims_app.command("update-status")
def claims_update_status(
    claim_id: int = typer.Argument(..., help="Claim id to update."),
    status: str = typer.Argument(..., help=f"New status. Allowed: {', '.join(sorted(CLAIM_STATUSES))}"),
    db: Path = typer.Option(Path("data/watch.db"), "--db", help="SQLite database path."),
    notes: str | None = typer.Option(None, "--notes", help="Reviewer notes."),
) -> None:
    """Update a claim verification status after manual review."""

    record = update_claim_status(db, claim_id, status, reviewer_notes=notes)
    typer.echo(f"Updated claim {record.id} to {record.status}")


@clinicaltrials_app.command("scan")
def clinicaltrials_scan(
    db: Path = typer.Option(Path("data/watch.db"), "--db", help="SQLite database path."),
    config_dir: Path = typer.Option(Path("config"), "--config-dir", help="Config directory."),
    nct: list[str] | None = typer.Option(
        None,
        "--nct",
        help="Specific NCT ID to fetch. Can be repeated.",
    ),
    query: list[str] | None = typer.Option(
        None,
        "--query",
        help="Specific search query term. Can be repeated.",
    ),
    aliases: bool = typer.Option(
        True,
        "--aliases/--no-aliases",
        help="Search configured peptide aliases.",
    ),
    known_ncts: bool = typer.Option(
        True,
        "--known-ncts/--no-known-ncts",
        help="Fetch NCT IDs found in config sources and query config.",
    ),
    page_size: int = typer.Option(25, "--page-size", min=1, max=1000, help="API page size."),
    max_pages: int = typer.Option(1, "--max-pages", min=1, help="Maximum API pages per query."),
    rate_limit_seconds: float = typer.Option(
        1.0,
        "--rate-limit-seconds",
        min=0.0,
        help="Delay between API requests.",
    ),
) -> None:
    """Fetch official ClinicalTrials.gov records and create change events."""

    result = scan_clinicaltrials(
        db,
        config_dir=config_dir,
        client=ClinicalTrialsClient(rate_limit_seconds=rate_limit_seconds),
        nct_ids=nct or [],
        query_terms=query or [],
        include_alias_queries=aliases,
        include_known_ncts=known_ncts,
        page_size=page_size,
        max_pages=max_pages,
    )
    typer.echo(
        "ClinicalTrials.gov scan complete: "
        f"{result.fetched} fetched, {result.stored} stored, "
        f"{result.inserted} inserted, {result.changed} changed, "
        f"{result.events_created} events created."
    )


@clinicaltrials_app.command("list")
def clinicaltrials_list(
    db: Path = typer.Option(Path("data/watch.db"), "--db", help="SQLite database path."),
    limit: int = typer.Option(100, "--limit", min=1, help="Maximum records to list."),
) -> None:
    """List stored ClinicalTrials.gov records."""

    typer.echo(export_trials_markdown(list_trials(db, limit=limit)))


@fda_app.command("scan")
def fda_scan(
    db: Path = typer.Option(Path("data/watch.db"), "--db", help="SQLite database path."),
    config_dir: Path = typer.Option(Path("config"), "--config-dir", help="Config directory."),
    source_id: list[str] | None = typer.Option(
        None,
        "--source-id",
        help="Specific configured FDA source id. Can be repeated.",
    ),
    rate_limit_seconds: float = typer.Option(
        0.2,
        "--rate-limit-seconds",
        min=0.0,
        help="Delay between FDA source requests.",
    ),
) -> None:
    """Fetch official FDA PCAC, 503A, and safety-risk page/PDF sources."""

    result = scan_fda_sources(
        db,
        config_dir=config_dir,
        client=FdaClient(rate_limit_seconds=rate_limit_seconds),
        source_ids=source_id,
    )
    typer.echo(
        "FDA scan complete: "
        f"{result.fetched} fetched, {result.stored} stored, "
        f"{result.inserted} inserted, {result.changed} changed, "
        f"{result.events_created} events created."
    )


@fda_app.command("list")
def fda_list(
    db: Path = typer.Option(Path("data/watch.db"), "--db", help="SQLite database path."),
    limit: int = typer.Option(100, "--limit", min=1, help="Maximum records to list."),
) -> None:
    """List stored FDA regulatory documents."""

    typer.echo(export_fda_documents_markdown(list_fda_documents(db, limit=limit)))


@federal_register_app.command("scan")
def federal_register_scan(
    db: Path = typer.Option(Path("data/watch.db"), "--db", help="SQLite database path."),
    config_dir: Path = typer.Option(Path("config"), "--config-dir", help="Config directory."),
    query: list[str] | None = typer.Option(
        None,
        "--query",
        help="Specific Federal Register search query. Can be repeated.",
    ),
    per_page: int = typer.Option(20, "--per-page", min=1, max=1000, help="Results per query."),
    rate_limit_seconds: float = typer.Option(
        0.2,
        "--rate-limit-seconds",
        min=0.0,
        help="Delay between Federal Register API requests.",
    ),
) -> None:
    """Search official Federal Register FDA notices and store matches."""

    result = scan_federal_register(
        db,
        config_dir=config_dir,
        client=FederalRegisterClient(rate_limit_seconds=rate_limit_seconds),
        queries=query,
        per_page=per_page,
    )
    typer.echo(
        "Federal Register scan complete: "
        f"{result.fetched} fetched, {result.stored} stored, "
        f"{result.inserted} inserted, {result.changed} changed, "
        f"{result.events_created} events created."
    )


@federal_register_app.command("list")
def federal_register_list(
    db: Path = typer.Option(Path("data/watch.db"), "--db", help="SQLite database path."),
    limit: int = typer.Option(100, "--limit", min=1, help="Maximum records to list."),
) -> None:
    """List stored Federal Register regulatory notices."""

    typer.echo(
        export_federal_register_documents_markdown(
            list_federal_register_documents(db, limit=limit)
        )
    )


@company_pages_app.command("scan")
def company_pages_scan(
    db: Path = typer.Option(Path("data/watch.db"), "--db", help="SQLite database path."),
    config_dir: Path = typer.Option(Path("config"), "--config-dir", help="Config directory."),
    source_id: list[str] | None = typer.Option(
        None,
        "--source-id",
        help="Specific configured company/news source id. Can be repeated.",
    ),
    rate_limit_seconds: float = typer.Option(
        0.2,
        "--rate-limit-seconds",
        min=0.0,
        help="Delay between public page requests.",
    ),
) -> None:
    """Fetch public company IR/news/page sources and create review events."""

    result = scan_company_pages(
        db,
        config_dir=config_dir,
        client=CompanyPageClient(rate_limit_seconds=rate_limit_seconds),
        source_ids=source_id,
    )
    typer.echo(
        "Company page scan complete: "
        f"{result.fetched} fetched, {result.stored} stored, "
        f"{result.inserted} inserted, {result.changed} changed, "
        f"{result.events_created} events created."
    )


@company_pages_app.command("list")
def company_pages_list(
    db: Path = typer.Option(Path("data/watch.db"), "--db", help="SQLite database path."),
    limit: int = typer.Option(100, "--limit", min=1, help="Maximum records to list."),
) -> None:
    """List stored public company page/news documents."""

    typer.echo(export_company_page_documents_markdown(list_company_page_documents(db, limit=limit)))


@sec_app.command("scan")
def sec_scan(
    db: Path = typer.Option(Path("data/watch.db"), "--db", help="SQLite database path."),
    config_dir: Path = typer.Option(Path("config"), "--config-dir", help="Config directory."),
    company_id: list[str] | None = typer.Option(
        None,
        "--company-id",
        help="Configured company id to scan. Can be repeated.",
    ),
    ticker: list[str] | None = typer.Option(
        None,
        "--ticker",
        help="Ticker to scan from configured companies. Can be repeated.",
    ),
    form: list[str] | None = typer.Option(
        None,
        "--form",
        help=(
            "SEC filing form to include. Can be repeated. "
            f"Default: {', '.join(DEFAULT_SEC_FORMS)}."
        ),
    ),
    max_filings: int = typer.Option(
        3,
        "--max-filings",
        min=1,
        help="Maximum recent filings to fetch per company.",
    ),
    rate_limit_seconds: float = typer.Option(
        0.2,
        "--rate-limit-seconds",
        min=0.0,
        help="Delay between SEC requests.",
    ),
) -> None:
    """Fetch recent public SEC filings and create review events for matched terms."""

    result = scan_sec_filings(
        db,
        config_dir=config_dir,
        client=SecEdgarClient(rate_limit_seconds=rate_limit_seconds),
        company_ids=company_id,
        tickers=ticker,
        forms=form,
        max_filings=max_filings,
    )
    typer.echo(
        "SEC EDGAR scan complete: "
        f"{result.fetched} fetched, {result.stored} stored, "
        f"{result.inserted} inserted, {result.changed} changed, "
        f"{result.events_created} events created."
    )


@sec_app.command("list")
def sec_list(
    db: Path = typer.Option(Path("data/watch.db"), "--db", help="SQLite database path."),
    limit: int = typer.Option(100, "--limit", min=1, help="Maximum records to list."),
) -> None:
    """List stored SEC EDGAR filing documents."""

    typer.echo(export_sec_documents_markdown(list_sec_documents(db, limit=limit)))
