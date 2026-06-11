import shutil
from pathlib import Path

import pytest

from peptide_watch.config import UNVERIFIED_CLAIM_STATUS, load_config

ROOT = Path(__file__).resolve().parents[1]


def _copy_config(tmp_path: Path) -> Path:
    config_dir = tmp_path / "config"
    shutil.copytree(ROOT / "config", config_dir)
    return config_dir


def test_load_config_reads_required_yaml_files() -> None:
    config = load_config(ROOT / "config")

    peptide_ids = {peptide.id for peptide in config.peptides}
    assert {"bpc_157", "tb_500", "thymosin_beta_4", "ghk_cu"} <= peptide_ids
    assert len(config.primary_peptides) == 4
    assert "fda_pcac_2026" in config.sources
    assert "pcac_docket" in config.queries
    assert config.alert_rules.review_defaults["ai_report_claim"] == "needs_review"


def test_config_preserves_unverified_claim_status_name() -> None:
    assert UNVERIFIED_CLAIM_STATUS == "needs_verification"


def test_unknown_source_key_is_rejected(tmp_path) -> None:
    config_dir = _copy_config(tmp_path)
    sources_path = config_dir / "sources.yaml"
    sources_path.write_text(
        sources_path.read_text(encoding="utf-8").replace(
            "cadence: daily", "cadence: daily\n    cadnece_typo: weekly", 1
        ),
        encoding="utf-8",
    )

    with pytest.raises(Exception, match="cadnece_typo"):
        load_config(config_dir)


def test_literal_token_value_is_rejected(tmp_path) -> None:
    config_dir = _copy_config(tmp_path)
    sources_path = config_dir / "sources.yaml"
    sources_path.write_text(
        sources_path.read_text(encoding="utf-8")
        + "  bad_source:\n"
        + "    type: api\n"
        + "    url: https://example.com/?key=ghp_abcdefghijklmnopqrstuvwxyz123456\n"
        + "    tier: A\n"
        + "    cadence: daily\n",
        encoding="utf-8",
    )

    with pytest.raises(ValueError, match="secret/token shape"):
        load_config(config_dir)


def test_secret_named_key_requires_env_reference(tmp_path) -> None:
    config_dir = _copy_config(tmp_path)
    alert_rules_path = config_dir / "alert_rules.yaml"
    alert_rules_path.write_text(
        alert_rules_path.read_text(encoding="utf-8")
        + "  alert_token: literal-secret-value\n",
        encoding="utf-8",
    )

    with pytest.raises(ValueError, match="environment variable"):
        load_config(config_dir)


def test_secret_named_key_accepts_env_reference_syntax(tmp_path) -> None:
    config_dir = _copy_config(tmp_path)
    sources_path = config_dir / "sources.yaml"
    text = sources_path.read_text(encoding="utf-8")
    # An env-style reference passes the secret scan; the unknown key must still
    # be caught by extra="forbid".
    sources_path.write_text(
        text.replace("cadence: daily", 'cadence: daily\n    api_token: "${MY_TOKEN}"', 1),
        encoding="utf-8",
    )

    with pytest.raises(Exception, match="api_token"):
        load_config(config_dir)
