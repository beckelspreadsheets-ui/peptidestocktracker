from pathlib import Path

from peptide_watch.config import UNVERIFIED_CLAIM_STATUS, load_config

ROOT = Path(__file__).resolve().parents[1]


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
