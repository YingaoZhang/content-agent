from pathlib import Path

from app.schemas import Audience, ContentRequest
from app.workflow import generate_image_plan, generate_images


class ImagePlanningHarness:
    def __init__(self) -> None:
        self.system = ""
        self.user = ""

    def json(self, system: str, user: str, name: str) -> dict:
        assert name == "plan_images"
        self.system = system
        self.user = user
        return {
            "images": [
                {"filename": "first", "placement": "body", "alt": "封面", "visual_focus": "核心机制", "prompt": "A scientist studies a clear serum sample in a sunlit laboratory."},
                {"filename": "second", "placement": "body", "alt": "正文图", "insert_after_heading": "作用机制", "visual_focus": "作用路径", "prompt": "A clean editorial still life showing a serum drop beside a research notebook."},
            ]
        }


class ImageGenerationHarness:
    def __init__(self) -> None:
        self.calls: list[dict] = []

    def image(self, prompt: str, target: Path, *, size: str, quality: str) -> None:
        self.calls.append({"prompt": prompt, "target": target, "size": size, "quality": quality})
        target.write_bytes(b"image")


def test_image_plan_recovers_when_model_omits_optional_planning_fields():
    request = ContentRequest(
        topic="测试主题",
        primary_audience=Audience.CONSUMER,
        objective="生成配图",
        image_count=2,
    )

    class SparsePlanningHarness(ImagePlanningHarness):
        def json(self, system: str, user: str, name: str) -> dict:
            return {"images": [{"filename": "cover.png", "visual_focus": "核心主题"}, {"prompt": "A supporting editorial image"}]}

    result = generate_image_plan({
        "request": request,
        "article": "# 标题\n\n## 章节一\n\n正文",
        "harness": SparsePlanningHarness(),
    })

    assert len(result["image_plan"]) == 2
    assert result["image_plan"][0]["placement"] == "cover"
    assert result["image_plan"][1]["placement"] == "body"
    assert result["image_plan"][0]["alt"] == "核心主题"
    assert result["image_plan"][0]["prompt"]


def test_image_plan_applies_a_consistent_wechat_theme_direction():
    request = ContentRequest(
        topic="麦角硫因的作用机制",
        primary_audience=Audience.CONSUMER,
        objective="介绍产品价值",
        key_points="重点讲清作用机制和使用边界",
        image_count=2,
        theme="石墨极简风",
    )
    harness = ImagePlanningHarness()
    state = {"request": request, "article": "# 标题\n\n引言\n\n## 作用机制\n\n正文", "harness": harness}

    result = generate_image_plan(state)

    cover, body = result["image_plan"]
    assert "公众号主题：石墨极简风" in harness.user
    assert "重点突出内容：重点讲清作用机制和使用边界" in harness.user
    assert cover["placement"] == "cover"
    assert cover["size"] == "1536x1024"
    assert body["size"] == "1024x1024"
    assert all(item["quality"] == "high" for item in result["image_plan"])
    assert "WeChat long-form editorial image series" in cover["prompt"]
    assert "title overlay" in cover["prompt"]
    assert "in-article visual" in body["prompt"]


def test_generation_uses_planned_image_sizes_and_quality(tmp_path: Path):
    harness = ImageGenerationHarness()
    plan = [
        {"filename": "cover.png", "placement": "cover", "alt": "封面", "prompt": "cover prompt", "size": "1536x1024", "quality": "high"},
        {"filename": "body.png", "placement": "body", "alt": "正文", "prompt": "body prompt", "insert_after_heading": "第一节", "size": "1024x1024", "quality": "high"},
    ]

    result = generate_images({"job_dir": str(tmp_path), "image_plan": plan, "article": "# 标题\n\n引言\n\n## 第一节\n\n正文", "harness": harness})

    assert [call["size"] for call in harness.calls] == ["1536x1024", "1024x1024"]
    assert all(call["quality"] == "high" for call in harness.calls)
    assert "images/cover.png" in result["article_with_images"]
