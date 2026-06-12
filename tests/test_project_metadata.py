import tomllib
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def test_pyproject_defines_python312_package_and_cli() -> None:
    pyproject = tomllib.loads((ROOT / "pyproject.toml").read_text(encoding="utf-8"))

    assert pyproject["project"]["requires-python"] == ">=3.12"
    assert pyproject["project"]["scripts"]["peptide-watch"] == "peptide_watch.cli:app"
    assert pyproject["tool"]["hatch"]["build"]["targets"]["wheel"]["packages"] == [
        "src/peptide_watch"
    ]


def test_baseline_script_checks_live_runtime_without_secret_output() -> None:
    script = (ROOT / "scripts" / "peptide_watch_baseline.sh").read_text(
        encoding="utf-8"
    )

    assert "uv run peptide-watch config check" in script
    assert "uv run peptide-watch status" in script
    assert "systemctl is-active" in script
    assert "http://127.0.0.1:8000" in script
    assert "/api/health" in script
    assert "peptide-watch · cockpit" in script
    assert "openclaw cron get" in script
    assert "python3 -c" in script
    assert "peptide-watch-briefing-agent" in script
    assert "PEPTIDE_WATCH_TELEGRAM_TOKEN" not in script
    assert "cat .env" not in script


def test_send_telegram_script_has_dry_run_and_language_gate(tmp_path) -> None:
    env_file = tmp_path / ".env"
    env_file.write_text(
        "PEPTIDE_WATCH_TELEGRAM_TOKEN=test-token\n"
        "PEPTIDE_WATCH_TELEGRAM_CHAT_ID=-100123\n",
        encoding="utf-8",
    )
    script = ROOT / "scripts" / "peptide_watch_send_telegram.py"

    ok = subprocess.run(
        [sys.executable, str(script), "--env-file", str(env_file), "--dry-run"],
        input="Peptide Watch HQ test: public-source tracker status only.",
        text=True,
        capture_output=True,
        cwd=ROOT,
        check=False,
    )
    assert ok.returncode == 0, ok.stderr
    assert "telegram send dry-run ok" in ok.stdout

    blocked = subprocess.run(
        [sys.executable, str(script), "--env-file", str(env_file), "--dry-run"],
        input="you should buy this now",
        text=True,
        capture_output=True,
        cwd=ROOT,
        check=False,
    )
    assert blocked.returncode == 2
    assert "language gate failed" in blocked.stderr
