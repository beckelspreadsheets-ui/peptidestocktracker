"""YAML configuration loading and validation."""

from __future__ import annotations

from pathlib import Path
from typing import Any

import yaml
from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

UNVERIFIED_CLAIM_STATUS = "needs_verification"


class PeptideConfig(BaseModel):
    """Canonical peptide configuration."""

    id: str
    name: str
    primary: bool = False
    aliases: list[str] = Field(default_factory=list)

    @field_validator("id", "name")
    @classmethod
    def require_text(cls, value: str) -> str:
        value = value.strip()
        if not value:
            raise ValueError("value must not be blank")
        return value

    @field_validator("aliases")
    @classmethod
    def require_aliases(cls, value: list[str]) -> list[str]:
        if not value:
            raise ValueError("each peptide must define at least one alias")
        return value


class CompanyConfig(BaseModel):
    """Company/watchlist configuration."""

    model_config = ConfigDict(extra="allow")

    id: str
    name: str
    public_private: str
    tier: int = Field(ge=1, le=3)
    relationship: str
    peptides: list[str] = Field(default_factory=list)
    confidence: str
    ticker: str | None = None
    exchange: str | None = None
    note: str | None = None
    liquidity_risk: str | None = None

    @field_validator("id", "name", "public_private", "relationship", "confidence")
    @classmethod
    def require_text(cls, value: str) -> str:
        value = value.strip()
        if not value:
            raise ValueError("value must not be blank")
        return value

    @field_validator("peptides")
    @classmethod
    def require_peptide_refs(cls, value: list[str]) -> list[str]:
        if not value:
            raise ValueError("each company must reference at least one peptide or 'multiple'")
        return value


class SourceConfig(BaseModel):
    """Public-source monitor configuration."""

    model_config = ConfigDict(extra="allow")

    type: str
    url: str
    tier: str
    cadence: str

    @field_validator("type", "url", "tier", "cadence")
    @classmethod
    def require_text(cls, value: str) -> str:
        value = value.strip()
        if not value:
            raise ValueError("value must not be blank")
        return value


class PeptidesFile(BaseModel):
    peptides: list[PeptideConfig]

    @model_validator(mode="after")
    def reject_duplicate_ids(self) -> "PeptidesFile":
        _reject_duplicate_ids((item.id for item in self.peptides), "peptide")
        return self


class CompaniesFile(BaseModel):
    companies: list[CompanyConfig]

    @model_validator(mode="after")
    def reject_duplicate_ids(self) -> "CompaniesFile":
        _reject_duplicate_ids((item.id for item in self.companies), "company")
        return self


class SourcesFile(BaseModel):
    sources: dict[str, SourceConfig]

    @field_validator("sources")
    @classmethod
    def require_sources(cls, value: dict[str, SourceConfig]) -> dict[str, SourceConfig]:
        if not value:
            raise ValueError("at least one source is required")
        return value


class QueriesFile(BaseModel):
    queries: dict[str, list[str]]

    @field_validator("queries")
    @classmethod
    def require_queries(cls, value: dict[str, list[str]]) -> dict[str, list[str]]:
        if not value:
            raise ValueError("at least one query group is required")
        for key, queries in value.items():
            if not queries:
                raise ValueError(f"query group {key!r} must not be empty")
        return value


class AlertRulesFile(BaseModel):
    severity_rules: dict[str, list[str]]
    confidence_rules: dict[str, str]
    review_defaults: dict[str, str]


class WatchConfig(BaseModel):
    """Fully loaded repository configuration."""

    peptides: list[PeptideConfig]
    companies: list[CompanyConfig]
    sources: dict[str, SourceConfig]
    queries: dict[str, list[str]]
    alert_rules: AlertRulesFile

    @model_validator(mode="after")
    def validate_company_peptide_refs(self) -> "WatchConfig":
        peptide_ids = {peptide.id for peptide in self.peptides}
        allowed_special_refs = {"multiple"}
        for company in self.companies:
            unknown_refs = set(company.peptides) - peptide_ids - allowed_special_refs
            if unknown_refs:
                refs = ", ".join(sorted(unknown_refs))
                raise ValueError(f"company {company.id!r} references unknown peptide ids: {refs}")
        return self

    @property
    def primary_peptides(self) -> list[PeptideConfig]:
        return [peptide for peptide in self.peptides if peptide.primary]


def load_config(config_dir: str | Path = "config") -> WatchConfig:
    """Load all required YAML config files from ``config_dir``."""

    base_dir = Path(config_dir)
    peptides = PeptidesFile.model_validate(_load_yaml(base_dir / "peptides.yaml"))
    companies = CompaniesFile.model_validate(_load_yaml(base_dir / "companies.yaml"))
    sources = SourcesFile.model_validate(_load_yaml(base_dir / "sources.yaml"))
    queries = QueriesFile.model_validate(_load_yaml(base_dir / "queries.yaml"))
    alert_rules = AlertRulesFile.model_validate(_load_yaml(base_dir / "alert_rules.yaml"))
    return WatchConfig(
        peptides=peptides.peptides,
        companies=companies.companies,
        sources=sources.sources,
        queries=queries.queries,
        alert_rules=alert_rules,
    )


def _load_yaml(path: Path) -> dict[str, Any]:
    if not path.exists():
        raise FileNotFoundError(f"required config file not found: {path}")
    loaded = yaml.safe_load(path.read_text(encoding="utf-8"))
    if loaded is None:
        return {}
    if not isinstance(loaded, dict):
        raise ValueError(f"config file must contain a mapping: {path}")
    return loaded


def _reject_duplicate_ids(ids: Any, label: str) -> None:
    seen: set[str] = set()
    duplicates: set[str] = set()
    for item_id in ids:
        if item_id in seen:
            duplicates.add(item_id)
        seen.add(item_id)
    if duplicates:
        formatted = ", ".join(sorted(duplicates))
        raise ValueError(f"duplicate {label} ids: {formatted}")
