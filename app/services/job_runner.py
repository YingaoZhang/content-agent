"""Background execution for long-running generation jobs.

API requests only reserve a job (writes its inputs to disk, records status
``pending``) and return the ``job_id`` immediately. This module owns a small
worker pool that picks the job up, runs the heavy model/image pipeline, and
updates the job's persisted status to ``completed`` / ``outline_ready`` /
``failed``. The frontend polls ``GET /api/jobs/{job_id}`` until it settles.
"""

from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor

from ..config import settings
from . import generation_service, task_service
from .content_service import database_url

# Small pool keeps provider concurrency predictable (image generation is
# already capped by IMAGE_MAX_CONCURRENCY); two slots let a text-only job and
# an image job progress in parallel without flooding the upstream APIs.
_executor = ThreadPoolExecutor(max_workers=2, thread_name_prefix="job-runner")


def submit(job_id: str) -> None:
    """Enqueue a reserved job for background execution."""
    _executor.submit(_run, job_id)


def recover() -> None:
    """Re-enqueue jobs that were pending or running when the process last stopped."""
    try:
        job_ids = task_service.get_pending_job_ids(database_url(settings))
    except Exception:
        return
    for job_id in job_ids:
        submit(job_id)


def shutdown(wait: bool = False) -> None:
    _executor.shutdown(wait=wait, cancel_futures=not wait)


def _run(job_id: str) -> None:
    db_url = database_url(settings)
    task_service.set_job_status(job_id, settings.storage_dir, db_url, "running")
    try:
        generation_service.execute_job(job_id, settings.storage_dir)
    except Exception as exc:  # noqa: BLE001 - surface any pipeline failure to the user
        generation_service.mark_job_failed(job_id, str(exc) or "生成失败", settings.storage_dir)
    finally:
        try:
            task_service.persist_job(job_id, settings.storage_dir, db_url)
        except Exception:  # noqa: BLE001 - artifacts stay on disk for sync_existing_jobs
            pass
