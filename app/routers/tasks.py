from fastapi import APIRouter, HTTPException
from fastapi.responses import FileResponse
from starlette.concurrency import run_in_threadpool

from ..schemas import TaskDetail, TaskSummary
from ..services import content_service


router = APIRouter()


def _runtime():
    from .. import api

    return api


@router.get("/api/jobs", response_model=list[TaskSummary])
async def jobs(limit: int = 100) -> list[TaskSummary]:
    runtime = _runtime()
    records = await run_in_threadpool(runtime.list_jobs, runtime._database_url(), limit)
    return [TaskSummary(**record) for record in records]


@router.get("/api/jobs/{job_id}", response_model=TaskDetail)
async def job_detail(job_id: str) -> TaskDetail:
    runtime = _runtime()
    record = await run_in_threadpool(runtime.get_job, job_id, runtime.settings.storage_dir, runtime._database_url())
    if record is None:
        raise HTTPException(status_code=404, detail="未找到该任务")
    return TaskDetail(**record)


@router.delete("/api/jobs/{job_id}")
async def remove_job(job_id: str) -> dict[str, bool]:
    runtime = _runtime()
    deleted = await run_in_threadpool(runtime.delete_job, job_id, runtime.settings.storage_dir, runtime._database_url())
    if not deleted:
        raise HTTPException(status_code=404, detail="未找到该任务")
    return {"deleted": True}


@router.get("/api/jobs/{job_id}/files/{filename}")
async def job_file(job_id: str, filename: str) -> FileResponse:
    runtime = _runtime()
    target = content_service.safe_job_file(job_id, filename, runtime.settings.storage_dir)
    media_types = {
        ".html": "text/html; charset=utf-8",
        ".md": "text/markdown; charset=utf-8",
        ".json": "application/json; charset=utf-8",
    }
    return FileResponse(target, media_type=media_types.get(target.suffix, "application/octet-stream"))
