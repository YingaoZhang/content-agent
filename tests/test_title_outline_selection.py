import json
from pathlib import Path
from types import SimpleNamespace

import pytest
from fastapi.testclient import TestClient

from app import api, workflow
from app.services import generation_service
from app.dependencies import get_settings
from app.routers import content as content_router
from app.schemas import Audience, ContentRequest
from app.services.task_service import persist_job
from tests.db_support import TEST_DATABASE_URL, reset_test_jobs


class RecordingHarness:
    instances: list["RecordingHarness"] = []

    def __init__(self, enable_image_generation: bool = False) -> None:
        self.enable_image_generation = enable_image_generation
        self.text_api = self
        self.trace = []
        self.calls = []
        RecordingHarness.instances.append(self)

    def json(self, system: str, user: str, name: str) -> dict:
        self.calls.append(("json", name, user))
        if name == "plan_article_titles":
            return {"titles": ["标题一", "标题二", "标题三", "标题四", "标题五"]}
        if name == "plan_article_outlines":
            return {
                "outlines": [
                    "# 标题二\n\n## 章节一\n- 要点甲\n- 要点乙",
                    "# 标题二\n\n## 章节甲\n- 要点丙\n- 要点丁",
                ]
            }
        return {}

    def text(self, system: str, user: str, name: str) -> str:
        self.calls.append(("text", name, user))
        return "# 标题二\n\n这是正文内容，包含足够的字数以通过大纲与正文校验。"


def _settings(tmp_path: Path) -> SimpleNamespace:
    return SimpleNamespace(
        storage_dir=tmp_path,
        text_base_url="https://text.example.test/v1",
        text_model="test-text-model",
        image_base_url="https://image.example.test/v1",
        image_model="test-image-model",
        article_min_chars=800,
        image_cover_size="1536x1024",
        image_body_size="1024x1024",
        image_quality="high",
    )


def _request() -> ContentRequest:
    return ContentRequest(topic="测试主题", primary_audience=Audience.CONSUMER, objective="测试目标", image_count=0)


def test_titles_then_outlines_stages(tmp_path: Path, monkeypatch):
    monkeypatch.setattr(generation_service, "settings", _settings(tmp_path))
    monkeypatch.setattr(generation_service, "ContentModelHarness", RecordingHarness)

    job_id = generation_service.prepare_outline(_request(), "资料内容", tmp_path)
    titles_result = generation_service.run_titles_job(job_id, tmp_path)
    assert titles_result["titles"] == ["标题一", "标题二", "标题三", "标题四", "标题五"]

    run_path = tmp_path / "jobs" / job_id / "run.json"
    metadata = json.loads(run_path.read_text(encoding="utf-8"))
    assert metadata["stage"] == "titles_ready"
    assert metadata["titles"] == titles_result["titles"]

    generation_service.select_title(job_id, "标题二", tmp_path)
    metadata = json.loads(run_path.read_text(encoding="utf-8"))
    assert metadata["selected_title"] == "标题二"
    assert metadata["kind"] == "outlines"
    assert metadata["stage"] == "pending"

    outlines_result = generation_service.run_outlines_job(job_id, tmp_path)
    assert len(outlines_result["outlines"]) == 2
    metadata = json.loads(run_path.read_text(encoding="utf-8"))
    assert metadata["stage"] == "outline_ready"
    assert metadata["selected_title"] == "标题二"
    assert len(metadata["outlines"]) == 2


def test_generation_uses_selected_title(tmp_path: Path, monkeypatch):
    monkeypatch.setattr(generation_service, "settings", _settings(tmp_path))
    monkeypatch.setattr(generation_service, "ContentModelHarness", RecordingHarness)

    def fake_render(text_api, markdown: str, theme: str, output_dir: Path):
        (output_dir / "wechat.html").write_text("<section>成品</section>", encoding="utf-8")
        (output_dir / "wechat_preview.html").write_text("<html></html>", encoding="utf-8")
        return output_dir / "wechat.html", output_dir / "wechat_preview.html", []

    monkeypatch.setattr(workflow, "render_wechat_html", fake_render)

    job_id = generation_service.prepare_outline(_request(), "资料内容", tmp_path)
    generation_service.run_titles_job(job_id, tmp_path)
    generation_service.select_title(job_id, "标题二", tmp_path)
    generation_service.run_outlines_job(job_id, tmp_path)
    generation_service.accept_outline(job_id, "# 标题二\n\n## 章节一\n- 要点内容足够长", tmp_path, title="标题二")

    generation_service.run_generation_from_outline_job(job_id, tmp_path)

    article = (tmp_path / "jobs" / job_id / "article.md").read_text(encoding="utf-8")
    assert article.startswith("# 标题二")

    generation_harness = RecordingHarness.instances[-1]
    article_calls = [c for c in generation_harness.calls if c[0] == "text" and c[1] == "generate_master_content"]
    assert article_calls
    assert "已选定标题" in article_calls[0][2]
    assert "标题二" in article_calls[0][2]


def test_api_title_selection_endpoint(tmp_path: Path, monkeypatch):
    reset_test_jobs()
    api.app.dependency_overrides[get_settings] = lambda: SimpleNamespace(
        storage_dir=tmp_path, database_url=TEST_DATABASE_URL
    )
    monkeypatch.setattr(content_router, "submit_job", lambda job_id: None)

    request = {
        "topic": "测试主题",
        "primary_audience": "consumer",
        "objective": "生成一篇测试文章",
        "image_count": 0,
    }
    client = TestClient(api.app)
    outline_response = client.post(
        "/api/outlines",
        data={"request": json.dumps(request)},
        files=[("files", ("brief.md", "原始内容".encode("utf-8"), "text/markdown"))],
    )
    job_id = outline_response.json()["job_id"]

    job_dir = tmp_path / "jobs" / job_id
    run_json = json.loads((job_dir / "run.json").read_text(encoding="utf-8"))
    run_json["stage"] = "titles_ready"
    run_json["titles"] = ["标题一", "标题二", "标题三", "标题四", "标题五"]
    (job_dir / "run.json").write_text(json.dumps(run_json, ensure_ascii=False), encoding="utf-8")
    persist_job(job_id, tmp_path, TEST_DATABASE_URL)

    detail = client.get(f"/api/jobs/{job_id}").json()
    assert detail["status"] == "titles_ready"
    assert len(detail["titles"]) == 5

    select_response = client.post(f"/api/outlines/{job_id}/titles", data={"title": "标题二"})
    assert select_response.status_code == 200
    assert select_response.json() == {"job_id": job_id, "status": "pending"}

    detail = client.get(f"/api/jobs/{job_id}").json()
    assert detail["selected_title"] == "标题二"
    assert detail["status"] == "pending"


@pytest.fixture(autouse=True)
def _clear_overrides():
    yield
    api.app.dependency_overrides.clear()
