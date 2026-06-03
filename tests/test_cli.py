from typer.testing import CliRunner

from peptide_watch.cli import app
from peptide_watch.database import REQUIRED_TABLES, table_names


def test_init_db_command_creates_database(tmp_path) -> None:
    db_path = tmp_path / "watch.db"
    result = CliRunner().invoke(app, ["init-db", "--db", str(db_path)])

    assert result.exit_code == 0, result.output
    assert db_path.exists()
    assert REQUIRED_TABLES <= table_names(db_path)


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
