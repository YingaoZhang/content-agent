import json
from pathlib import Path
from types import SimpleNamespace

from fastapi.testclient import TestClient

from app import api
from tests.db_support import TEST_DATABASE_URL, reset_test_jobs


def test_health_and_theme_endpoints():
    client = TestClient(api.app)

    assert client.get("/api/health").json() == {"status": "ok"}
    assert "石墨极简风" in client.get("/api/themes").json()["themes"]


def test_generate_endpoint_stores_materials_and_returns_artifact_urls(tmp_path: Path, monkeypatch):
    reset_test_jobs()
    monkeypatch.setattr(api, "settings", SimpleNamespace(storage_dir=tmp_path, database_url=TEST_DATABASE_URL))

    def fake_merge(paths, image_to_text=None):
        assert paths[0].read_text(encoding="utf-8") == "资料正文"
        return "# 资料：brief.md\n\n资料正文"

    def fake_run_generation(request, material_text):
        assert request.theme == "石墨极简风"
        assert material_text.endswith("资料正文")
        job_dir = tmp_path / "jobs" / "abcdef123456"
        job_dir.mkdir(parents=True)
        (job_dir / "article.md").write_text("# 测试成品\n\n正文", encoding="utf-8")
        (job_dir / "article_with_images.md").write_text("# 测试成品\n\n正文", encoding="utf-8")
        (job_dir / "wechat.html").write_text("<section>成品</section>", encoding="utf-8")
        (job_dir / "wechat_preview.html").write_text("<html></html>", encoding="utf-8")
        return {"job_id": "abcdef123456", "warnings": ["测试提示"]}

    monkeypatch.setattr(api, "merge_materials", fake_merge)
    monkeypatch.setattr(api, "run_generation", fake_run_generation)

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
    assert data["title"] == "测试成品"
    assert data["preview_url"] == "/api/jobs/abcdef123456/files/wechat_preview.html"
    assert data["warnings"] == ["测试提示"]
    assert not (tmp_path / "uploads").exists() or not list((tmp_path / "uploads").iterdir())


def test_outline_then_generate_endpoints_preserve_quality_controls(tmp_path: Path, monkeypatch):
    reset_test_jobs()
    monkeypatch.setattr(api, "settings", SimpleNamespace(storage_dir=tmp_path, database_url=TEST_DATABASE_URL))

    def fake_merge(paths, image_to_text=None):
        return "# 资料\n\n原始内容"

    def fake_outline(request, material_text):
        assert request.target_length == 5000
        assert request.tone == "理性、克制"
        assert request.forbidden_words == "夸大"
        assert material_text.endswith("原始内容")
        return {"job_id": "abcdef123456", "outline": "# 测试标题\n\n## 第一章\n- 要点"}

    def fake_generate_from_outline(job_id, outline):
        assert job_id == "abcdef123456"
        assert "调整后的要点" in outline
        job_dir = tmp_path / "jobs" / job_id
        job_dir.mkdir(parents=True)
        (job_dir / "article.md").write_text("# 已确认成品\n\n正文", encoding="utf-8")
        (job_dir / "article_with_images.md").write_text("# 已确认成品\n\n正文", encoding="utf-8")
        (job_dir / "wechat.html").write_text("<section>成品</section>", encoding="utf-8")
        (job_dir / "wechat_preview.html").write_text("<html></html>", encoding="utf-8")
        return {"job_id": job_id, "warnings": []}

    monkeypatch.setattr(api, "merge_materials", fake_merge)
    monkeypatch.setattr(api, "run_outline_generation", fake_outline)
    monkeypatch.setattr(api, "run_generation_from_outline", fake_generate_from_outline)
    client = TestClient(api.app)
    request = {
        "topic": "测试主题",
        "primary_audience": "consumer",
        "objective": "先确认大纲再生成文章",
        "image_count": 0,
        "target_length": 5000,
        "tone": "理性、克制",
        "forbidden_words": "夸大",
    }
    outline_response = client.post(
        "/api/outlines",
        data={"request": json.dumps(request)},
        files=[("files", ("brief.md", "原始内容".encode("utf-8"), "text/markdown"))],
    )
    assert outline_response.status_code == 200
    assert outline_response.json()["job_id"] == "abcdef123456"

    response = client.post(
        "/api/outlines/abcdef123456/generate",
        data={"outline": "# 测试标题\n\n## 第一章\n- 调整后的要点"},
    )
    assert response.status_code == 200
    assert response.json()["title"] == "已确认成品"
