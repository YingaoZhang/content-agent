from pathlib import Path

from app.schemas import Audience, ContentRequest
from app.workflow import generate_image_plan, generate_images


def make_request(image_count: int) -> ContentRequest:
    return ContentRequest(
        topic="测试主题",
        primary_audience=Audience.CONSUMER,
        objective="测试图片数量选项",
        image_count=image_count,
    )


def test_image_count_accepts_zero_through_nine():
    for count in range(10):
        assert make_request(count).image_count == count


def test_zero_images_skips_planning_and_generation(tmp_path: Path):
    request = make_request(0)
    state = {"request": request, "article": "# 测试文章\n\n正文内容", "harness": object(), "job_dir": str(tmp_path)}

    plan = generate_image_plan(state)
    assert plan == {"image_plan": []}

    result = generate_images({**state, **plan})
    assert result["image_plan"] == []
    assert result["article_with_images"] == state["article"]
    assert (tmp_path / "image_plan.json").read_text(encoding="utf-8") == "[]\n"
    assert (tmp_path / "article_with_images.md").read_text(encoding="utf-8") == state["article"]
