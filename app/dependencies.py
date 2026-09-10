"""FastAPI dependency providers.

Routers receive ``settings`` and ``database_url`` through ``Depends`` instead of
reaching back into the application module. Tests override ``get_settings`` with
``app.dependency_overrides`` to point storage and the database at a temp dir.
"""

from fastapi import Depends

from .config import Settings, settings as _settings
from .services.content_service import database_url as _database_url


def get_settings() -> Settings:
    """Return the process settings singleton."""
    return _settings


def get_database_url(settings: Settings = Depends(get_settings)) -> str:
    return _database_url(settings)
