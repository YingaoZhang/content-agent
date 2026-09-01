import json
from pathlib import Path
from types import SimpleNamespace

from fastapi.testclient import TestClient

from app import api


def test_health_and_theme_endpoints():
    client = TestClient(api.app)

    assert client.get("/api/health").json() == {"status": "ok"}
    assert "石墨极简风" in client.get("/api/themes").json()["themes"]


def test_generate_endpoint_stores_materials_and_returns_artifact_urls(tmp_path: Path, monkeypatch):
    monkeypatch.setattr(api, "settings", SimpleNamespace(storage_dir=tmp_path))

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
