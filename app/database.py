"""Compatibility facade for the database service.

The implementation now lives in ``app.models`` and ``app.services``. This
module remains importable for existing integrations that used app.database.
"""

from .models.database import Base, JobRecord, initialize_database
from .services.task_service import delete_job, get_job, list_jobs, persist_job, sync_existing_jobs

__all__ = [
    "Base",
    "JobRecord",
    "delete_job",
    "get_job",
    "initialize_database",
    "list_jobs",
    "persist_job",
    "sync_existing_jobs",
]
