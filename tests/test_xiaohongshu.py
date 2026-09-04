from pathlib import Path

import pytest
from PIL import Image

from app.schemas import Audience, ContentRequest, Platform
from app.workflow import generate_xiaohongshu_note


class FakeHarness:
    def __init__(self) -> None:
        self.user_prompt = ""

    def json(self, _system: str, user: str, _name: str) -> dict:
        self.user_prompt = user
        return {
            "title": "资料也能讲得清楚",
            "caption": "先从读者的问题开始。\n\n一张卡片只讲一个要点。",
            "hashtags": ["#内容创作", "#资料整理"],
            "cards": [
                {
                    "filename": f"{index:02d}.png",
                    "headline": f"第 {index} 个要点",
                    "body": "只保留一个清晰结论\n让读者一眼理解",
                    "visual_focus": "A detailed editorial composition showing the contrast between low and high purity samples in a research setting. " * 3,
                    "prompt": "A clean, text-free editorial desk scene with paper notes and warm daylight",
                }
                for index in range(1, 4)
            ],
        }

    def image(self, _prompt: str, target: Path, *, size: str, quality: str) -> None:
        assert size == "1024x1536"
        assert quality == "high"
        target.parent.mkdir(parents=True, exist_ok=True)
        Image.new("RGB", (1024, 1536), "#9DC7B5").save(target)


def test_xiaohongshu_note_renders_exact_card_count_and_artifacts(tmp_path: Path):
    request = ContentRequest(
        platform=Platform.XIAOHONGSHU,
        topic="测试小红书图文",
        primary_audience=Audience.CONSUMER,
        objective="用资料生成可发布的图文笔记",
        image_count=3,
        theme="摸鱼绿",
    )

    harness = FakeHarness()
    result = generate_xiaohongshu_note(request, "这是可用的资料正文。", tmp_path, harness)

    assert len(result["cards"]) == 3
    assert sorted(path.name for path in (tmp_path / "cards").glob("*.png")) == ["01.png", "02.png", "03.png"]
    with Image.open(tmp_path / "cards" / "01.png") as card:
        assert card.size == (1080, 1440)
    assert (tmp_path / "caption.txt").exists()
    caption_text = (tmp_path / "caption.txt").read_text(encoding="utf-8")
    assert "#内容创作 #资料整理" in caption_text
    assert (tmp_path / "card_plan.json").exists()
    assert (tmp_path / "xiaohongshu_preview.html").exists()
    assert "发布文案长度：约 500 个中文字符。" in harness.user_prompt
    assert "目标长度：约 6500 个中文字符。" not in harness.user_prompt
    assert len(result["cards"][0]["visual_focus"]) == 160


def test_xiaohongshu_requires_at_least_one_card():
    with pytest.raises(ValueError, match="至少需要 1 张卡片"):
        ContentRequest(
            platform=Platform.XIAOHONGSHU,
            topic="测试小红书图文",
            primary_audience=Audience.CONSUMER,
            objective="用资料生成可发布的图文笔记",
            image_count=0,
        )
