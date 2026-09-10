from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import FileResponse
from starlette.concurrency import run_in_threadpool

from ..config import Settings
from ..dependencies import get_database_url, get_settings
from ..schemas import TaskDetail, TaskSummary
from ..services import content_service
from ..services.task_service import delete_job, get_job, list_jobs


router = APIRouter()


@router.get("/api/jobs", response_model=list[TaskSummary])
async def jobs(
    limit: int = 100,
    database_url: str = Depends(get_database_url),
) -> list[TaskSummary]:
    records = await run_in_threadpool(list_jobs, database_url, limit)
    return [TaskSummary(**record) for record in records]


@router.get("/api/jobs/{job_id}", response_model=TaskDetail)
async def job_detail(
    job_id: str,
    settings: Settings = Depends(get_settings),
    database_url: str = Depends(get_database_url),
) -> TaskDetail:
    record = await run_in_threadpool(get_job, job_id, settings.storage_dir, database_url)
    if record is None:
        raise HTTPException(status_code=404, detail="未找到该任务")
    return TaskDetail(**record)


@router.delete("/api/jobs/{job_id}")
async def remove_job(
    job_id: str,
    settings: Settings = Depends(get_settings),
    database_url: str = Depends(get_database_url),
) -> dict[str, bool]:
    deleted = await run_in_threadpool(delete_job, job_id, settings.storage_dir, database_url)
    if not deleted:
        raise HTTPException(status_code=404, detail="未找到该任务")
    return {"deleted": True}


@router.get("/api/jobs/{job_id}/images.zip")
async def job_images_archive(
    job_id: str,
    settings: Settings = Depends(get_settings),
) -> FileResponse:
    archive = await run_in_threadpool(content_service.build_images_archive, job_id, settings.storage_dir)
    return FileResponse(archive, media_type="application/zip", filename="images.zip")


@router.get("/api/jobs/{job_id}/files/{filename}")
async def job_file(
    job_id: str,
    filename: str,
    settings: Settings = Depends(get_settings),
) -> FileResponse:
    target = content_service.safe_job_file(job_id, filename, settings.storage_dir)
    media_types = {
        ".html": "text/html; charset=utf-8",
        ".md": "text/markdown; charset=utf-8",
        ".json": "application/json; charset=utf-8",
    }
    return FileResponse(target, media_type=media_types.get(target.suffix, "application/octet-stream"))
