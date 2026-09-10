import json
from pathlib import Path
from types import SimpleNamespace

import pytest
from fastapi.testclient import TestClient

from app import api
from app.dependencies import get_settings
from app.services.task_service import persist_job
from tests.db_support import TEST_DATABASE_URL, reset_test_jobs


@pytest.fixture(autouse=True)
def _clear_overrides():
    yield
    api.app.dependency_overrides.clear()


def test_task_history_api(tmp_path: Path):
    reset_test_jobs()
    api.app.dependency_overrides[get_settings] = lambda: SimpleNamespace(
        storage_dir=tmp_path, database_url=TEST_DATABASE_URL
    )
    job_id = "abcdef123456"
    job_dir = tmp_path / "jobs" / job_id
    job_dir.mkdir(parents=True)
    request = {
        "topic": "接口任务",
        "primary_audience": "consumer",
        "objective": "测试历史接口",
        "theme": "石墨极简风",
    }
    (job_dir / "run.json").write_text(json.dumps({"request": request, "stage": "outline_ready"}), encoding="utf-8")
    (job_dir / "outline.md").write_text("# 接口任务\n\n## 章节\n- 要点", encoding="utf-8")
    persist_job(job_id, tmp_path, TEST_DATABASE_URL)

    client = TestClient(api.app)
    records = client.get("/api/jobs")
    assert records.status_code == 200
    assert records.json()[0]["job_id"] == job_id

    detail = client.get(f"/api/jobs/{job_id}")
    assert detail.status_code == 200
    assert detail.json()["request"]["objective"] == "测试历史接口"
    assert detail.json()["status"] == "outline_ready"

    deleted = client.delete(f"/api/jobs/{job_id}")
    assert deleted.status_code == 200
    assert deleted.json() == {"deleted": True}
    assert not job_dir.exists()
    assert client.get(f"/api/jobs/{job_id}").status_code == 404
