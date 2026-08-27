import json
from pathlib import Path
from types import SimpleNamespace

from app import workflow
from app.schemas import Audience, ContentRequest


class FakeHarness:
    def __init__(self, enable_image_generation: bool = True) -> None:
        self.enable_image_generation = enable_image_generation
        self.text_api = self
        self.trace = []

    def text(self, system: str, user: str, name: str) -> str:
        self.trace.append({"node": name})
        return "# 修改后的标题\n\n这是根据修改意见调整后的正文。"


def test_revision_creates_a_new_version_without_images(tmp_path: Path, monkeypatch):
    request = ContentRequest(
        topic="原始标题",
        primary_audience=Audience.CONSUMER,
        objective="测试修改流程",
        image_count=0,
    )
    parent_id = "parent-job"
    parent_dir = tmp_path / "jobs" / parent_id
    parent_dir.mkdir(parents=True)
    (parent_dir / "source_material.md").write_text("原始资料", encoding="utf-8")
    (parent_dir / "article.md").write_text("# 原始标题\n\n原始正文", encoding="utf-8")
    (parent_dir / "run.json").write_text(json.dumps({"request": request.model_dump(mode="json")}), encoding="utf-8")

    def fake_render(text_api, markdown: str, theme: str, output_dir: Path):
        html_path = output_dir / "wechat.html"
        preview_path = output_dir / "wechat_preview.html"
        html_path.write_text("<section>修改后的成品</section>", encoding="utf-8")
        preview_path.write_text("<html></html>", encoding="utf-8")
        return html_path, preview_path, []

    monkeypatch.setattr(
        workflow,
        "settings",
        SimpleNamespace(
            storage_dir=tmp_path,
            text_base_url="https://text.example.test/v1",
            text_model="test-text-model",
            image_base_url="https://image.example.test/v1",
            image_model="test-image-model",
        ),
    )
    monkeypatch.setattr(workflow, "ContentModelHarness", FakeHarness)
    monkeypatch.setattr(workflow, "render_wechat_html", fake_render)

    result = workflow.run_revision(parent_id, "把语气改得更专业")
    revision_dir = tmp_path / "jobs" / result["job_id"]

    assert result["job_id"] != parent_id
    assert (parent_dir / "article.md").read_text(encoding="utf-8") == "# 原始标题\n\n原始正文"
    assert (revision_dir / "article.md").read_text(encoding="utf-8").startswith("# 修改后的标题")
    assert (revision_dir / "image_plan.json").read_text(encoding="utf-8") == "[]\n"
    metadata = json.loads((revision_dir / "run.json").read_text(encoding="utf-8"))
    assert metadata["parent_job_id"] == parent_id
