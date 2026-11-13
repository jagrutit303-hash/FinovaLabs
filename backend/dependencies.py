"""Dependency injection providers for FinovaLabs FastAPI backend."""

from __future__ import annotations

from pathlib import Path
from typing import Annotated

from fastapi import Depends

from backend.config import get_backend_settings
from finova_labs.database import resolve_db_path
from finova_labs.settings import Settings


def get_db_file() -> Path:
    """Return the active SQLite database path from centralized settings."""
    settings = get_backend_settings()
    return resolve_db_path(settings.db_file)


def get_sec_cache_dir() -> Path:
    """Return the disk cache path for SEC submissions, facts, and HTML."""
    settings = get_backend_settings()
    return Path(settings.sec.cache_dir).resolve()


def get_settings_dep() -> Settings:
    """Return application settings object."""
    return get_backend_settings()


DbPathDep = Annotated[Path, Depends(get_db_file)]
SettingsDep = Annotated[Settings, Depends(get_settings_dep)]

