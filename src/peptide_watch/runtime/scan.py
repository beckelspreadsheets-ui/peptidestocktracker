"""Scan orchestrator: one tracked run over all source families with failure isolation."""

from __future__ import annotations

import fcntl
import json
import logging
import traceback
from pathlib import Path
from typing import Any, Callable, Mapping

from peptide_watch.database import connect
from peptide_watch.runtime import ledger

logger = logging.getLogger("peptide_watch.scan")

COUNT_FIELDS = ("fetched", "stored", "inserted", "changed", "events_created")
CIRCUIT_BREAKER_THRESHOLD = 3
MAX_COOLDOWN_RUNS = 16
LOCKFILE_NAME = "peptide_watch.lock"

Scanner = Callable[[Path, Path, str], Any]

SCANNER_REGISTRY: dict[str, Scanner] = {}


class ScanLocked(RuntimeError):
    """Another scan already holds the lockfile."""


def register_scanner(name: str) -> Callable[[Scanner], Scanner]:
    """Register a source-family scan entrypoint under a stable id.

    A new source family is added by writing its scan function and
    registering it here — the scan loop, ledger, and CLI pick it up.
    """

    def decorator(func: Scanner) -> Scanner:
        if name in SCANNER_REGISTRY:
            raise ValueError(f"scanner already registered: {name}")
        SCANNER_REGISTRY[name] = func
        return func

    return decorator


@register_scanner("clinicaltrials")
def _scan_clinicaltrials(db_path: Path, config_dir: Path, run_id: str) -> Any:
    """Official ClinicalTrials.gov API v2 records for configured aliases and NCT IDs."""
    from peptide_watch.sources.clinicaltrials import scan_clinicaltrials

    return scan_clinicaltrials(db_path, config_dir=config_dir, run_id=run_id)


@register_scanner("fda")
def _scan_fda(db_path: Path, config_dir: Path, run_id: str) -> Any:
    """Official FDA PCAC, 503A, and safety-risk page/PDF sources."""
    from peptide_watch.sources.fda import scan_fda_sources

    return scan_fda_sources(db_path, config_dir=config_dir, run_id=run_id)


@register_scanner("federal_register")
def _scan_federal_register(db_path: Path, config_dir: Path, run_id: str) -> Any:
    """Official Federal Register FDA notices for configured queries."""
    from peptide_watch.sources.federal_register import scan_federal_register

    return scan_federal_register(db_path, config_dir=config_dir, run_id=run_id)


@register_scanner("company_pages")
def _scan_company_pages(db_path: Path, config_dir: Path, run_id: str) -> Any:
    """Public company IR/news/page sources from config."""
    from peptide_watch.sources.company_pages import scan_company_pages

    return scan_company_pages(db_path, config_dir=config_dir, run_id=run_id)


@register_scanner("sec_edgar")
def _scan_sec(db_path: Path, config_dir: Path, run_id: str) -> Any:
    """Recent public SEC EDGAR filings for configured companies."""
    from peptide_watch.sources.sec import scan_sec_filings

    return scan_sec_filings(db_path, config_dir=config_dir, run_id=run_id)


DEFAULT_SCANNERS: dict[str, Scanner] = SCANNER_REGISTRY


class JsonLogFormatter(logging.Formatter):
    """One JSON object per line with run/source context bound in."""

    def format(self, record: logging.LogRecord) -> str:
        payload: dict[str, Any] = {
            "ts": self.formatTime(record, "%Y-%m-%dT%H:%M:%S%z"),
            "level": record.levelname,
            "logger": record.name,
            "message": record.getMessage(),
        }
        for key in ("run_id", "source_id", "event", "status", "attempt"):
            value = getattr(record, key, None)
            if value is not None:
                payload[key] = value
        if record.exc_info:
            payload["exception"] = self.formatException(record.exc_info)
        return json.dumps(payload)


def configure_json_logging(level: int = logging.INFO) -> None:
    handler = logging.StreamHandler()
    handler.setFormatter(JsonLogFormatter())
    root = logging.getLogger("peptide_watch")
    root.handlers = [handler]
    root.setLevel(level)
    root.propagate = False


def cooldown_runs(consecutive_errors: int) -> int:
    """Exponential cool-down once the breaker trips: 1, 2, 4, ... capped."""

    return min(2 ** (consecutive_errors - CIRCUIT_BREAKER_THRESHOLD), MAX_COOLDOWN_RUNS)


def run_scan(
    db_path: str | Path,
    *,
    config_dir: str | Path = "config",
    scanners: Mapping[str, Scanner] | None = None,
    source_ids: list[str] | None = None,
    resume: bool = True,
) -> dict[str, Any]:
    """Execute one tracked scan run; returns the run summary.

    Sources fail independently: an exception in one scanner marks its task
    'error' and the run continues. Only KeyboardInterrupt/SystemExit abort,
    leaving the run 'interrupted' for the next invocation to resume.
    """

    db = Path(db_path)
    available = dict(scanners if scanners is not None else DEFAULT_SCANNERS)
    if source_ids:
        unknown = set(source_ids) - set(available)
        if unknown:
            raise ValueError(f"unknown source ids: {', '.join(sorted(unknown))}")
        available = {key: available[key] for key in source_ids}

    lock_path = db.parent / LOCKFILE_NAME
    lock_path.parent.mkdir(parents=True, exist_ok=True)
    lock_file = open(lock_path, "w")
    try:
        try:
            fcntl.flock(lock_file, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except OSError as exc:
            raise ScanLocked(f"another scan holds {lock_path}") from exc

        connection = connect(db)
        try:
            return _run_scan_locked(connection, db, Path(config_dir), available, resume)
        finally:
            connection.close()
    finally:
        lock_file.close()


def _run_scan_locked(
    connection: Any,
    db: Path,
    config_dir: Path,
    scanners: dict[str, Scanner],
    resume: bool,
) -> dict[str, Any]:
    interrupted = ledger.mark_interrupted_runs(connection)
    for run_id in interrupted:
        logger.warning("marked stale run interrupted", extra={"run_id": run_id})

    run_id = None
    if resume:
        run_id = ledger.latest_interrupted_run(connection)
    if run_id is not None:
        task_ids = ledger.resume_run(connection, run_id)
        logger.info(
            "resuming interrupted run",
            extra={"run_id": run_id, "event": "resume", "status": f"{len(task_ids)} tasks left"},
        )
    else:
        task_ids = list(scanners)
        run_id = ledger.create_run(connection, task_ids)
        logger.info("run started", extra={"run_id": run_id, "event": "run_started"})

    try:
        for source_id in task_ids:
            _execute_task(connection, db, config_dir, scanners, run_id, source_id)
    except (KeyboardInterrupt, SystemExit):
        ledger.finish_run(connection, run_id, "interrupted", ledger.run_summary(connection, run_id))
        logger.warning("run interrupted", extra={"run_id": run_id, "event": "run_interrupted"})
        raise

    summary = ledger.run_summary(connection, run_id)
    status = "completed" if summary["tasks_by_status"].get("done") else "failed"
    if summary["sources"] == summary["tasks_by_status"].get("skipped", 0):
        status = "completed"
    ledger.finish_run(connection, run_id, status, summary)
    logger.info("run finished", extra={"run_id": run_id, "event": "run_finished", "status": status})
    summary["status"] = status
    return summary


def _execute_task(
    connection: Any,
    db: Path,
    config_dir: Path,
    scanners: dict[str, Scanner],
    run_id: str,
    source_id: str,
) -> None:
    context = {"run_id": run_id, "source_id": source_id}

    scanner = scanners.get(source_id)
    if scanner is None:
        ledger.finish_task(
            connection, run_id, source_id, "skipped", error="no scanner registered"
        )
        logger.warning("task skipped: no scanner registered", extra=context)
        return

    errors, skips = ledger.failure_streak(connection, source_id)
    if errors >= CIRCUIT_BREAKER_THRESHOLD and skips < cooldown_runs(errors):
        reason = (
            f"circuit breaker open: {errors} consecutive failures; "
            f"cooling down ({skips + 1}/{cooldown_runs(errors)} runs)"
        )
        ledger.finish_task(connection, run_id, source_id, "skipped", error=reason)
        logger.warning("task skipped: %s", reason, extra=context)
        return

    ledger.start_task(connection, run_id, source_id)
    logger.info("task started", extra={**context, "event": "task_started"})
    try:
        result = scanner(db, config_dir, run_id)
    except (KeyboardInterrupt, SystemExit):
        ledger.finish_task(connection, run_id, source_id, "error", error="interrupted")
        raise
    except Exception:
        ledger.finish_task(
            connection, run_id, source_id, "error", error=traceback.format_exc()
        )
        logger.exception("task failed", extra={**context, "event": "task_failed"})
        return

    counts = {field: int(getattr(result, field, 0) or 0) for field in COUNT_FIELDS}
    entry_errors = list(getattr(result, "errors", []) or [])
    if entry_errors:
        counts["source_errors"] = len(entry_errors)
        logger.warning(
            "task finished with %d per-entry errors: %s",
            len(entry_errors),
            "; ".join(entry_errors[:3]),
            extra={**context, "event": "task_partial_errors"},
        )
    ledger.finish_task(connection, run_id, source_id, "done", counts=counts)
    logger.info(
        "task done",
        extra={**context, "event": "task_done", "status": json.dumps(counts)},
    )


def format_summary(summary: dict[str, Any]) -> str:
    """Human-readable epilogue for the CLI; reusable as a digest header."""

    by_status = summary["tasks_by_status"]
    totals = summary["totals"]
    lines = [
        f"Run {summary['run_id']} {summary.get('status', '')}".rstrip() + ":",
        "  sources: "
        + ", ".join(f"{count} {status}" for status, count in sorted(by_status.items())),
    ]
    if totals:
        lines.append(
            "  totals: "
            + ", ".join(f"{totals.get(field, 0)} {field}" for field in COUNT_FIELDS)
        )
    for source_id, message in summary.get("errors", {}).items():
        lines.append(f"  error {source_id}: {message}")
    for source_id, message in summary.get("skipped", {}).items():
        lines.append(f"  skipped {source_id}: {message}")
    return "\n".join(lines)
