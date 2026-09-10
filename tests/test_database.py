import json
from pathlib import Path

import pytest

from app.models.database import create_engine_for_url, initialize_database
from app.services.task_service import delete_job, get_job, list_jobs, persist_job
from tests.db_support import TEST_DATABASE_URL, reset_test_jobs
from app.config import Settings


def _write_job(storage_dir: Path, job_id: str, stage: str = "completed") -> Path:
    job_dir = storage_dir / "jobs" / job_id
    job_dir.mkdir(parents=True)
    request = {
        "topic": "数据库任务",
        "primary_audience": "consumer",
        "objective": "验证历史任务保存",
        "theme": "石墨极简风",
    }
    (job_dir / "run.json").write_text(
        json.dumps({"request": request, "stage": stage, "warnings": ["检查提示"]}, ensure_ascii=False),
        encoding="utf-8",
    )
    (job_dir / "outline.md").write_text("# 数据库任务\n\n## 第一章\n- 任务要点", encoding="utf-8")
    if stage == "completed":
        (job_dir / "article.md").write_text("# 数据库任务\n\n正文", encoding="utf-8")
        (job_dir / "article_with_images.md").write_text("# 数据库任务\n\n正文", encoding="utf-8")
        (job_dir / "wechat.html").write_text("<section>正文</section>", encoding="utf-8")
        (job_dir / "wechat_preview.html").write_text("<html></html>", encoding="utf-8")
    return job_dir


def test_postgres_task_lifecycle(tmp_path: Path):
    database_url = TEST_DATABASE_URL
    reset_test_jobs()
    initialize_database(database_url)
    _write_job(tmp_path, "abcdef123456")
    persist_job("abcdef123456", tmp_path, database_url)

    records = list_jobs(database_url)
    assert len(records) == 1
    assert records[0]["title"] == "数据库任务"
    assert records[0]["status"] == "completed"

    detail = get_job("abcdef123456", tmp_path, database_url)
    assert detail is not None
    assert detail["request"]["primary_audience"] == "consumer"
    assert detail["preview_url"].endswith("wechat_preview.html")
    assert detail["warnings"] == ["检查提示"]

    assert delete_job("abcdef123456", tmp_path, database_url) is True
    assert get_job("abcdef123456", tmp_path, database_url) is None
    assert not (tmp_path / "jobs" / "abcdef123456").exists()


def test_outline_task_is_saved_without_completed_artifacts(tmp_path: Path):
    database_url = TEST_DATABASE_URL
    reset_test_jobs()
    job_dir = _write_job(tmp_path, "fedcba654321", stage="outline_ready")
    persist_job("fedcba654321", tmp_path, database_url)

    detail = get_job("fedcba654321", tmp_path, database_url)
    assert detail is not None
    assert detail["status"] == "outline_ready"
    assert detail["outline"].startswith("# 数据库任务")
    assert detail["preview_url"] is None
    assert job_dir.exists()


def test_postgres_database_url_is_required():
    docker_settings = Settings(database_url=TEST_DATABASE_URL)
    assert docker_settings.database_url.startswith("postgresql+psycopg://")
    with pytest.raises(ValueError, match=r"postgresql\+psycopg"):
        create_engine_for_url("mysql://content_agent:content_agent@db/content_agent")
