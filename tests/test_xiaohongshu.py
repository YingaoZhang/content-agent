from pathlib import Path

import pytest
from PIL import Image

from app.schemas import Audience, ContentRequest, Platform
from app.channels.xiaohongshu import generate_xiaohongshu_note
from app.xiaohongshu_adapter import CARD_SIZE, render_card


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
                    "role": "cover" if index == 1 else "content",
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

    def enable_image_generation(self) -> None:
        pass


def _reference_images(tmp_path: Path, count: int) -> list[Path]:
    references = []
    for index in range(count):
        path = tmp_path / f"reference-{index + 1}.jpg"
        Image.new("RGB", (1600, 1200), (80 + index * 20, 150, 120)).save(path)
        references.append(path)
    return references


def test_xiaohongshu_note_renders_exact_card_count_and_artifacts(tmp_path: Path):
    request = ContentRequest(
        platform=Platform.XIAOHONGSHU,
        topic="测试小红书图文",
        primary_audience=Audience.CONSUMER,
        objective="用资料生成可发布的图文笔记",
        image_count=3,
        theme="摸鱼绿",
        caption_length=500,
    )

    harness = FakeHarness()
    result = generate_xiaohongshu_note(request, "这是可用的资料正文。", tmp_path, harness, _reference_images(tmp_path, 3))

    assert len(result["cards"]) == 3
    assert result["cards"][0]["role"] == "cover"
    assert all(card["layout"] == "实拍故事" for card in result["cards"])
    assert all(card["image_source"] == "uploaded_photo" for card in result["cards"])
    assert sorted(path.name for path in (tmp_path / "cards").glob("*.png")) == ["01.png", "02.png", "03.png"]
    with Image.open(tmp_path / "cards" / "01.png") as card:
        assert card.size == (1080, 1440)
    assert (tmp_path / "caption.txt").exists()
    caption_text = (tmp_path / "caption.txt").read_text(encoding="utf-8")
    assert "#内容创作 #资料整理" in caption_text
    assert (tmp_path / "card_plan.json").exists()
    assert (tmp_path / "xiaohongshu_preview.html").exists()
    assert "发布文案长度：约 500 个中文字符" in harness.user_prompt
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


def test_xiaohongshu_recovers_when_model_omits_image_prompt(tmp_path: Path):
    request = ContentRequest(
        platform=Platform.XIAOHONGSHU,
        topic="测试小红书图文",
        primary_audience=Audience.CONSUMER,
        objective="用资料生成可发布的图文笔记",
        image_count=1,
    )

    class MissingPromptHarness(FakeHarness):
        def json(self, _system: str, _user: str, _name: str) -> dict:
            return {
                "title": "测试标题",
                "caption": "测试文案",
                "hashtags": ["#内容创作"],
                "cards": [{
                    "filename": "01.png",
                    "headline": "核心观点",
                    "body": "一条说明",
                    "visual_focus": "一位用户查看原料细节",
                }],
            }

    result = generate_xiaohongshu_note(request, "可用资料正文", tmp_path, MissingPromptHarness(), _reference_images(tmp_path, 1))
    assert result["cards"][0]["prompt"] == ""


def test_xiaohongshu_fills_remaining_cards_with_ai_when_photos_run_out(tmp_path: Path):
    request = ContentRequest(
        platform=Platform.XIAOHONGSHU,
        topic="测试小红书图文",
        primary_audience=Audience.CONSUMER,
        objective="用资料生成可发布的图文笔记",
        image_count=2,
    )
    class TwoCardHarness(FakeHarness):
        def json(self, _system: str, _user: str, _name: str) -> dict:
            data = super().json(_system, _user, _name)
            data["cards"] = data["cards"][:2]
            return data

    result = generate_xiaohongshu_note(request, "可用资料正文", tmp_path, TwoCardHarness(), _reference_images(tmp_path, 1))

    assert len(result["cards"]) == request.image_count
    assert result["cards"][0]["image_source"] == "uploaded_photo"
    assert result["cards"][1]["image_source"] == "ai_illustration"
    assert (tmp_path / "images" / "xhs-ai-source-02.png").exists()


def test_xiaohongshu_reports_missing_ai_output_file(tmp_path: Path):
    request = ContentRequest(
        platform=Platform.XIAOHONGSHU,
        topic="抽象机制说明",
        primary_audience=Audience.CONSUMER,
        objective="解释一个抽象机制",
        image_count=1,
    )

    class NoOutputHarness(FakeHarness):
        def json(self, _system: str, _user: str, _name: str) -> dict:
            data = super().json(_system, _user, _name)
            data["cards"] = data["cards"][:1]
            return data

        def image(self, _prompt: str, _target: Path, *, size: str, quality: str) -> None:
            return

    with pytest.raises(RuntimeError, match="AI 图片未成功写入"):
        generate_xiaohongshu_note(request, "可用资料正文", tmp_path, NoOutputHarness(), [])


def test_xiaohongshu_generates_ai_when_reality_sensitive_card_has_no_photo(tmp_path: Path):
    request = ContentRequest(
        platform=Platform.XIAOHONGSHU,
        topic="实验室记录",
        primary_audience=Audience.RD_FORMULATOR,
        objective="展示实验室资料",
        image_count=2,
    )

    class RealitySensitiveHarness(FakeHarness):
        def json(self, _system: str, _user: str, _name: str) -> dict:
            return {
                "title": "实验记录",
                "caption": "资料摘要",
                "hashtags": ["#实验室"],
                "cards": [
                    {
                        "filename": "01.png",
                        "role": "cover",
                        "headline": "实验室设备细节",
                        "body": "展示真实仪器与样品。",
                        "visual_focus": "实验室仪器与样品",
                    },
                    {
                        "filename": "02.png",
                        "role": "content",
                        "headline": "机制说明",
                        "body": "用图示解释抽象机制。",
                        "visual_focus": "抽象机制路径",
                        "prompt": "A text-free abstract editorial diagram of a mechanism",
                    },
                ],
            }

    result = generate_xiaohongshu_note(
        request,
        "可用资料正文",
        tmp_path,
        RealitySensitiveHarness(),
        [],
    )

    assert len(result["cards"]) == 2
    assert all(card["image_source"] == "ai_illustration" for card in result["cards"])
    assert sorted(path.name for path in (tmp_path / "cards").glob("*.png")) == ["01.png", "02.png"]


@pytest.mark.parametrize("layout", ["实拍故事", "杂志留白", "知识图解", "清单便签", "纯图画册"])
def test_xiaohongshu_layout_variants_render(tmp_path: Path, layout: str):
    source = tmp_path / "source.png"
    Image.new("RGB", (1024, 1536), "#9DC7B5").save(source)
    cover = tmp_path / f"{layout}-cover.png"
    content = tmp_path / f"{layout}-content.png"
    render_card(source, {"headline": "封面标题", "body": "正文说明", "role": "cover", "layout": layout}, 1, 3, cover)
    render_card(source, {"headline": "正文标题", "body": "正文说明", "role": "content", "layout": layout}, 2, 3, content)
    assert Image.open(cover).size == CARD_SIZE
    assert Image.open(content).size == CARD_SIZE
