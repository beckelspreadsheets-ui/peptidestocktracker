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
from peptide_watch.database import init_db as initialize_database
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
        0.2,
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
