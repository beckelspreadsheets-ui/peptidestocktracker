"""YAML configuration loading and validation."""

from __future__ import annotations

import re
from pathlib import Path
from typing import Any

import yaml
from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

UNVERIFIED_CLAIM_STATUS = "needs_verification"

# Secrets must come from the environment; config files may only reference them
# by name (e.g. "${ALERT_TOKEN}"), never hold a literal value.
SECRET_VALUE_PATTERNS = (
    re.compile(r"ghp_[A-Za-z0-9]{20,}"),
    re.compile(r"github_pat_[A-Za-z0-9_]{20,}"),
    re.compile(r"xox[baprs]-[A-Za-z0-9-]{10,}"),
    re.compile(r"(?<![A-Za-z0-9])sk-[A-Za-z0-9]{20,}"),
    re.compile(r"AKIA[0-9A-Z]{16}"),
    re.compile(r"\b\d{8,10}:[A-Za-z0-9_-]{30,}"),
    re.compile(r"-----BEGIN [A-Z ]*PRIVATE KEY-----"),
)
SECRET_KEY_PATTERN = re.compile(r"(?i)(token|secret|password|passwd|api[_-]?key|auth[_-]?key)")
ENV_REFERENCE_PATTERN = re.compile(r"^\$\{[A-Z][A-Z0-9_]*\}$")


class PeptideConfig(BaseModel):
    """Canonical peptide configuration."""

    model_config = ConfigDict(extra="forbid")

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

    model_config = ConfigDict(extra="forbid")

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

    model_config = ConfigDict(extra="forbid")

    type: str
    url: str
    tier: str
    cadence: str
    company_id: str | None = None

    @field_validator("type", "url", "tier", "cadence")
    @classmethod
    def require_text(cls, value: str) -> str:
        value = value.strip()
        if not value:
            raise ValueError("value must not be blank")
        return value


class PeptidesFile(BaseModel):
    model_config = ConfigDict(extra="forbid")

    peptides: list[PeptideConfig]

    @model_validator(mode="after")
    def reject_duplicate_ids(self) -> "PeptidesFile":
        _reject_duplicate_ids((item.id for item in self.peptides), "peptide")
        return self


class CompaniesFile(BaseModel):
    model_config = ConfigDict(extra="forbid")

    companies: list[CompanyConfig]

    @model_validator(mode="after")
    def reject_duplicate_ids(self) -> "CompaniesFile":
        _reject_duplicate_ids((item.id for item in self.companies), "company")
        return self


class SourcesFile(BaseModel):
    model_config = ConfigDict(extra="forbid")

    sources: dict[str, SourceConfig]

    @field_validator("sources")
    @classmethod
    def require_sources(cls, value: dict[str, SourceConfig]) -> dict[str, SourceConfig]:
        if not value:
            raise ValueError("at least one source is required")
        return value


class QueriesFile(BaseModel):
    model_config = ConfigDict(extra="forbid")

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
    model_config = ConfigDict(extra="forbid")

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
    _reject_secret_values(loaded, str(path))
    return loaded


def _reject_secret_values(node: Any, location: str) -> None:
    """Reject literal secrets in config; secrets belong in env vars only."""

    if isinstance(node, dict):
        for key, value in node.items():
            child_location = f"{location}.{key}"
            if (
                isinstance(key, str)
                and SECRET_KEY_PATTERN.search(key)
                and isinstance(value, str)
                and value
                and not ENV_REFERENCE_PATTERN.match(value)
            ):
                raise ValueError(
                    f"config key {child_location!r} looks like a secret; "
                    'reference an environment variable instead (e.g. "${MY_TOKEN}")'
                )
            _reject_secret_values(value, child_location)
    elif isinstance(node, list):
        for index, value in enumerate(node):
            _reject_secret_values(value, f"{location}[{index}]")
    elif isinstance(node, str):
        for pattern in SECRET_VALUE_PATTERNS:
            if pattern.search(node):
                raise ValueError(
                    f"config value at {location!r} matches a known secret/token shape; "
                    "move it to an environment variable and reference it by name"
                )


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
