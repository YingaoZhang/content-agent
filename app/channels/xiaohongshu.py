"""Xiaohongshu 图文笔记 generation: model plan -> photo assignment -> card render -> note files."""

import json
import re
from pathlib import Path

from ..audiences import AUDIENCE_STRATEGIES
from ..config import settings
from ..forbidden_words import forbidden_words_rule, forbidden_words_warning
from ..harness import ContentModelHarness
from ..prompts import (
    XHS_AUDIENCE_VISUAL_DIRECTIONS,
    XHS_LAYOUTS,
    XHS_VISUAL_DIRECTIONS,
    XIAOHONGSHU_SYSTEM,
)
from ..schemas import Audience, ContentRequest, FactPolicy, Platform, XiaohongshuCard
from ..xiaohongshu_adapter import render_card, write_note_files


def xiaohongshu_constraints(request: ContentRequest) -> str:
    audience_strategy = AUDIENCE_STRATEGIES[request.primary_audience]
    fact_rule = (
        "所有事实、数据、认证、效果与案例都必须能在上传资料中找到依据，不得补充资料外信息。"
        if request.fact_policy == FactPolicy.MATERIALS_ONLY
        else "优先使用上传资料；可以补充不含具体数据、认证、效果或案例的通用常识，且必须明确、克制。"
    )
    forbidden_rule = forbidden_words_rule()
    length_rule = (
        f"发布文案长度：约 {request.caption_length} 个中文字符，可根据内容完整性上下浮动。"
        if request.caption_length else
        "发布文案长度：不设固定字数，以信息完整和平台阅读体验为准。"
    )
    return f"""小红书图文要求（已根据主要用户自动匹配）：
{length_rule}
笔记语气：{audience_strategy['tone']}。
内容结构：{audience_strategy['structure']}。
内容重点：{audience_strategy['focus']}。
事实依据：{fact_rule}
{forbidden_rule}"""


def _xiaohongshu_visual_direction(request: ContentRequest) -> str:
    direction = XHS_VISUAL_DIRECTIONS.get(request.theme, XHS_VISUAL_DIRECTIONS["真实产品摄影"])
    layout = XHS_LAYOUTS.get(request.xhs_layout, XHS_LAYOUTS["实拍故事"])
    audience_direction = XHS_AUDIENCE_VISUAL_DIRECTIONS.get(request.primary_audience, XHS_AUDIENCE_VISUAL_DIRECTIONS[Audience.BRAND_PM])
    return (
        f"Xiaohongshu vertical editorial note series, 3:4 portrait. {direction}. Layout system: {layout}. "
        f"Audience visual priority: {audience_direction} "
        "Keep the subject faithful to the supplied reference materials and ordinary real-world appearance; do not beautify into an unrelated fantasy scene. "
        "Use one immediately readable concrete subject per card. Favor documentary or product photography over conceptual art. Keep a coherent natural visual language across the series, while deliberately varying the setting, camera distance, angle, composition, and focal subject from card to card. "
        "No abstract biology, floating particles, split-screen comparisons, beauty retouching, generic wellness poses, text, logos, watermarks, user-interface elements, collage grids, generic futuristic blue glow, or invented branded packaging."
    )


def _normalize_xiaohongshu_card(raw_card: dict) -> dict:
    """Keep minor model verbosity from failing an otherwise usable card plan."""
    card = dict(raw_card)
    for field, limit in (("headline", 34), ("body", 160), ("visual_focus", 160)):
        if isinstance(card.get(field), str):
            card[field] = card[field].strip()[:limit]
    if card.get("role") not in {"cover", "content", "closing"}:
        card["role"] = "content"
    if card.get("image_source") not in {"uploaded_photo", "ai_illustration"}:
        card["image_source"] = "uploaded_photo"
    if not isinstance(card.get("source_photo_index"), int) or card["source_photo_index"] < 1:
        card["source_photo_index"] = None
    prompt = card.get("prompt") or card.get("image_prompt") or card.get("image_description")
    if isinstance(prompt, str) and prompt.strip():
        card["prompt"] = prompt.strip()
    elif card["image_source"] == "ai_illustration":
        focus = str(card.get("visual_focus") or card.get("headline") or "the note's key idea").strip()
        card["prompt"] = (
            f"Text-free AI-generated editorial image about {focus}; "
            "credible visual detail, polished composition, natural lighting, no logos, numbers, or text."
        )
    else:
        card["prompt"] = ""
    return card


def _normalize_xiaohongshu_hashtags(raw_tags: object, topic: str) -> list[str]:
    """Prefer short, commonly searchable topics over long generated phrases."""
    source = f"{topic} {' '.join(str(tag) for tag in (raw_tags if isinstance(raw_tags, list) else []))}"
    candidates = [re.sub(r"[^\w\u4e00-\u9fff]", "", str(tag).strip().lstrip("#")) for tag in (raw_tags if isinstance(raw_tags, list) else [])]
    tags: list[str] = []
    for tag in candidates:
        if 2 <= len(tag) <= 10 and tag not in tags:
            tags.append(tag)

    common = [
        ("麦角硫因", "#麦角硫因"), ("抗衰", "#抗衰老"), ("细胞", "#细胞健康"),
        ("成分", "#成分党"), ("原料", "#原料"), ("生物制造", "#生物科技"),
        ("配方", "#配方师"), ("护肤", "#护肤成分"), ("健康", "#健康科普"),
    ]
    for keyword, tag in common:
        if keyword in source and tag[1:] not in tags:
            tags.append(tag[1:])
    for fallback in ("小红书干货", "科普分享"):
        if len(tags) >= 5:
            break
        if fallback not in tags:
            tags.append(fallback)
    return [f"#{tag}" for tag in tags[:8]]


def generate_xiaohongshu_note(
    request: ContentRequest,
    material_text: str,
    job_dir: Path,
    harness: ContentModelHarness,
    reference_images: list[Path],
) -> dict:
    strategy = AUDIENCE_STRATEGIES[request.primary_audience]
    data = harness.json(
        XIAOHONGSHU_SYSTEM,
        f"需要 {request.image_count} 张 3:4 卡片。\n主题：{request.topic}\n内容目标：{request.objective}\n重点突出内容：{request.key_points or '由资料和主要用户策略自动提炼'}\n主要读者策略：{json.dumps(strategy, ensure_ascii=False)}\n结尾互动：{request.call_to_action}\n版式方案：{request.xhs_layout}（{XHS_LAYOUTS.get(request.xhs_layout, XHS_LAYOUTS['实拍故事'])}）\n可用实拍图（按 source_photo_index 编号）：{', '.join(f'{index}:{path.name}' for index, path in enumerate(reference_images, start=1)) or '未上传'}\n受众视觉要求：{XHS_AUDIENCE_VISUAL_DIRECTIONS.get(request.primary_audience, '')}\n{xiaohongshu_constraints(request)}\n视觉方向：{_xiaohongshu_visual_direction(request)}\n\n资料：\n{material_text}",
        "plan_xiaohongshu_note",
    )
    title = str(data.get("title") or request.topic).strip()[:40]
    caption = str(data.get("caption") or request.objective).strip()
    hashtags = _normalize_xiaohongshu_hashtags(data.get("hashtags"), f"{request.topic} {caption}")
    cards = [
        XiaohongshuCard.model_validate(_normalize_xiaohongshu_card(card)).model_dump()
        for card in data.get("cards", [])
    ]
    if len(cards) != request.image_count:
        raise RuntimeError(f"小红书卡片计划数量不正确：期望 {request.image_count}，实际 {len(cards)}")
    cards[0]["role"] = "cover"
    for card in cards[1:-1]:
        if card["role"] == "cover":
            card["role"] = "content"
    if len(cards) > 1 and cards[-1]["role"] == "cover":
        cards[-1]["role"] = "closing"

    prepared_cards: list[tuple[int, dict, Path]] = []
    sources_dir = job_dir / "images"
    sources_dir.mkdir(exist_ok=True)
    used_photo_indexes: set[int] = set()
    next_photo_index = 1

    # Resolve explicit photo assignments first, then use remaining uploaded photos
    # in order. Any cards left without a photo are generated by the image model.
    assignments: dict[int, int] = {}
    for index, card in enumerate(cards, start=1):
        requested_photo_index = card.get("source_photo_index")
        if (
            isinstance(requested_photo_index, int)
            and 1 <= requested_photo_index <= len(reference_images)
            and requested_photo_index not in used_photo_indexes
        ):
            assignments[index] = requested_photo_index
            used_photo_indexes.add(requested_photo_index)
    for index, card in enumerate(cards, start=1):
        if index in assignments:
            continue
        while next_photo_index <= len(reference_images) and next_photo_index in used_photo_indexes:
            next_photo_index += 1
        if next_photo_index <= len(reference_images):
            assignments[index] = next_photo_index
            used_photo_indexes.add(next_photo_index)
            next_photo_index += 1
    for index, card in enumerate(cards, start=1):
        if index in assignments:
            continue
        requested_photo_index = card.get("source_photo_index")
        if (
            isinstance(requested_photo_index, int)
            and 1 <= requested_photo_index <= len(reference_images)
            and requested_photo_index not in used_photo_indexes
        ):
            assignments[index] = requested_photo_index
            used_photo_indexes.add(requested_photo_index)
    for index, card in enumerate(cards, start=1):
        if index in assignments:
            continue
        while next_photo_index <= len(reference_images) and next_photo_index in used_photo_indexes:
            next_photo_index += 1
        if next_photo_index <= len(reference_images):
            assignments[index] = next_photo_index
            used_photo_indexes.add(next_photo_index)
            next_photo_index += 1

    for index, card in enumerate(cards, start=1):
        photo_index = assignments.get(index)

        if photo_index is not None:
            card["image_source"] = "uploaded_photo"
            card["source_photo_index"] = photo_index
            prepared_cards.append((index, card, reference_images[photo_index - 1]))
            continue

        card["image_source"] = "ai_illustration"
        card["source_photo_index"] = None
        source_path = sources_dir / f"xhs-ai-source-{index:02d}.png"
        harness.enable_image_generation()
        if not str(card.get("prompt") or "").strip():
            focus = str(card.get("visual_focus") or card.get("headline") or "the note's key idea").strip()
            card["prompt"] = (
                f"Text-free AI-generated editorial image about {focus}; "
                "credible visual detail, polished composition, natural lighting, no logos, numbers, or text."
            )
        prompt = (
            f"{card['prompt']}\n\nArt direction: {_xiaohongshu_visual_direction(request)}\n"
            "This is an AI-generated visual. It may use realistic photography or editorial illustration, but must not include text, numbers, logos, watermarks, or UI. Do not imply that it is an uploaded documentary photograph."
        )
        harness.image(
            prompt,
            source_path,
            size=getattr(settings, "xhs_card_size", "1024x1536"),
            quality=getattr(settings, "image_quality", "high"),
        )
        if not source_path.is_file() or source_path.stat().st_size == 0:
            raise RuntimeError(
                f"第 {index} 张 AI 图片未成功写入：{source_path.name}。请检查图片 API 返回内容和存储目录权限。"
            )
        prepared_cards.append((index, card, source_path))

    rendered_cards = []
    for index, card, source_path in prepared_cards:
        card["filename"] = f"{index:02d}.png"
        card["source_filename"] = source_path.name
        card["layout"] = request.xhs_layout
        render_card(source_path, card, index, len(cards), job_dir / "cards" / card["filename"])
        rendered_cards.append(card)

    preview_path = write_note_files(job_dir, title, caption, hashtags, rendered_cards, job_dir.name)
    warnings = []
    if warning := forbidden_words_warning(
        title,
        caption,
        *(card.get("headline", "") or "" for card in rendered_cards),
        *(card.get("body", "") or "" for card in rendered_cards),
        *(card.get("visual_focus", "") or "" for card in rendered_cards),
    ):
        warnings.append(warning)
    return {"title": title, "cards": rendered_cards, "preview_path": str(preview_path), "warnings": warnings}


class XiaohongshuChannel:
    platform = Platform.XIAOHONGSHU

    def generate(
        self,
        request: ContentRequest,
        material_text: str,
        job_dir: Path,
        harness: ContentModelHarness,
        reference_images: list[Path],
    ) -> dict:
        return generate_xiaohongshu_note(request, material_text, job_dir, harness, reference_images)
