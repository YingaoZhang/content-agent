"""FastAPI application assembly.

HTTP handlers live in ``app.routers`` and receive their dependencies through
``app.dependencies``. This module only wires the lifespan, static mounts, and
router registration.
"""

from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI
from fastapi.staticfiles import StaticFiles
from starlette.concurrency import run_in_threadpool

from .config import settings
from .models.database import dispose_engines, initialize_database
from .routers import content_router, pages_router, system_router, tasks_router
from .services import job_runner
from .services.content_service import database_url
from .services.task_service import sync_existing_jobs


ROOT_DIR = Path(__file__).resolve().parents[1]
FRONTEND_DIR = ROOT_DIR / "frontend"

settings.storage_dir.mkdir(parents=True, exist_ok=True)


@asynccontextmanager
async def lifespan(_: FastAPI):
    database = database_url(settings)
    await run_in_threadpool(initialize_database, database)
    await run_in_threadpool(sync_existing_jobs, settings.storage_dir, database)
    await run_in_threadpool(job_runner.recover)
    try:
        yield
    finally:
        job_runner.shutdown(wait=False)
        await run_in_threadpool(dispose_engines)


app = FastAPI(title="Content Agent API", version="0.3.0", lifespan=lifespan)
app.mount("/assets", StaticFiles(directory=settings.storage_dir), name="assets")
app.include_router(pages_router)
app.include_router(system_router)
app.include_router(content_router)
app.include_router(tasks_router)
app.mount("/static", StaticFiles(directory=FRONTEND_DIR), name="static")
