import json
import re
import shutil
from datetime import datetime, timezone
from pathlib import Path

from sqlalchemy import DateTime, String, Text, create_engine, select
from sqlalchemy.orm import DeclarativeBase, Mapped, Session, mapped_column


TITLE_PATTERN = re.compile(r"^#\s+(.+?)\s*$", re.M)
JOB_ID_PATTERN = re.compile(r"[a-f0-9]{12}")
_ENGINES = {}


class Base(DeclarativeBase):
    pass


class JobRecord(Base):
    __tablename__ = "content_jobs"

    job_id: Mapped[str] = mapped_column(String(12), primary_key=True)
    status: Mapped[str] = mapped_column(String(32), index=True)
    title: Mapped[str] = mapped_column(String(240))
    topic: Mapped[str] = mapped_column(String(120))
    objective: Mapped[str] = mapped_column(Text)
    theme: Mapped[str] = mapped_column(String(80))
    primary_audience: Mapped[str] = mapped_column(String(80))
    parent_job_id: Mapped[str | None] = mapped_column(String(12), nullable=True, index=True)
    request_json: Mapped[str] = mapped_column(Text)
    outline: Mapped[str] = mapped_column(Text, default="")
    warnings_json: Mapped[str] = mapped_column(Text, default="[]")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=lambda: datetime.now(timezone.utc))
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=lambda: datetime.now(timezone.utc),
        onupdate=lambda: datetime.now(timezone.utc),
    )


def _engine(database_url: str):
    engine = _ENGINES.get(database_url)
    if engine is None:
        connect_args = {"check_same_thread": False} if database_url.startswith("sqlite") else {}
        engine = create_engine(database_url, pool_pre_ping=True, connect_args=connect_args)
        _ENGINES[database_url] = engine
    Base.metadata.create_all(engine)
    return engine


def initialize_database(database_url: str) -> None:
    _engine(database_url)


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
    status = metadata.get("stage") or ("completed" if (job_dir / "article.md").exists() else "outline_ready")
    now = datetime.now(timezone.utc)

    with Session(_engine(database_url)) as session:
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
        if warnings is not None:
            record.warnings_json = json.dumps(warnings, ensure_ascii=False)
        elif "warnings" in metadata:
            record.warnings_json = json.dumps(metadata["warnings"], ensure_ascii=False)
        elif not record.warnings_json:
            record.warnings_json = "[]"
        record.updated_at = now
        session.commit()


def sync_existing_jobs(storage_dir: Path, database_url: str) -> None:
    engine = _engine(database_url)
    with Session(engine) as session:
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
        "parent_job_id": record.parent_job_id,
        "created_at": record.created_at,
        "updated_at": record.updated_at,
    }


def list_jobs(database_url: str, limit: int = 100) -> list[dict]:
    limit = max(1, min(limit, 200))
    with Session(_engine(database_url)) as session:
        records = session.scalars(select(JobRecord).order_by(JobRecord.updated_at.desc()).limit(limit)).all()
        return [_summary(record) for record in records]


def get_job(job_id: str, storage_dir: Path, database_url: str) -> dict | None:
    if not JOB_ID_PATTERN.fullmatch(job_id):
        return None
    with Session(_engine(database_url)) as session:
        record = session.get(JobRecord, job_id)
        if record is None:
            return None
        result = _summary(record)
        result["request"] = json.loads(record.request_json or "{}")
        result["outline"] = record.outline
        result["warnings"] = json.loads(record.warnings_json or "[]")
        completed_status = record.status == "completed"

    job_dir = storage_dir / "jobs" / job_id
    completed = completed_status and (job_dir / "article.md").exists()
    result["markdown_url"] = f"/api/jobs/{job_id}/files/article_with_images.md" if completed else None
    result["html_url"] = f"/api/jobs/{job_id}/files/wechat.html" if completed else None
    result["preview_url"] = f"/api/jobs/{job_id}/files/wechat_preview.html" if completed else None
    images_dir = job_dir / "images"
    result["image_urls"] = [f"/assets/jobs/{job_id}/images/{path.name}" for path in sorted(images_dir.glob("*.png"))] if images_dir.exists() else []
    return result


def delete_job(job_id: str, storage_dir: Path, database_url: str) -> bool:
    if not JOB_ID_PATTERN.fullmatch(job_id):
        return False
    with Session(_engine(database_url)) as session:
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
