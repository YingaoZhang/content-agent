import json
from pathlib import Path
from types import SimpleNamespace

import pytest
from fastapi.testclient import TestClient

from app import api
from app.dependencies import get_settings
from app.routers import content as content_router
from app.services.task_service import persist_job
from tests.db_support import TEST_DATABASE_URL, reset_test_jobs


@pytest.fixture(autouse=True)
def _clear_overrides():
    yield
    api.app.dependency_overrides.clear()


def test_health_and_theme_endpoints():
    client = TestClient(api.app)

    assert client.get("/api/health").json() == {"status": "ok"}
    data = client.get("/api/themes").json()
    assert "石墨极简风" in data["themes"]
    assert "实拍故事" in data["xhs_layouts"]


def _install_overrides(tmp_path: Path, monkeypatch) -> None:
    reset_test_jobs()
    api.app.dependency_overrides[get_settings] = lambda: SimpleNamespace(
        storage_dir=tmp_path, database_url=TEST_DATABASE_URL
    )
    # Never run the real background worker during API tests.
    monkeypatch.setattr(content_router, "submit_job", lambda job_id: None)


def test_generate_endpoint_reserves_pending_job(tmp_path: Path, monkeypatch):
    _install_overrides(tmp_path, monkeypatch)

    def fake_merge(paths, image_to_text=None):
        assert paths[0].read_text(encoding="utf-8") == "资料正文"
        return "# 资料：brief.md\n\n资料正文"

    monkeypatch.setattr(content_router, "merge_materials", fake_merge)

    request = {
        "topic": "测试主题",
        "primary_audience": "consumer",
        "objective": "生成一篇测试文章",
        "image_count": 0,
    }
    response = TestClient(api.app).post(
        "/api/generate",
        data={"request": json.dumps(request)},
        files=[("files", ("brief.md", "资料正文".encode("utf-8"), "text/markdown"))],
    )

    assert response.status_code == 200
    data = response.json()
    assert data["status"] == "pending"
    job_id = data["job_id"]
    assert len(job_id) == 12

    job_dir = tmp_path / "jobs" / job_id
    assert (job_dir / "source_material.md").read_text(encoding="utf-8").endswith("资料正文")
    assert not (tmp_path / "uploads").exists() or not list((tmp_path / "uploads").iterdir())

    detail = TestClient(api.app).get(f"/api/jobs/{job_id}").json()
    assert detail["status"] == "pending"
    assert detail["request"]["topic"] == "测试主题"


def test_outline_then_generate_transitions_to_pending(tmp_path: Path, monkeypatch):
    _install_overrides(tmp_path, monkeypatch)

    def fake_merge(paths, image_to_text=None):
        return "# 资料\n\n原始内容"

    monkeypatch.setattr(content_router, "merge_materials", fake_merge)

    request = {
        "topic": "测试主题",
        "primary_audience": "consumer",
        "objective": "先确认大纲再生成文章",
        "image_count": 0,
        "target_length": 5000,
    }
    client = TestClient(api.app)
    outline_response = client.post(
        "/api/outlines",
        data={"request": json.dumps(request)},
        files=[("files", ("brief.md", "原始内容".encode("utf-8"), "text/markdown"))],
    )
    assert outline_response.status_code == 200
    assert outline_response.json()["status"] == "pending"
    job_id = outline_response.json()["job_id"]

    # Simulate the background worker finishing the outline step.
    job_dir = tmp_path / "jobs" / job_id
    (job_dir / "outline.md").write_text("# 测试标题\n\n## 第一章\n- 要点", encoding="utf-8")
    run_json = json.loads((job_dir / "run.json").read_text(encoding="utf-8"))
    run_json["stage"] = "outline_ready"
    (job_dir / "run.json").write_text(json.dumps(run_json, ensure_ascii=False), encoding="utf-8")
    persist_job(job_id, tmp_path, TEST_DATABASE_URL)

    assert client.get(f"/api/jobs/{job_id}").json()["status"] == "outline_ready"

    generate_response = client.post(
        f"/api/outlines/{job_id}/generate",
        data={"outline": "# 测试标题\n\n## 第一章\n- 调整后的要点"},
    )
    assert generate_response.status_code == 200
    assert generate_response.json() == {"job_id": job_id, "status": "pending"}

    detail = client.get(f"/api/jobs/{job_id}").json()
    assert detail["status"] == "pending"
    assert "调整后的要点" in detail["outline"]


def test_download_images_archive(tmp_path: Path):
    api.app.dependency_overrides[get_settings] = lambda: SimpleNamespace(
        storage_dir=tmp_path, database_url=TEST_DATABASE_URL
    )
    image_dir = tmp_path / "jobs" / "abcdef123456" / "cards"
    image_dir.mkdir(parents=True)
    (image_dir / "01.png").write_bytes(b"one")
    (image_dir / "02.png").write_bytes(b"two")

    response = TestClient(api.app).get("/api/jobs/abcdef123456/images.zip")

    assert response.status_code == 200
    assert response.headers["content-type"] == "application/zip"
    assert b"01.png" in response.content and b"02.png" in response.content
