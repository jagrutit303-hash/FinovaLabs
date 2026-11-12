"""Load and validate centralized application configuration from config.yaml and .env."""

from __future__ import annotations

import os
import re
from functools import lru_cache
from pathlib import Path
from typing import Any, Literal

import yaml
from dotenv import load_dotenv
from pydantic import BaseModel, Field, ValidationError, model_validator

from finova_labs import PRODUCT_NAME, PRODUCT_TAGLINE
from finova_labs.exceptions import ConfigurationError

_EMAIL_RE = re.compile(r"[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}")
_PLACEHOLDER_DOMAINS = {"example.com", "example.org", "example.net", "yourdomain.com", "test.com"}


class AppSettings(BaseModel):
    """Core application metadata and storage paths."""

    name: str = PRODUCT_NAME
    tagline: str = PRODUCT_TAGLINE
    db_path: str = "data/finova_labs.db"
    reports_dir: str = "data/reports"


class SecSettings(BaseModel):
    """SEC EDGAR client configuration."""

    user_agent: str = "FinovaLabs contact@example.com"
    cache_dir: str = "data/cache/sec"
    request_timeout_seconds: int = Field(default=30, ge=1, le=300)
    max_requests_per_second: int = Field(default=5, ge=1, le=10)


class ConfidenceWeights(BaseModel):
    """Configurable weights for explainable confidence scoring (must sum to 1.0)."""

    label_concept_match: float = Field(default=0.25, ge=0.0, le=1.0)
    reporting_period_match: float = Field(default=0.25, ge=0.0, le=1.0)
    unit_scale_correctness: float = Field(default=0.20, ge=0.0, le=1.0)
    evidence_quality: float = Field(default=0.20, ge=0.0, le=1.0)
    independent_path_agreement: float = Field(default=0.10, ge=0.0, le=1.0)

    @model_validator(mode="after")
    def validate_weight_sum(self) -> "ConfidenceWeights":
        total = (
            self.label_concept_match
            + self.reporting_period_match
            + self.unit_scale_correctness
            + self.evidence_quality
            + self.independent_path_agreement
        )
        if abs(total - 1.0) > 1e-6:
            raise ValueError(
                f"confidence.weights must sum to 1.0 (got {total:.4f})"
            )
        return self


class ConfidenceSettings(BaseModel):
    """Confidence score thresholds and factor weights for review escalation."""

    auto_approve_threshold: float = Field(default=0.90, ge=0.0, le=1.0)
    review_required_threshold: float = Field(default=0.60, ge=0.0, le=1.0)
    scoring_version: str = "1.0.0"
    weights: ConfidenceWeights = Field(default_factory=ConfidenceWeights)

    @model_validator(mode="after")
    def validate_threshold_order(self) -> "ConfidenceSettings":
        if self.auto_approve_threshold <= self.review_required_threshold:
            raise ValueError(
                "auto_approve_threshold must be greater than review_required_threshold"
            )
        return self


class ValidationSettings(BaseModel):
    """Financial reconciliation and variance alert thresholds."""

    accounting_identity_tolerance: float = Field(default=0.0005, ge=0.0, le=1.0)
    segment_reconciliation_tolerance: float = Field(default=0.02, ge=0.0, le=1.0)
    yoy_change_alert_threshold: float = Field(default=0.30, ge=0.0, le=10.0)


class LoggingSettings(BaseModel):
    """Application logging settings."""

    level: Literal["DEBUG", "INFO", "WARNING", "ERROR", "CRITICAL"] = "INFO"
    log_dir: str = "data/logs"
    file_name: str = "finova_labs.log"


class Settings(BaseModel):
    """Validated top-level FinovaLabs configuration."""

    project_root: Path = Field(default_factory=Path.cwd)
    app: AppSettings = Field(default_factory=AppSettings)
    sec: SecSettings = Field(default_factory=SecSettings)
    confidence: ConfidenceSettings = Field(default_factory=ConfidenceSettings)
    validation: ValidationSettings = Field(default_factory=ValidationSettings)
    logging: LoggingSettings = Field(default_factory=LoggingSettings)

    def resolve_path(self, relative_or_absolute: str | Path) -> Path:
        """Resolve a configured path relative to the project root."""
        target = Path(relative_or_absolute)
        return target if target.is_absolute() else (self.project_root / target).resolve()

    @property
    def db_file(self) -> Path:
        return self.resolve_path(self.app.db_path)

    @property
    def reports_path(self) -> Path:
        return self.resolve_path(self.app.reports_dir)

    @property
    def cache_path(self) -> Path:
        return self.resolve_path(self.sec.cache_dir)

    @property
    def log_file(self) -> Path:
        return self.resolve_path(self.logging.log_dir) / self.logging.file_name


def find_project_root(start: Path | None = None) -> Path:
    """Locate the repository root containing config.yaml."""
    current = (start or Path(__file__)).resolve()
    for candidate in (current, *current.parents):
        if (candidate / "config.yaml").is_file():
            return candidate
    return Path.cwd().resolve()


def load_project_env(project_root: Path | None = None) -> None:
    """Load environment variables from .env without overriding existing OS variables."""
    root = project_root or find_project_root()
    env_file = root / ".env"
    if env_file.is_file():
        load_dotenv(dotenv_path=env_file, override=False)


def resolve_sec_user_agent(
    settings: Settings | None = None,
    require_real_email: bool = True,
) -> str:
    """Resolve and validate the SEC EDGAR User-Agent from environment or config.

    Priority:
    1. ``FINOVALABS_SEC_USER_AGENT`` environment variable
    2. ``FINOVALABS_SEC_CONTACT_EMAIL`` environment variable
    3. ``config.yaml`` ``sec.user_agent``
    """
    cfg = settings or get_settings()
    load_project_env(cfg.project_root)

    explicit_ua = os.getenv("FINOVALABS_SEC_USER_AGENT", "").strip()
    contact_email = os.getenv("FINOVALABS_SEC_CONTACT_EMAIL", "").strip()

    if explicit_ua:
        candidate = explicit_ua
    elif contact_email:
        candidate = f"{PRODUCT_NAME} {contact_email}"
    else:
        candidate = cfg.sec.user_agent.strip()

    match = _EMAIL_RE.search(candidate)
    if not match:
        raise ConfigurationError(
            "SEC User-Agent must include a valid contact email address.",
            hint="Set FINOVALABS_SEC_CONTACT_EMAIL=your.name@domain.com in .env.",
        )

    domain = match.group(0).split("@", 1)[1].lower()
    if require_real_email and domain in _PLACEHOLDER_DOMAINS:
        raise ConfigurationError(
            f"SEC User-Agent still uses placeholder email domain '{domain}'.",
            hint="Create a .env file from .env.example and set FINOVALABS_SEC_CONTACT_EMAIL to your real email address.",
        )

    return candidate


def load_typed_settings(config_path: Path | None = None) -> Settings:
    """Read and validate config.yaml and .env into a Settings model."""
    root = config_path.resolve().parent if config_path else find_project_root()
    load_project_env(root)
    path = config_path.resolve() if config_path else (root / "config.yaml")

    raw_data: dict[str, Any] = {}
    if path.is_file():
        try:
            loaded = yaml.safe_load(path.read_text(encoding="utf-8"))
        except yaml.YAMLError as exc:
            raise ConfigurationError(
                f"Failed to parse YAML configuration at {path}",
                hint="Check config.yaml syntax and indentation.",
            ) from exc
        except OSError as exc:
            raise ConfigurationError(
                f"Unable to read configuration file at {path}: {exc}",
                hint="Verify file permissions for config.yaml.",
            ) from exc

        if loaded is None:
            raw_data = {}
        elif isinstance(loaded, dict):
            raw_data = loaded
        else:
            raise ConfigurationError(
                f"Invalid configuration structure in {path}",
                hint="Top-level config.yaml content must be a key-value mapping.",
            )

    try:
        return Settings(project_root=root, **raw_data)
    except ValidationError as exc:
        raise ConfigurationError(
            f"Configuration validation failed: {exc.errors()[0]['msg']}",
            hint="Review values under app, sec, confidence, validation, and logging in config.yaml.",
        ) from exc


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    """Return cached validated Settings for the current process."""
    return load_typed_settings()


def load_settings(config_path: Path | None = None) -> dict[str, Any]:
    """Return validated settings as a plain dictionary for backward compatibility."""
    settings = load_typed_settings(config_path) if config_path else get_settings()
    return settings.model_dump(exclude={"project_root"})
