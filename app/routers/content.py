import shutil

from fastapi import APIRouter, Depends, File, Form, HTTPException, UploadFile
from pydantic import ValidationError
from starlette.concurrency import run_in_threadpool

from ..config import Settings
from ..dependencies import get_database_url, get_settings
from ..harness import ProviderUnavailableError, VisionApiClient
from ..materials import merge_materials
from ..schemas import ContentRequest, JobAccepted, Platform
from ..services import content_service
from ..services.generation_service import (
    accept_outline,
    prepare_generation,
    prepare_outline,
    prepare_revision,
    select_title,
)
from ..services.job_runner import submit as submit_job
from ..services.task_service import persist_job


router = APIRouter()


def _error_message(error: Exception) -> str:
    return str(error) or "请求处理失败"


@router.post("/api/outlines", response_model=JobAccepted)
async def create_outline(
    request_json: str = Form(..., alias="request"),
    files: list[UploadFile] = File(...),
    settings: Settings = Depends(get_settings),
    database_url: str = Depends(get_database_url),
) -> JobAccepted:
    try:
        request = ContentRequest.model_validate_json(request_json)
    except ValidationError as exc:
        raise HTTPException(status_code=422, detail=exc.errors()) from exc
    if request.platform == Platform.XIAOHONGSHU:
        raise HTTPException(status_code=422, detail="小红书图文请直接使用 /api/generate")
    if not files:
        raise HTTPException(status_code=400, detail="至少需要上传一份资料")

    upload_dir, paths = await content_service.store_uploads(files, settings.storage_dir)
    try:
        has_images = content_service.has_image_materials(paths)
        material_text = await run_in_threadpool(
            merge_materials,
            paths,
            image_to_text=VisionApiClient().describe if has_images else None,
        )
        job_id = await run_in_threadpool(prepare_outline, request, material_text, settings.storage_dir)
        await run_in_threadpool(persist_job, job_id, settings.storage_dir, database_url)
        submit_job(job_id)
        return JobAccepted(job_id=job_id)
    except (ProviderUnavailableError, RuntimeError, ValueError) as exc:
        raise HTTPException(status_code=503, detail=_error_message(exc)) from exc
    finally:
        shutil.rmtree(upload_dir, ignore_errors=True)


@router.post("/api/outlines/{job_id}/titles", response_model=JobAccepted)
async def choose_title(
    job_id: str,
    title: str = Form(...),
    settings: Settings = Depends(get_settings),
    database_url: str = Depends(get_database_url),
) -> JobAccepted:
    try:
        await run_in_threadpool(select_title, job_id, title, settings.storage_dir)
        await run_in_threadpool(persist_job, job_id, settings.storage_dir, database_url)
        submit_job(job_id)
        return JobAccepted(job_id=job_id)
    except FileNotFoundError as exc:
        raise HTTPException(status_code=404, detail="未找到候选标题对应的任务") from exc
    except (ProviderUnavailableError, RuntimeError, ValueError) as exc:
        raise HTTPException(status_code=503, detail=_error_message(exc)) from exc


@router.post("/api/outlines/{job_id}/generate", response_model=JobAccepted)
async def generate_from_outline(
    job_id: str,
    outline: str = Form(...),
    title: str | None = Form(None),
    settings: Settings = Depends(get_settings),
    database_url: str = Depends(get_database_url),
) -> JobAccepted:
    try:
        await run_in_threadpool(accept_outline, job_id, outline, settings.storage_dir, title)
        await run_in_threadpool(persist_job, job_id, settings.storage_dir, database_url)
        submit_job(job_id)
        return JobAccepted(job_id=job_id)
    except FileNotFoundError as exc:
        raise HTTPException(status_code=404, detail="未找到待确认大纲") from exc
    except (ProviderUnavailableError, RuntimeError, ValueError) as exc:
        raise HTTPException(status_code=503, detail=_error_message(exc)) from exc


@router.post("/api/generate", response_model=JobAccepted)
async def generate(
    request_json: str = Form(..., alias="request"),
    files: list[UploadFile] = File(...),
    settings: Settings = Depends(get_settings),
    database_url: str = Depends(get_database_url),
) -> JobAccepted:
    try:
        request = ContentRequest.model_validate_json(request_json)
    except ValidationError as exc:
        raise HTTPException(status_code=422, detail=exc.errors()) from exc
    if not files:
        raise HTTPException(status_code=400, detail="至少需要上传一份资料")

    upload_dir, paths = await content_service.store_uploads(files, settings.storage_dir)
    try:
        reference_images = content_service.image_material_paths(paths)
        has_images = content_service.has_image_materials(paths)
        material_text = await run_in_threadpool(
            merge_materials,
            paths,
            image_to_text=VisionApiClient().describe if has_images else None,
        )
        job_id = await run_in_threadpool(prepare_generation, request, material_text, settings.storage_dir, reference_images)
        await run_in_threadpool(persist_job, job_id, settings.storage_dir, database_url)
        submit_job(job_id)
        return JobAccepted(job_id=job_id)
    except (ProviderUnavailableError, RuntimeError, ValueError) as exc:
        raise HTTPException(status_code=503, detail=_error_message(exc)) from exc
    finally:
        shutil.rmtree(upload_dir, ignore_errors=True)


@router.post("/api/jobs/{job_id}/revision", response_model=JobAccepted)
async def revise(
    job_id: str,
    feedback: str = Form(...),
    settings: Settings = Depends(get_settings),
    database_url: str = Depends(get_database_url),
) -> JobAccepted:
    try:
        child_job_id = await run_in_threadpool(prepare_revision, job_id, feedback, settings.storage_dir)
        await run_in_threadpool(persist_job, child_job_id, settings.storage_dir, database_url)
        submit_job(child_job_id)
        return JobAccepted(job_id=child_job_id)
    except FileNotFoundError as exc:
        raise HTTPException(status_code=404, detail="未找到当前任务") from exc
    except (ProviderUnavailableError, RuntimeError, ValueError) as exc:
        raise HTTPException(status_code=503, detail=_error_message(exc)) from exc
