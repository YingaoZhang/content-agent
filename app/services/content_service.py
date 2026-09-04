import json
import re
import shutil
import uuid
import zipfile
from pathlib import Path

from fastapi import HTTPException, UploadFile

from ..materials import ALLOWED_SUFFIXES, IMAGE_SUFFIXES
from ..schemas import ContentRequest, GenerationResult


MAX_UPLOAD_SIZE = 25 * 1024 * 1024
TITLE_PATTERN = re.compile(r"^#\s+(.+?)\s*$", re.M)


def database_url(settings) -> str:
    configured_url = getattr(settings, "database_url", "")
    if not configured_url:
        raise RuntimeError("未配置 DATABASE_URL，请使用 Docker Compose 启动 PostgreSQL")
    return configured_url


def error_message(error: Exception) -> str:
    return str(error) or "请求处理失败"


async def store_uploads(files: list[UploadFile], storage_dir: Path) -> tuple[Path, list[Path]]:
    upload_dir = storage_dir / "uploads" / uuid.uuid4().hex
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
                        raise HTTPException(
                            status_code=413,
                            detail=f"文件过大（单文件上限 {MAX_UPLOAD_SIZE // 1024 // 1024} MB）：{filename}",
                        )
                    output.write(chunk)
            paths.append(target)
        return upload_dir, paths
    except Exception:
        shutil.rmtree(upload_dir, ignore_errors=True)
        raise


def has_image_materials(paths: list[Path]) -> bool:
    return any(path.suffix.lower() in IMAGE_SUFFIXES for path in paths)


def build_generation_result(
    job_id: str,
    storage_dir: Path,
    request: ContentRequest | None = None,
    warnings: list[str] | None = None,
) -> GenerationResult:
    job_dir = storage_dir / "jobs" / job_id
    if not job_dir.is_dir():
        raise HTTPException(status_code=404, detail="未找到该任务")
    article_path = job_dir / "article.md"
    if not article_path.exists():
        raise HTTPException(status_code=404, detail="任务尚未生成文章产物")
    article = article_path.read_text(encoding="utf-8", errors="replace")
    metadata: dict = {}
    run_path = job_dir / "run.json"
    if run_path.exists():
        try:
            metadata = json.loads(run_path.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, OSError):
            metadata = {}
    if request is None and metadata.get("request"):
        try:
            request = ContentRequest.model_validate(metadata["request"])
        except ValueError:
            pass
    title_match = TITLE_PATTERN.search(article)
    title = title_match.group(1).strip() if title_match else request.topic if request else "公众号文章"
    platform = (request.model_dump(mode="json").get("platform") if request else None) or "wechat"
    image_folder = "cards" if platform == "xiaohongshu" else "images"
    images_dir = job_dir / image_folder
    image_urls = (
        [f"/assets/jobs/{job_id}/{image_folder}/{path.name}" for path in sorted(images_dir.glob("*.png"))]
        if images_dir.exists()
        else []
    )
    images_zip_url = f"/api/jobs/{job_id}/images.zip" if image_urls else None
    resolved_warnings = warnings or []
    resolved_warnings = metadata.get("warnings", resolved_warnings)
    return GenerationResult(
        job_id=job_id,
        title=title,
        markdown_url=f"/api/jobs/{job_id}/files/article_with_images.md",
        html_url=f"/api/jobs/{job_id}/files/{'xiaohongshu_preview.html' if platform == 'xiaohongshu' else 'wechat.html'}",
        preview_url=f"/api/jobs/{job_id}/files/{'xiaohongshu_preview.html' if platform == 'xiaohongshu' else 'wechat_preview.html'}",
        image_urls=image_urls,
        images_zip_url=images_zip_url,
        warnings=resolved_warnings,
        platform=platform,
        caption_url=f"/api/jobs/{job_id}/files/caption.txt" if platform == "xiaohongshu" and (job_dir / "caption.txt").exists() else None,
        card_plan_url=f"/api/jobs/{job_id}/files/card_plan.json" if platform == "xiaohongshu" and (job_dir / "card_plan.json").exists() else None,
    )


def build_images_archive(job_id: str, storage_dir: Path) -> Path:
    """Create a fresh ZIP containing all generated PNGs for a job."""
    if not re.fullmatch(r"[a-f0-9]{12}", job_id):
        raise HTTPException(status_code=400, detail="任务编号无效")
    job_dir = storage_dir / "jobs" / job_id
    if not job_dir.is_dir():
        raise HTTPException(status_code=404, detail="未找到该任务")
    image_dir = job_dir / ("cards" if (job_dir / "cards").exists() else "images")
    files = sorted(image_dir.glob("*.png")) if image_dir.exists() else []
    if not files:
        raise HTTPException(status_code=404, detail="该任务尚未生成图片")
    archive = job_dir / "images.zip"
    with zipfile.ZipFile(archive, "w", compression=zipfile.ZIP_DEFLATED) as bundle:
        for path in files:
            bundle.write(path, arcname=path.name)
    return archive


def safe_job_file(job_id: str, filename: str, storage_dir: Path) -> Path:
    if not re.fullmatch(r"[a-f0-9]{12}", job_id) or Path(filename).name != filename:
        raise HTTPException(status_code=400, detail="任务文件路径无效")
    target = storage_dir / "jobs" / job_id / filename
    if not target.is_file():
        raise HTTPException(status_code=404, detail="未找到任务文件")
    return target
