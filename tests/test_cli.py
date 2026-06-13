from pathlib import Path

from typer.testing import CliRunner

from peptide_watch.cli import app
from peptide_watch.database import REQUIRED_TABLES, table_names

ROOT = Path(__file__).resolve().parents[1]


def test_init_db_command_creates_database(tmp_path) -> None:
    db_path = tmp_path / "watch.db"
    result = CliRunner().invoke(app, ["init-db", "--db", str(db_path)])

    assert result.exit_code == 0, result.output
    assert db_path.exists()
    assert REQUIRED_TABLES <= table_names(db_path)


def test_config_check_passes_on_repo_config() -> None:
    result = CliRunner().invoke(app, ["config", "check", "--config-dir", str(ROOT / "config")])

    assert result.exit_code == 0, result.output
    assert "Config OK" in result.output


def test_config_check_fails_on_missing_config_dir(tmp_path) -> None:
    result = CliRunner().invoke(
        app, ["config", "check", "--config-dir", str(tmp_path / "missing")]
    )

    assert result.exit_code == 1


def test_backup_db_command_creates_backup(tmp_path) -> None:
    db_path = tmp_path / "watch.db"
    runner = CliRunner()
    runner.invoke(app, ["init-db", "--db", str(db_path)])

    result = runner.invoke(
        app,
        ["backup-db", "--db", str(db_path), "--backups-dir", str(tmp_path / "backups")],
    )

    assert result.exit_code == 0, result.output
    assert "Backed up" in result.output
    assert list((tmp_path / "backups").glob("watch-*.db"))


def test_claims_seed_and_export_commands(tmp_path) -> None:
    db_path = tmp_path / "watch.db"
    runner = CliRunner()

    seed = runner.invoke(app, ["claims", "seed", "--db", str(db_path)])
    export = runner.invoke(app, ["claims", "export", "--db", str(db_path), "--format", "csv"])

    assert seed.exit_code == 0, seed.output
    assert "14 inserted" in seed.output
    assert export.exit_code == 0, export.output
    assert "needs_verification" in export.output
    assert "confirmed_primary_source" in export.output


def test_claims_add_command_defaults_to_needs_verification(tmp_path) -> None:
    db_path = tmp_path / "watch.db"
    result = CliRunner().invoke(
        app,
        [
            "claims",
            "add",
            "--db",
            str(db_path),
            "--text",
            "AI report claim that requires primary-source verification.",
            "--source-type",
            "ai_report",
        ],
    )

    assert result.exit_code == 0, result.output
    assert "needs_verification" in result.output


def test_briefing_json_command(tmp_path) -> None:
    import json
    db_path = tmp_path / "watch.db"
    runner = CliRunner()
    runner.invoke(app, ["init-db", "--db", str(db_path)])
    result = runner.invoke(
        app, ["briefing", "--db", str(db_path), "--config-dir", str(ROOT / "config"), "--format", "json"]
    )
    assert result.exit_code == 0, result.output
    data = json.loads(result.output)
    assert data["schema_version"] == "1.0"
    assert "top_events" in data and "disclaimers" in data


def test_briefing_markdown_has_disclaimer(tmp_path) -> None:
    db_path = tmp_path / "watch.db"
    runner = CliRunner()
    runner.invoke(app, ["init-db", "--db", str(db_path)])
    result = runner.invoke(
        app, ["briefing", "--db", str(db_path), "--config-dir", str(ROOT / "config")]
    )
    assert result.exit_code == 0, result.output
    assert "not a buy/sell recommendation" in result.output


def test_check_language_clean_and_forbidden() -> None:
    runner = CliRunner()
    clean = runner.invoke(app, ["check-language", "--text", "A new filer disclosed BPC-157. Source: url."])
    assert clean.exit_code == 0, clean.output
    assert "clean" in clean.output

    bad = runner.invoke(app, ["check-language", "--text", "you should buy this now for guaranteed gains"])
    assert bad.exit_code == 1
    assert "forbidden" in bad.output

    # the whitelisted disclaimer phrase must NOT trip the gate
    ok = runner.invoke(app, ["check-language", "--text", "This is not a buy/sell recommendation."])
    assert ok.exit_code == 0, ok.output


def test_hq_command_status(tmp_path) -> None:
    db_path = tmp_path / "watch.db"
    result = CliRunner().invoke(app, ["hq-command", "/status", "--db", str(db_path)])

    assert result.exit_code == 0, result.output
    assert "Peptide Watch HQ status" in result.output
    assert "Latest run:" in result.output
