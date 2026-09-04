import shutil

from fastapi import APIRouter, File, Form, HTTPException, UploadFile
from pydantic import ValidationError
from starlette.concurrency import run_in_threadpool

from ..harness import ProviderUnavailableError, VisionApiClient
from ..schemas import ContentRequest, GenerationResult, OutlineResult, Platform
from ..services import content_service


router = APIRouter()


def _runtime():
    # Keep app.api monkeypatch compatibility while routing lives in this module.
    from .. import api

    return api


def _error_message(error: Exception) -> str:
    return str(error) or "请求处理失败"


@router.post("/api/outlines", response_model=OutlineResult)
async def create_outline(
    request_json: str = Form(..., alias="request"),
    files: list[UploadFile] = File(...),
) -> OutlineResult:
    runtime = _runtime()
    try:
        request = ContentRequest.model_validate_json(request_json)
    except ValidationError as exc:
        raise HTTPException(status_code=422, detail=exc.errors()) from exc
    if request.platform == Platform.XIAOHONGSHU:
        raise HTTPException(status_code=422, detail="小红书图文请直接使用 /api/generate")
    if not files:
        raise HTTPException(status_code=400, detail="至少需要上传一份资料")

    upload_dir, paths = await content_service.store_uploads(files, runtime.settings.storage_dir)
    try:
        has_images = content_service.has_image_materials(paths)
        material_text = await run_in_threadpool(
            runtime.merge_materials,
            paths,
            image_to_text=VisionApiClient().describe if has_images else None,
        )
        result = await run_in_threadpool(runtime.run_outline_generation, request, material_text)
        await run_in_threadpool(runtime.persist_job, result["job_id"], runtime.settings.storage_dir, runtime._database_url())
        return OutlineResult(**result)
    except (ProviderUnavailableError, RuntimeError, ValueError) as exc:
        raise HTTPException(status_code=503, detail=_error_message(exc)) from exc
    finally:
        shutil.rmtree(upload_dir, ignore_errors=True)


@router.post("/api/outlines/{job_id}/generate", response_model=GenerationResult)
async def generate_from_outline(job_id: str, outline: str = Form(...)) -> GenerationResult:
    runtime = _runtime()
    try:
        result = await run_in_threadpool(runtime.run_generation_from_outline, job_id, outline)
        await run_in_threadpool(
            runtime.persist_job,
            result["job_id"],
            runtime.settings.storage_dir,
            runtime._database_url(),
            result.get("warnings", []),
        )
        return content_service.build_generation_result(
            result["job_id"], runtime.settings.storage_dir, warnings=result.get("warnings", [])
        )
    except FileNotFoundError as exc:
        raise HTTPException(status_code=404, detail="未找到待确认大纲") from exc
    except (ProviderUnavailableError, RuntimeError, ValueError) as exc:
        raise HTTPException(status_code=503, detail=_error_message(exc)) from exc


@router.post("/api/generate", response_model=GenerationResult)
async def generate(
    request_json: str = Form(..., alias="request"),
    files: list[UploadFile] = File(...),
) -> GenerationResult:
    runtime = _runtime()
    try:
        request = ContentRequest.model_validate_json(request_json)
    except ValidationError as exc:
        raise HTTPException(status_code=422, detail=exc.errors()) from exc
    if not files:
        raise HTTPException(status_code=400, detail="至少需要上传一份资料")

    upload_dir, paths = await content_service.store_uploads(files, runtime.settings.storage_dir)
    try:
        has_images = content_service.has_image_materials(paths)
        material_text = await run_in_threadpool(
            runtime.merge_materials,
            paths,
            image_to_text=VisionApiClient().describe if has_images else None,
        )
        result = await run_in_threadpool(runtime.run_generation, request, material_text)
        await run_in_threadpool(
            runtime.persist_job,
            result["job_id"],
            runtime.settings.storage_dir,
            runtime._database_url(),
            result.get("warnings", []),
        )
        return content_service.build_generation_result(
            result["job_id"], runtime.settings.storage_dir, request, result.get("warnings", [])
        )
    except (ProviderUnavailableError, RuntimeError, ValueError) as exc:
        raise HTTPException(status_code=503, detail=_error_message(exc)) from exc
    finally:
        shutil.rmtree(upload_dir, ignore_errors=True)


@router.post("/api/jobs/{job_id}/revision", response_model=GenerationResult)
async def revise(job_id: str, feedback: str = Form(...)) -> GenerationResult:
    runtime = _runtime()
    try:
        result = await run_in_threadpool(runtime.run_revision, job_id, feedback)
        await run_in_threadpool(
            runtime.persist_job,
            result["job_id"],
            runtime.settings.storage_dir,
            runtime._database_url(),
            result.get("warnings", []),
        )
        return content_service.build_generation_result(
            result["job_id"], runtime.settings.storage_dir, warnings=result.get("warnings", [])
        )
    except FileNotFoundError as exc:
        raise HTTPException(status_code=404, detail="未找到当前任务") from exc
    except (ProviderUnavailableError, RuntimeError, ValueError) as exc:
        raise HTTPException(status_code=503, detail=_error_message(exc)) from exc
