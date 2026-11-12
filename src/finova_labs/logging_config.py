"""Centralized, idempotent logging configuration for FinovaLabs."""

from __future__ import annotations

import logging
from logging.handlers import RotatingFileHandler
from pathlib import Path

from finova_labs.settings import Settings, get_settings

_LOG_FORMAT = "%(asctime)s | %(levelname)-8s | %(name)s | %(message)s"
_DATE_FORMAT = "%Y-%m-%d %H:%M:%S"
_LOGGER_NAMESPACE = "finova_labs"


def configure_logging(settings: Settings | None = None) -> logging.Logger:
    """Configure console and rotating file logging once for the package."""
    cfg = settings or get_settings()
    package_logger = logging.getLogger(_LOGGER_NAMESPACE)

    level = getattr(logging, cfg.logging.level, logging.INFO)
    package_logger.setLevel(level)
    package_logger.propagate = False

    if package_logger.handlers:
        return package_logger

    formatter = logging.Formatter(fmt=_LOG_FORMAT, datefmt=_DATE_FORMAT)

    stream_handler = logging.StreamHandler()
    stream_handler.setLevel(level)
    stream_handler.setFormatter(formatter)
    package_logger.addHandler(stream_handler)

    log_file: Path = cfg.log_file
    try:
        log_file.parent.mkdir(parents=True, exist_ok=True)
        file_handler = RotatingFileHandler(
            log_file,
            maxBytes=2_000_000,
            backupCount=3,
            encoding="utf-8",
        )
        file_handler.setLevel(level)
        file_handler.setFormatter(formatter)
        package_logger.addHandler(file_handler)
    except OSError as exc:
        package_logger.warning("File logging disabled (%s); using console handler only.", exc)

    return package_logger


def get_logger(name: str) -> logging.Logger:
    """Return a namespaced logger, ensuring package logging is initialized."""
    configure_logging()
    short = name if name.startswith(_LOGGER_NAMESPACE) else f"{_LOGGER_NAMESPACE}.{name}"
    return logging.getLogger(short)

