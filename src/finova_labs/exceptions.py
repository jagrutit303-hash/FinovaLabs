"""Custom domain exceptions with user-friendly error messages for FinovaLabs."""

from __future__ import annotations


class FinovaError(Exception):
    """Base exception for all FinovaLabs application errors."""

    def __init__(self, message: str, hint: str | None = None) -> None:
        self.message = message
        self.hint = hint
        full = f"{message} ({hint})" if hint else message
        super().__init__(full)


class ConfigurationError(FinovaError):
    """Raised when config.yaml or environment configuration fails validation."""


class DatabaseError(FinovaError):
    """Raised when SQLite initialization, connection, or queries fail."""


class AuditChainError(FinovaError):
    """Raised when audit log persistence or hash-chain verification fails."""


class SecClientError(FinovaError):
    """Raised when SEC EDGAR lookups, network requests, or response parsing fail."""


class WorkflowError(FinovaError):
    """Raised when workflow state, review submission, or checkpoint recovery fails."""
