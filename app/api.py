"""FastAPI application assembly.

HTTP handlers live in ``app.routers``. This module keeps application setup and
legacy imports that external callers may still use.
"""

from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI, UploadFile
from fastapi.staticfiles import StaticFiles
from starlette.concurrency import run_in_threadpool

from .config import settings
from .database import delete_job, get_job, initialize_database, list_jobs, persist_job, sync_existing_jobs
from .gzh_adapter import THEMES
from .harness import VisionApiClient
from .materials import merge_materials
from .routers import content_router, pages_router, system_router, tasks_router
from .schemas import ContentRequest, GenerationResult
from .services.content_service import (
    build_generation_result,
    database_url,
    safe_job_file,
    store_uploads,
)
from .workflow import run_generation, run_generation_from_outline, run_outline_generation, run_revision


ROOT_DIR = Path(__file__).resolve().parents[1]
FRONTEND_DIR = ROOT_DIR / "frontend"

settings.storage_dir.mkdir(parents=True, exist_ok=True)


def _database_url() -> str:
    return database_url(settings)


@asynccontextmanager
async def lifespan(_: FastAPI):
    database = _database_url()
    await run_in_threadpool(initialize_database, database)
    await run_in_threadpool(sync_existing_jobs, settings.storage_dir, database)
    yield


app = FastAPI(title="Content Agent API", version="0.3.0", lifespan=lifespan)
app.mount("/assets", StaticFiles(directory=settings.storage_dir), name="assets")
app.include_router(pages_router)
app.include_router(system_router)
app.include_router(content_router)
app.include_router(tasks_router)


# Compatibility helpers for code that imported these symbols from app.api.
async def _store_uploads(files: list[UploadFile]):
    return await store_uploads(files, settings.storage_dir)


def _job_result(
    job_id: str,
    request: ContentRequest | None = None,
    warnings: list[str] | None = None,
) -> GenerationResult:
    return build_generation_result(job_id, settings.storage_dir, request, warnings)


def _safe_job_file(job_id: str, filename: str) -> Path:
    return safe_job_file(job_id, filename, settings.storage_dir)


app.mount("/static", StaticFiles(directory=FRONTEND_DIR), name="static")
