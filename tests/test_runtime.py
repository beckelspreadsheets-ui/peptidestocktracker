import fcntl
from pathlib import Path
from types import SimpleNamespace

import pytest
from typer.testing import CliRunner

from peptide_watch.cli import app
from peptide_watch.database import connect, init_db
from peptide_watch.runtime import ledger
from peptide_watch.runtime.scan import (
    LOCKFILE_NAME,
    ScanLocked,
    cooldown_runs,
    format_summary,
    run_scan,
)

ROOT = Path(__file__).resolve().parents[1]
CONFIG_DIR = ROOT / "config"


def _result(**overrides):
    counts = {"fetched": 1, "stored": 1, "inserted": 1, "changed": 0, "events_created": 0}
    counts.update(overrides)
    return SimpleNamespace(**counts)


class CountingScanner:
    def __init__(self, exception: BaseException | None = None):
        self.calls = 0
        self.exception = exception

    def __call__(self, db_path, config_dir, run_id):
        self.calls += 1
        if self.exception is not None:
            raise self.exception
        return _result()


def test_failing_source_does_not_abort_run(tmp_path) -> None:
    db_path = init_db(tmp_path / "watch.db")
    good = CountingScanner()
    bad = CountingScanner(ValueError("boom"))
    other = CountingScanner()

    summary = run_scan(
        db_path,
        config_dir=CONFIG_DIR,
        scanners={"good": good, "bad": bad, "other": other},
    )

    assert summary["status"] == "completed"
    assert summary["tasks_by_status"] == {"done": 2, "error": 1}
    assert "bad" in summary["errors"]
    assert "boom" in summary["errors"]["bad"]
    assert good.calls == 1 and other.calls == 1


def test_interrupt_marks_run_interrupted_and_resume_skips_done_tasks(tmp_path) -> None:
    db_path = init_db(tmp_path / "watch.db")
    first = CountingScanner()
    crasher = CountingScanner(KeyboardInterrupt())
    last = CountingScanner()
    scanners = {"first": first, "crasher": crasher, "last": last}

    with pytest.raises(KeyboardInterrupt):
        run_scan(db_path, config_dir=CONFIG_DIR, scanners=scanners)

    connection = connect(db_path)
    try:
        runs = ledger.list_runs(connection)
    finally:
        connection.close()
    assert runs[0]["status"] == "interrupted"
    run_id = runs[0]["run_id"]

    crasher.exception = None
    summary = run_scan(db_path, config_dir=CONFIG_DIR, scanners=scanners, resume=True)

    assert summary["run_id"] == run_id
    assert summary["status"] == "completed"
    assert first.calls == 1  # finished task is not re-executed
    assert crasher.calls == 2 and last.calls == 1


def test_no_resume_starts_fresh_run(tmp_path) -> None:
    db_path = init_db(tmp_path / "watch.db")
    crasher = CountingScanner(KeyboardInterrupt())
    scanners = {"crasher": crasher}

    with pytest.raises(KeyboardInterrupt):
        run_scan(db_path, config_dir=CONFIG_DIR, scanners=scanners)

    crasher.exception = None
    summary = run_scan(db_path, config_dir=CONFIG_DIR, scanners=scanners, resume=False)

    connection = connect(db_path)
    try:
        runs = ledger.list_runs(connection)
    finally:
        connection.close()
    assert len(runs) == 2
    assert summary["run_id"] != runs[-1]["run_id"]
    assert runs[-1]["status"] == "interrupted"  # old run stays interrupted


def test_circuit_breaker_skips_after_three_failures_then_retries(tmp_path) -> None:
    db_path = init_db(tmp_path / "watch.db")
    flaky = CountingScanner(RuntimeError("down"))
    scanners = {"flaky": flaky}

    for _ in range(3):
        summary = run_scan(db_path, config_dir=CONFIG_DIR, scanners=scanners, resume=False)
        assert summary["tasks_by_status"] == {"error": 1}
    assert flaky.calls == 3

    skipped = run_scan(db_path, config_dir=CONFIG_DIR, scanners=scanners, resume=False)
    assert skipped["tasks_by_status"] == {"skipped": 1}
    assert "circuit breaker" in skipped["skipped"]["flaky"]
    assert flaky.calls == 3  # not attempted while cooling down

    # cool-down of one run served; the breaker allows a retry, which succeeds
    flaky.exception = None
    retried = run_scan(db_path, config_dir=CONFIG_DIR, scanners=scanners, resume=False)
    assert retried["tasks_by_status"] == {"done": 1}
    assert flaky.calls == 4


def test_cooldown_grows_exponentially() -> None:
    assert cooldown_runs(3) == 1
    assert cooldown_runs(4) == 2
    assert cooldown_runs(5) == 4
    assert cooldown_runs(20) == 16


def test_concurrent_scan_is_rejected_by_lockfile(tmp_path) -> None:
    db_path = init_db(tmp_path / "watch.db")
    lock_path = db_path.parent / LOCKFILE_NAME
    holder = open(lock_path, "w")
    try:
        fcntl.flock(holder, fcntl.LOCK_EX | fcntl.LOCK_NB)
        with pytest.raises(ScanLocked):
            run_scan(db_path, config_dir=CONFIG_DIR, scanners={"x": CountingScanner()})
    finally:
        holder.close()


def test_unknown_source_filter_is_rejected(tmp_path) -> None:
    db_path = init_db(tmp_path / "watch.db")

    with pytest.raises(ValueError, match="unknown source ids"):
        run_scan(
            db_path,
            config_dir=CONFIG_DIR,
            scanners={"known": CountingScanner()},
            source_ids=["typo"],
        )


def test_format_summary_mentions_errors_and_totals(tmp_path) -> None:
    db_path = init_db(tmp_path / "watch.db")
    summary = run_scan(
        db_path,
        config_dir=CONFIG_DIR,
        scanners={"good": CountingScanner(), "bad": CountingScanner(RuntimeError("down"))},
    )

    text = format_summary(summary)

    assert summary["run_id"] in text
    assert "1 done" in text and "1 error" in text
    assert "1 fetched" in text
    assert "error bad: " in text


def test_scan_and_runs_cli_commands(tmp_path, monkeypatch) -> None:
    db_path = tmp_path / "watch.db"
    scanners = {"good": CountingScanner(), "bad": CountingScanner(RuntimeError("down"))}
    monkeypatch.setattr("peptide_watch.runtime.scan.DEFAULT_SCANNERS", scanners)
    runner = CliRunner()

    scan_result = runner.invoke(
        app,
        ["scan", "--db", str(db_path), "--config-dir", str(CONFIG_DIR)],
    )
    assert scan_result.exit_code == 0, scan_result.output
    assert "1 done" in scan_result.output

    list_result = runner.invoke(app, ["runs", "list", "--db", str(db_path)])
    assert list_result.exit_code == 0, list_result.output
    assert "completed" in list_result.output

    connection = connect(db_path)
    try:
        run_id = ledger.list_runs(connection)[0]["run_id"]
    finally:
        connection.close()

    show_result = runner.invoke(app, ["runs", "show", run_id, "--db", str(db_path)])
    assert show_result.exit_code == 0, show_result.output
    assert "good: done" in show_result.output
    assert "bad: error" in show_result.output

    missing = runner.invoke(app, ["runs", "show", "nope", "--db", str(db_path)])
    assert missing.exit_code == 1
