import json
import re
import shutil
from datetime import datetime, timezone
from pathlib import Path

from sqlalchemy import select
from sqlalchemy.orm import Session

from ..models.database import JobRecord, get_engine


TITLE_PATTERN = re.compile(r"^#\s+(.+?)\s*$", re.M)
JOB_ID_PATTERN = re.compile(r"[a-f0-9]{12}")


def _read_json(path: Path) -> dict:
    try:
        return json.loads(path.read_text(encoding="utf-8")) if path.exists() else {}
    except (json.JSONDecodeError, OSError):
        return {}


def _title_from_job(job_dir: Path, fallback: str) -> str:
    for filename in ("article.md", "outline.md"):
        path = job_dir / filename
        if path.exists():
            match = TITLE_PATTERN.search(path.read_text(encoding="utf-8", errors="replace"))
            if match:
                return match.group(1).strip()
    return fallback or "未命名任务"


def persist_job(job_id: str, storage_dir: Path, database_url: str, warnings: list[str] | None = None) -> None:
    if not JOB_ID_PATTERN.fullmatch(job_id):
        raise ValueError("任务编号无效")
    job_dir = storage_dir / "jobs" / job_id
    metadata = _read_json(job_dir / "run.json")
    request = metadata.get("request", {})
    outline_path = job_dir / "outline.md"
    outline = outline_path.read_text(encoding="utf-8", errors="replace") if outline_path.exists() else ""
    stage = metadata.get("stage")
    if stage in ("pending", "titles_ready", "outline_ready", "completed", "failed"):
        status = stage
    else:
        status = "completed" if (job_dir / "article.md").exists() else "outline_ready"
    now = datetime.now(timezone.utc)

    with Session(get_engine(database_url)) as session:
        record = session.get(JobRecord, job_id)
        if record is None:
            record = JobRecord(job_id=job_id, created_at=now, updated_at=now)
            session.add(record)
        record.status = status
        record.title = _title_from_job(job_dir, request.get("topic", ""))
        record.topic = request.get("topic", "")
        record.objective = request.get("objective", "")
        record.theme = request.get("theme", "")
        record.primary_audience = request.get("primary_audience", "")
        record.parent_job_id = metadata.get("parent_job_id")
        record.request_json = json.dumps(request, ensure_ascii=False)
        record.outline = outline
        record.error = metadata.get("error")
        if warnings is not None:
            record.warnings_json = json.dumps(warnings, ensure_ascii=False)
        elif "warnings" in metadata:
            record.warnings_json = json.dumps(metadata["warnings"], ensure_ascii=False)
        elif not record.warnings_json:
            record.warnings_json = "[]"
        record.updated_at = now
        session.commit()


def sync_existing_jobs(storage_dir: Path, database_url: str) -> None:
    with Session(get_engine(database_url)) as session:
        known_job_ids = set(session.scalars(select(JobRecord.job_id)).all())
    jobs_dir = storage_dir / "jobs"
    if not jobs_dir.exists():
        return
    for job_dir in jobs_dir.iterdir():
        if (
            job_dir.name not in known_job_ids
            and job_dir.is_dir()
            and JOB_ID_PATTERN.fullmatch(job_dir.name)
            and (job_dir / "run.json").exists()
        ):
            persist_job(job_dir.name, storage_dir, database_url)


def _summary(record: JobRecord) -> dict:
    return {
        "job_id": record.job_id,
        "status": record.status,
        "title": record.title,
        "topic": record.topic,
        "objective": record.objective,
        "theme": record.theme,
        "platform": json.loads(record.request_json or "{}").get("platform", "wechat"),
        "parent_job_id": record.parent_job_id,
        "created_at": record.created_at,
        "updated_at": record.updated_at,
        "error": record.error,
    }


def set_job_status(
    job_id: str,
    storage_dir: Path,
    database_url: str,
    status: str,
    error: str | None = None,
) -> None:
    if not JOB_ID_PATTERN.fullmatch(job_id):
        return
    with Session(get_engine(database_url)) as session:
        record = session.get(JobRecord, job_id)
        if record is None:
            return
        record.status = status
        if error is not None:
            record.error = error
        record.updated_at = datetime.now(timezone.utc)
        session.commit()


def get_pending_job_ids(database_url: str) -> list[str]:
    with Session(get_engine(database_url)) as session:
        return list(
            session.scalars(
                select(JobRecord.job_id).where(JobRecord.status.in_(("pending", "running")))
            ).all()
        )


def list_jobs(database_url: str, limit: int = 100) -> list[dict]:
    limit = max(1, min(limit, 200))
    with Session(get_engine(database_url)) as session:
        records = session.scalars(select(JobRecord).order_by(JobRecord.updated_at.desc()).limit(limit)).all()
        return [_summary(record) for record in records]


def get_job(job_id: str, storage_dir: Path, database_url: str) -> dict | None:
    if not JOB_ID_PATTERN.fullmatch(job_id):
        return None
    with Session(get_engine(database_url)) as session:
        record = session.get(JobRecord, job_id)
        if record is None:
            return None
        result = _summary(record)
        result["request"] = json.loads(record.request_json or "{}")
        result["outline"] = record.outline
        result["warnings"] = json.loads(record.warnings_json or "[]")
        completed_status = record.status == "completed"

    job_dir = storage_dir / "jobs" / job_id
    metadata = _read_json(job_dir / "run.json")
    result["titles"] = metadata.get("titles", [])
    result["outlines"] = metadata.get("outlines", [])
    result["selected_title"] = metadata.get("selected_title", "")
    completed = completed_status and (job_dir / "article.md").exists()
    result["markdown_url"] = f"/api/jobs/{job_id}/files/article_with_images.md" if completed else None
    platform = result["request"].get("platform", "wechat")
    result["html_url"] = (
        f"/api/jobs/{job_id}/files/{'xiaohongshu_preview.html' if platform == 'xiaohongshu' else 'wechat.html'}"
        if completed
        else None
    )
    preview_file = "xiaohongshu_preview.html" if platform == "xiaohongshu" else "wechat_preview.html"
    result["preview_url"] = f"/api/jobs/{job_id}/files/{preview_file}" if completed and (job_dir / preview_file).exists() else None
    result["image_urls"] = (
        [f"/assets/jobs/{job_id}/{('cards' if platform == 'xiaohongshu' else 'images')}/{path.name}" for path in sorted((job_dir / ('cards' if platform == 'xiaohongshu' else 'images')).glob("*.png"))]
        if (job_dir / ('cards' if platform == 'xiaohongshu' else 'images')).exists()
        else []
    )
    result["images_zip_url"] = f"/api/jobs/{job_id}/images.zip" if result["image_urls"] else None
    result["caption_url"] = f"/api/jobs/{job_id}/files/caption.txt" if platform == "xiaohongshu" and (job_dir / "caption.txt").exists() else None
    result["card_plan_url"] = f"/api/jobs/{job_id}/files/card_plan.json" if platform == "xiaohongshu" and (job_dir / "card_plan.json").exists() else None
    return result


def delete_job(job_id: str, storage_dir: Path, database_url: str) -> bool:
    if not JOB_ID_PATTERN.fullmatch(job_id):
        return False
    with Session(get_engine(database_url)) as session:
        record = session.get(JobRecord, job_id)
        if record is None:
            return False
        session.delete(record)
        session.commit()
    job_dir = (storage_dir / "jobs" / job_id).resolve()
    jobs_root = (storage_dir / "jobs").resolve()
    if job_dir.parent == jobs_root and job_dir.exists():
        shutil.rmtree(job_dir)
    return True
