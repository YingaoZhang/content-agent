import json
import re
import shutil
import uuid
from pathlib import Path

from fastapi import FastAPI, File, Form, HTTPException, UploadFile
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles
from pydantic import ValidationError
from starlette.concurrency import run_in_threadpool

from .config import settings
from .harness import ProviderUnavailableError, VisionApiClient
from .materials import ALLOWED_SUFFIXES, IMAGE_SUFFIXES, merge_materials
from .schemas import ContentRequest, GenerationResult
from .workflow import run_generation, run_revision
from .gzh_adapter import THEMES


ROOT_DIR = Path(__file__).resolve().parents[1]
FRONTEND_DIR = ROOT_DIR / "frontend"
MAX_UPLOAD_SIZE = 25 * 1024 * 1024
TITLE_PATTERN = re.compile(r"^#\s+(.+?)\s*$", re.M)

app = FastAPI(title="Content Agent API", version="0.2.0")
settings.storage_dir.mkdir(parents=True, exist_ok=True)
app.mount("/assets", StaticFiles(directory=settings.storage_dir), name="assets")


def _error_message(error: Exception) -> str:
    return str(error) or "请求处理失败"


def _job_result(job_id: str, request: ContentRequest | None = None, warnings: list[str] | None = None) -> GenerationResult:
    job_dir = settings.storage_dir / "jobs" / job_id
    if not job_dir.is_dir():
        raise HTTPException(status_code=404, detail="未找到该任务")
    article_path = job_dir / "article.md"
    if not article_path.exists():
        raise HTTPException(status_code=404, detail="任务尚未生成文章产物")
    article = article_path.read_text(encoding="utf-8", errors="replace")
    title_match = TITLE_PATTERN.search(article)
    title = title_match.group(1).strip() if title_match else request.topic if request else "公众号文章"
    image_urls = [f"/assets/jobs/{job_id}/images/{path.name}" for path in sorted((job_dir / "images").glob("*.png"))] if (job_dir / "images").exists() else []
    resolved_warnings = warnings or []
    run_path = job_dir / "run.json"
    if run_path.exists():
        try:
            metadata = json.loads(run_path.read_text(encoding="utf-8"))
            resolved_warnings = metadata.get("warnings", resolved_warnings)
        except (json.JSONDecodeError, OSError):
            pass
    return GenerationResult(
        job_id=job_id,
        title=title,
        markdown_url=f"/api/jobs/{job_id}/files/article_with_images.md",
        html_url=f"/api/jobs/{job_id}/files/wechat.html",
        preview_url=f"/api/jobs/{job_id}/files/wechat_preview.html",
        image_urls=image_urls,
        warnings=resolved_warnings,
    )


def _safe_job_file(job_id: str, filename: str) -> Path:
    if not re.fullmatch(r"[a-f0-9]{12}", job_id) or Path(filename).name != filename:
        raise HTTPException(status_code=400, detail="任务文件路径无效")
    target = settings.storage_dir / "jobs" / job_id / filename
    if not target.is_file():
        raise HTTPException(status_code=404, detail="未找到任务文件")
    return target


async def _store_uploads(files: list[UploadFile]) -> tuple[Path, list[Path]]:
    upload_dir = settings.storage_dir / "uploads" / uuid.uuid4().hex
    upload_dir.mkdir(parents=True, exist_ok=False)
    paths: list[Path] = []
    try:
        for uploaded in files:
            filename = Path(uploaded.filename or "").name
            suffix = Path(filename).suffix.lower()
            if not filename or suffix not in ALLOWED_SUFFIXES:
                raise HTTPException(status_code=400, detail=f"不支持文件：{uploaded.filename or '未命名文件'}")
            target = upload_dir / filename
            size = 0
            with target.open("wb") as output:
                while chunk := await uploaded.read(1024 * 1024):
                    size += len(chunk)
                    if size > MAX_UPLOAD_SIZE:
                        raise HTTPException(status_code=413, detail=f"文件过大（单文件上限 {MAX_UPLOAD_SIZE // 1024 // 1024} MB）：{filename}")
                    output.write(chunk)
            paths.append(target)
        return upload_dir, paths
    except Exception:
        shutil.rmtree(upload_dir, ignore_errors=True)
        raise


@app.get("/api/health")
async def health() -> dict[str, str]:
    return {"status": "ok"}


@app.get("/api/themes")
async def themes() -> dict[str, list[str]]:
    return {"themes": list(THEMES)}


@app.post("/api/generate", response_model=GenerationResult)
async def generate(
    request_json: str = Form(..., alias="request"),
    files: list[UploadFile] = File(...),
) -> GenerationResult:
    try:
        request = ContentRequest.model_validate_json(request_json)
    except ValidationError as exc:
        raise HTTPException(status_code=422, detail=exc.errors()) from exc
    if not files:
        raise HTTPException(status_code=400, detail="至少需要上传一份资料")

    upload_dir, paths = await _store_uploads(files)
    try:
        has_images = any(path.suffix.lower() in IMAGE_SUFFIXES for path in paths)
        material_text = await run_in_threadpool(
            merge_materials,
            paths,
            image_to_text=VisionApiClient().describe if has_images else None,
        )
        result = await run_in_threadpool(run_generation, request, material_text)
        return _job_result(result["job_id"], request, result.get("warnings", []))
    except (ProviderUnavailableError, RuntimeError, ValueError) as exc:
        raise HTTPException(status_code=503, detail=_error_message(exc)) from exc
    finally:
        shutil.rmtree(upload_dir, ignore_errors=True)


@app.post("/api/jobs/{job_id}/revision", response_model=GenerationResult)
async def revise(job_id: str, feedback: str = Form(...)) -> GenerationResult:
    try:
        result = await run_in_threadpool(run_revision, job_id, feedback)
        return _job_result(result["job_id"], warnings=result.get("warnings", []))
    except FileNotFoundError as exc:
        raise HTTPException(status_code=404, detail="未找到当前任务") from exc
    except (ProviderUnavailableError, RuntimeError, ValueError) as exc:
        raise HTTPException(status_code=503, detail=_error_message(exc)) from exc


@app.get("/api/jobs/{job_id}/files/{filename}")
async def job_file(job_id: str, filename: str) -> FileResponse:
    target = _safe_job_file(job_id, filename)
    media_types = {
        ".html": "text/html; charset=utf-8",
        ".md": "text/markdown; charset=utf-8",
        ".json": "application/json; charset=utf-8",
    }
    return FileResponse(target, media_type=media_types.get(target.suffix, "application/octet-stream"))


@app.get("/", include_in_schema=False)
async def index() -> FileResponse:
    return FileResponse(FRONTEND_DIR / "index.html")


app.mount("/static", StaticFiles(directory=FRONTEND_DIR), name="static")
