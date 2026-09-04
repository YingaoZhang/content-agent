import json
import re
from concurrent.futures import ThreadPoolExecutor
import uuid
from pathlib import Path
from typing import TypedDict

from .config import settings

from langgraph.graph import END, START, StateGraph

from .audiences import AUDIENCE_STRATEGIES
from .gzh_adapter import render_wechat_html
from .harness import ContentModelHarness
from .schemas import ContentRequest, FactPolicy, ImagePlanItem, Platform, XiaohongshuCard
from .xiaohongshu_adapter import render_card, write_note_files


class WorkflowState(TypedDict, total=False):
    request: ContentRequest
    material_text: str
    job_dir: str
    harness: ContentModelHarness
    brief: dict
    outline: str
    article: str
    feedback: str
    image_plan: list[dict]
    article_with_images: str
    html_path: str
    preview_path: str
    warnings: list[str]


OUTLINE_SYSTEM = """你是一位资深中文内容主编。请根据用户资料和写作要求，先给出一份可供确认的微信公众号文章大纲。
只输出 Markdown 大纲，不写完整正文，不使用代码围栏。大纲必须包含一个 # 标题、300 至 500 字开篇的内容要点、4 至 6 个 ## 章节及每章 2 至 4 个具体要点，以及结语与行动号召。每个要点应说明将使用资料中的哪类事实或观点，避免空泛标题。"""

WRITING_SYSTEM = """你是一位资深中文内容主编。请严格根据已确认的大纲和用户提供的资料写作。
写一篇可直接用于微信公众号的完整 Markdown 长文。
必须包含：一个有张力的 # 标题；300 至 500 字的开篇引入和引用金句；4 至 6 个 ## 章节；每章至少 2 个自然段、每段 120 至 260 字；必要时使用 ### 小节；300 至 500 字的结语与行动号召。
先充分展开资料中的背景、问题、方法、产品/能力、应用场景和下一步行动，再收束文章。避免机械的“首先/其次/最后”，不声称资料没有支持的事实，不用空洞重复来凑字数。"""

REVISION_SYSTEM = """你是一位资深中文内容主编。根据用户的修改意见修订一篇微信公众号 Markdown 文章。
完整输出修改后的文章，不要说明修改过程，不要输出 Markdown 代码围栏。保留文章的 # 标题与清晰章节结构；没有被要求修改的内容尽量保持原意。"""

XIAOHONGSHU_SYSTEM = """你是中文小红书图文笔记策划。严格根据上传资料，生成一组可发布的图文笔记。
只输出合法 JSON，不要 Markdown 代码围栏，格式为：
{"title":"不超过20个中文字符的标题","caption":"按指定字数生成的发布文案，分成3到6个短段，首句有具体钩子，结尾有自然互动提问","hashtags":["#标签"],"cards":[{"filename":"01.png","headline":"卡片标题","body":"卡片正文，1到4句短句","visual_focus":"这张图的独立信息点","prompt":"English prompt for a text-free vertical editorial image"}]}。
必须严格返回指定数量的 cards。第一张是封面，负责提出问题或给出结论；中间卡片每张只解释一个要点；最后一张给出可执行总结或互动。headline 不超过 34 个字符，body 和 visual_focus 各不超过 160 个字符。hashtags 请提供 5 到 8 个小红书常见、可搜索的短话题，优先 2 到 8 个字，避免公司名、地点、认证名和过长的组合词；系统会再次过滤。卡片中文字将由程序排版，所以 prompt 中严禁生成任何文字、数字、Logo、水印、UI 面板或拼贴网格。不要把公众号长文缩短，不得编造资料中没有的数据、认证、效果或案例。"""


THEME_VISUAL_DIRECTIONS = {
    "石墨极简风": "premium graphite-and-white editorial art direction, restrained contrast, generous negative space, precise magazine photography or clean data illustration",
    "摸鱼绿": "fresh moss-green editorial art direction, natural tactile materials, calm daylight, approachable expert publication",
    "红白色系": "confident red-and-white editorial art direction, bold but restrained composition, sharp contrast, contemporary feature-story photography",
    "留白禅意风": "quiet minimalist editorial art direction, warm white space, soft natural light, contemplative composition",
    "摸鱼票据风": "clever modern editorial art direction with structured paper, labels, and tactile desk elements, never a literal receipt screenshot",
    "橄榄手记": "warm olive journal editorial art direction, documentary detail, understated grain, thoughtful long-form publication",
}

XHS_VISUAL_DIRECTIONS = {
    "真实产品摄影": "realistic product photography, accurate material texture, natural proportions, soft daylight, clean uncluttered background",
    "清透实验室": "bright clean laboratory photography, authentic glassware and material details, neutral daylight, restrained scientific mood",
    "生活方式记录": "natural lifestyle documentary photography, believable everyday setting, candid composition, warm daylight, close to real use context",
    "自然原料质感": "close-up natural material photography, tactile surface details, earthy neutral palette, soft window light, editorial but believable",
    "极简杂志感": "minimal contemporary editorial photography, one concrete subject, precise composition, quiet neutral palette, soft directional light",
}


def _image_visual_direction(request: ContentRequest) -> str:
    theme_direction = THEME_VISUAL_DIRECTIONS.get(request.theme, THEME_VISUAL_DIRECTIONS["石墨极简风"])
    brand_context = f"Brand context: {request.brand_name}." if request.brand_name else "No visible brand mark or invented product packaging."
    return (
        f"WeChat long-form editorial image series. {theme_direction}. {brand_context} "
        "Mobile-first readability, one clear visual idea per image, consistent palette and lighting across the whole series. "
        "No embedded text, logos, watermarks, UI panels, collage grids, generic blue sci-fi glow, or unrelated decorative objects."
    )


def _image_prompt(item: dict, visual_direction: str) -> str:
    role_instruction = (
        "This is the article cover: create one strong subject with clean negative space in the upper third and on one side for the WeChat title overlay; "
        "do not render that title in the image."
        if item["placement"] == "cover"
        else "This is an in-article visual: explain the named section with one concrete scene, object, process, or data relationship; keep the focal subject immediately legible on a mobile screen."
    )
    return f"{item['prompt'].strip()}\n\nArt direction: {visual_direction}\n{role_instruction}"


def writing_constraints(request: ContentRequest) -> str:
    fact_rule = (
        "所有事实、数据、认证、效果与案例都必须能在上传资料中找到依据，不得补充资料外信息。"
        if request.fact_policy == FactPolicy.MATERIALS_ONLY
        else "优先使用上传资料；可以补充不含具体数据、认证、效果或案例的通用常识，且必须明确、克制。"
    )
    forbidden_rule = f"禁止使用这些词或近似宣传表述：{request.forbidden_words}。" if request.forbidden_words else "没有额外禁用词。"
    return f"""写作质量要求：
目标长度：约 {request.target_length} 个中文字符。
语气：{request.tone}。
文章结构：{request.structure}。
事实依据：{fact_rule}
{forbidden_rule}"""


def xiaohongshu_constraints(request: ContentRequest) -> str:
    fact_rule = (
        "所有事实、数据、认证、效果与案例都必须能在上传资料中找到依据，不得补充资料外信息。"
        if request.fact_policy == FactPolicy.MATERIALS_ONLY
        else "优先使用上传资料；可以补充不含具体数据、认证、效果或案例的通用常识，且必须明确、克制。"
    )
    forbidden_rule = f"禁止使用这些词或近似宣传表述：{request.forbidden_words}。" if request.forbidden_words else "没有额外禁用词。"
    return f"""小红书图文要求：
发布文案长度：约 {request.caption_length} 个中文字符。
笔记语气：{request.tone}。
事实依据：{fact_rule}
{forbidden_rule}"""


def validate_project(state: WorkflowState) -> WorkflowState:
    request = state["request"]
    if request.primary_audience not in AUDIENCE_STRATEGIES:
        raise ValueError("必须选择且仅选择一类主要用户")
    if not state["material_text"].strip():
        raise ValueError("至少需要一份可提取文本的资料")
    return {}


def build_brief(state: WorkflowState) -> WorkflowState:
    request = state["request"]
    strategy = AUDIENCE_STRATEGIES[request.primary_audience]
    return {"brief": {"topic": request.topic, "objective": request.objective, "cta": request.call_to_action, "brand": request.brand_name, "strategy": strategy}}


def generate_outline(state: WorkflowState) -> WorkflowState:
    request = state["request"]
    brief = state["brief"]
    outline = state["harness"].text(
        OUTLINE_SYSTEM,
        f"""内容主题：{request.topic}
内容目标：{request.objective}
品牌：{request.brand_name or '未提供'}
主要用户策略：{json.dumps(brief['strategy'], ensure_ascii=False)}
行动号召：{request.call_to_action}
{writing_constraints(request)}

资料：
{state['material_text']}""",
        "plan_article_outline",
    )
    if not outline.startswith("#"):
        outline = f"# {request.topic}\n\n{outline}"
    return {"outline": outline}


def generate_article(state: WorkflowState) -> WorkflowState:
    request = state["request"]
    brief = state["brief"]
    user = f"""内容主题：{request.topic}
内容目标：{request.objective}
品牌：{request.brand_name or '未提供'}
主要用户策略：{json.dumps(brief['strategy'], ensure_ascii=False)}
行动号召：{request.call_to_action}
作者署名：{request.author_name}
作者简介：{request.author_bio}
{writing_constraints(request)}

已确认文章大纲：
{state.get('outline', '未提供额外大纲，请按主要用户策略组织文章。')}

资料：
{state['material_text']}
"""
    article = state["harness"].text(WRITING_SYSTEM, user, "generate_master_content")
    if not article.startswith("#"):
        article = f"# {request.topic}\n\n{article}"
    minimum_length = min(settings.article_min_chars, max(1000, int(request.target_length * 0.7)))
    if len(article) < minimum_length:
        expand_system = """你是微信公众号资深编辑。请在不改变原文事实、不新增资料外信息的前提下，把文章扩写到目标长度。
保留原有标题和章节，补充资料中已有的背景、机制、场景、细节、段落过渡和读者行动建议；不要重复句子，不要添加来源中没有的数字或承诺。
只输出完整 Markdown 文章。"""
        article = state["harness"].text(expand_system, f"{writing_constraints(request)}\n最低长度：{minimum_length} 字符\n\n原文：\n{article}\n\n资料：\n{state['material_text']}", "expand_master_content")
        if not article.startswith("#"):
            article = f"# {request.topic}\n\n{article}"
    return {"article": article}


def revise_article(state: WorkflowState) -> WorkflowState:
    article = state["harness"].text(
        REVISION_SYSTEM,
        f"""用户修改意见：
{state['feedback']}
{writing_constraints(state['request'])}

原文章：
{state['article']}

可依据的资料：
{state['material_text']}""",
        "revise_master_content",
    )
    if not article.startswith("#"):
        title = re.search(r"^#\s+(.+?)\s*$", state["article"], re.M)
        article = f"# {title.group(1) if title else state['request'].topic}\n\n{article}"
    return {"article": article}


def generate_image_plan(state: WorkflowState) -> WorkflowState:
    request = state["request"]
    if request.image_count == 0:
        return {"image_plan": []}

    headings = re.findall(r"^##\s+(.+?)\s*$", state["article"], re.M)
    visual_direction = _image_visual_direction(request)
    system = """你是微信公众号视觉总监。根据文章真实内容规划配图，严格只输出 JSON：{\"images\":[{\"filename\":\"cover.png\",\"placement\":\"cover\",\"alt\":\"中文图片说明\",\"insert_after_heading\":\"\",\"visual_focus\":\"本图要证明/表达的具体内容\",\"prompt\":\"English image prompt describing only the concrete visual subject, scene, composition, and light\"}]}。
必须恰好返回指定数量的图片，第一张 placement 必须是 cover，其余全部是 body。
每张 body 图的 insert_after_heading 必须从给定章节标题中原样选择；visual_focus 必须对应该章节的具体信息，禁止泛泛写“科技感”“抽象分子”。英文 Prompt 必须明确主体、场景、构图、光线和与章节内容的视觉关系，不要生成长文本、Logo、品牌名或资料中没有的产品属性。
每张图只表达一个核心观点，必须能被手机端读者在一眼内理解。系列图片要保持同一种光线、色彩和编辑风格；封面应有一个明确主体和可留白区域，正文图应服务对应章节，而不是重复封面。"""
    data = state["harness"].json(
        system,
        f"需要恰好 {request.image_count} 张图片。\n"
        f"公众号主题：{request.theme}\n品牌：{request.brand_name or '未提供'}\n主要读者：{request.primary_audience.value}\n"
        f"全篇视觉方向（必须遵守）：{visual_direction}\n"
        f"可绑定的章节标题：{json.dumps(headings, ensure_ascii=False)}\n\n文章：\n{state['article']}",
        "plan_images",
    )
    items = [ImagePlanItem.model_validate(item).model_dump() for item in data.get("images", [])]
    if len(items) != request.image_count:
        raise RuntimeError(f"图片计划数量不正确：期望 {request.image_count}，实际 {len(items)}")
    items[0]["filename"] = "cover.png"
    items[0]["placement"] = "cover"
    for item_index, item in enumerate(items[1:], start=1):
        item["placement"] = "body"
        if item["insert_after_heading"] not in headings:
            item["insert_after_heading"] = headings[min(item_index - 1, len(headings) - 1)] if headings else ""
    cover_size = getattr(settings, "image_cover_size", "1536x1024")
    body_size = getattr(settings, "image_body_size", "1024x1024")
    quality = getattr(settings, "image_quality", "high")
    for item in items:
        item["size"] = cover_size if item["placement"] == "cover" else body_size
        item["quality"] = quality
        item["prompt"] = _image_prompt(item, visual_direction)
    return {"image_plan": items}


def generate_images(state: WorkflowState) -> WorkflowState:
    job_dir = Path(state["job_dir"])
    if not state["image_plan"]:
        (job_dir / "image_plan.json").write_text("[]\n", encoding="utf-8")
        (job_dir / "article.md").write_text(state["article"], encoding="utf-8")
        (job_dir / "article_with_images.md").write_text(state["article"], encoding="utf-8")
        return {"image_plan": [], "article_with_images": state["article"]}

    images_dir = job_dir / "images"
    images_dir.mkdir(exist_ok=True)
    prepared: list[tuple[dict, str, Path]] = []
    for index, item in enumerate(state["image_plan"]):
        filename = re.sub(r"[^a-zA-Z0-9_.-]", "-", item["filename"] or f"image-{index + 1}.png")
        if not filename.endswith(".png"):
            filename += ".png"
        prepared.append((item, filename, images_dir / filename))

    def render_one(entry: tuple[dict, str, Path]) -> None:
        item, _filename, target = entry
        state["harness"].image(
            item["prompt"],
            target,
            size=item.get("size") or getattr(settings, "image_body_size", "1024x1024"),
            quality=item.get("quality") or getattr(settings, "image_quality", "high"),
        )

    # Submit a few async tasks concurrently; keep output order stable below.
    max_workers = max(1, min(getattr(settings, "image_max_concurrency", 2), len(prepared)))
    with ThreadPoolExecutor(max_workers=max_workers) as executor:
        list(executor.map(render_one, prepared))

    items = []
    for item, filename, _target in prepared:
        item["filename"] = filename
        items.append(item)

    image_lines = {item["filename"]: f"![{item['alt']}](/assets/jobs/{job_dir.name}/images/{item['filename']})" for item in items}
    markdown = state["article"]
    cover_line = image_lines["cover.png"]
    markdown = markdown.replace("\n\n", "\n\n" + cover_line + "\n\n", 1)
    for item in items[1:]:
        image_line = image_lines[item["filename"]]
        heading = item.get("insert_after_heading", "")
        marker = f"## {heading}" if heading else ""
        if marker and marker in markdown:
            next_heading = re.search(r"\n##\s+", markdown[markdown.index(marker) + len(marker):])
            start = markdown.index(marker) + len(marker)
            end = start + next_heading.start() if next_heading else len(markdown)
            section = markdown[start:end].rstrip()
            markdown = markdown[:start] + section + "\n\n" + image_line + markdown[end:]
        else:
            markdown += "\n\n" + image_line
    (job_dir / "image_plan.json").write_text(json.dumps(items, ensure_ascii=False, indent=2), encoding="utf-8")
    (job_dir / "article.md").write_text(state["article"], encoding="utf-8")
    (job_dir / "article_with_images.md").write_text(markdown, encoding="utf-8")
    return {"image_plan": items, "article_with_images": markdown}


def layout_article(state: WorkflowState) -> WorkflowState:
    html, preview, warnings = render_wechat_html(state["harness"].text_api, state["article_with_images"], state["request"].theme, Path(state["job_dir"]))
    return {"html_path": str(html), "preview_path": str(preview), "warnings": warnings}


def _xiaohongshu_visual_direction(request: ContentRequest) -> str:
    direction = XHS_VISUAL_DIRECTIONS.get(request.theme, XHS_VISUAL_DIRECTIONS["真实产品摄影"])
    return (
        f"Xiaohongshu vertical editorial note series, 3:4 portrait. {direction}. "
        "Keep the subject faithful to the supplied reference materials and ordinary real-world appearance; do not beautify into an unrelated fantasy scene. "
        "One immediately readable subject per card, consistent natural light and palette across the series, enough clean space for locally rendered Chinese copy. "
        "No text, logos, watermarks, user-interface elements, collage grids, generic futuristic blue glow, or invented branded packaging."
    )


def _normalize_xiaohongshu_card(raw_card: dict) -> dict:
    """Keep minor model verbosity from failing an otherwise usable card plan."""
    card = dict(raw_card)
    for field, limit in (("headline", 34), ("body", 160), ("visual_focus", 160)):
        if isinstance(card.get(field), str):
            card[field] = card[field].strip()[:limit]
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


def generate_xiaohongshu_note(request: ContentRequest, material_text: str, job_dir: Path, harness: ContentModelHarness) -> dict:
    strategy = AUDIENCE_STRATEGIES[request.primary_audience]
    data = harness.json(
        XIAOHONGSHU_SYSTEM,
        f"需要 {request.image_count} 张 3:4 卡片。\n主题：{request.topic}\n内容目标：{request.objective}\n品牌：{request.brand_name or '未提供'}\n主要读者策略：{json.dumps(strategy, ensure_ascii=False)}\n结尾互动：{request.call_to_action}\n{xiaohongshu_constraints(request)}\n视觉方向：{_xiaohongshu_visual_direction(request)}\n\n资料：\n{material_text}",
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

    sources_dir = job_dir / "images"
    sources_dir.mkdir(exist_ok=True)
    prepared_cards: list[tuple[int, dict, str, Path]] = []
    for index, card in enumerate(cards, start=1):
        source_name = f"xhs-source-{index:02d}.png"
        source_path = sources_dir / source_name
        prompt = f"{card['prompt'].strip()}\n\nArt direction: {_xiaohongshu_visual_direction(request)}"
        prepared_cards.append((index, card, prompt, source_path))

    def render_source(entry: tuple[int, dict, str, Path]) -> None:
        _index, _card, prompt, source_path = entry
        harness.image(
            prompt,
            source_path,
            size=getattr(settings, "xhs_card_size", "1024x1536"),
            quality=getattr(settings, "image_quality", "high"),
        )

    max_workers = max(1, min(getattr(settings, "image_max_concurrency", 2), len(prepared_cards)))
    with ThreadPoolExecutor(max_workers=max_workers) as executor:
        list(executor.map(render_source, prepared_cards))

    rendered_cards = []
    for index, card, _prompt, source_path in prepared_cards:
        card["filename"] = f"{index:02d}.png"
        card["source_filename"] = source_name
        render_card(source_path, card, index, len(cards), request.brand_name, job_dir / "cards" / card["filename"])
        rendered_cards.append(card)

    preview_path = write_note_files(job_dir, title, caption, hashtags, rendered_cards, job_dir.name)
    return {"title": title, "cards": rendered_cards, "preview_path": str(preview_path), "warnings": []}


def build_graph():
    graph = StateGraph(WorkflowState)
    graph.add_node("validate_project", validate_project)
    graph.add_node("build_brief", build_brief)
    graph.add_node("generate_article", generate_article)
    graph.add_node("generate_image_plan", generate_image_plan)
    graph.add_node("generate_images", generate_images)
    graph.add_node("layout_article", layout_article)
    graph.add_edge(START, "validate_project")
    graph.add_edge("validate_project", "build_brief")
    graph.add_edge("build_brief", "generate_article")
    graph.add_edge("generate_article", "generate_image_plan")
    graph.add_edge("generate_image_plan", "generate_images")
    graph.add_edge("generate_images", "layout_article")
    graph.add_edge("layout_article", END)
    return graph.compile()


def build_revision_graph():
    graph = StateGraph(WorkflowState)
    graph.add_node("validate_project", validate_project)
    graph.add_node("revise_article", revise_article)
    graph.add_node("generate_image_plan", generate_image_plan)
    graph.add_node("generate_images", generate_images)
    graph.add_node("layout_article", layout_article)
    graph.add_edge(START, "validate_project")
    graph.add_edge("validate_project", "revise_article")
    graph.add_edge("revise_article", "generate_image_plan")
    graph.add_edge("generate_image_plan", "generate_images")
    graph.add_edge("generate_images", "layout_article")
    graph.add_edge("layout_article", END)
    return graph.compile()


def _create_job_dir() -> tuple[str, Path]:
    job_id = uuid.uuid4().hex[:12]
    job_dir = settings.storage_dir / "jobs" / job_id
    job_dir.mkdir(parents=True, exist_ok=False)
    return job_id, job_dir


def _write_run_metadata(
    job_dir: Path,
    request: ContentRequest,
    harness: ContentModelHarness,
    parent_job_id: str | None = None,
    stage: str = "completed",
) -> None:
    metadata = {
        "request": request.model_dump(mode="json"),
        "text_api": {"base_url": settings.text_base_url, "model": settings.text_model},
        "image_api": {"base_url": settings.image_base_url, "model": settings.image_model},
        "trace": harness.trace,
        "stage": stage,
    }
    if parent_job_id:
        metadata["parent_job_id"] = parent_job_id
    (job_dir / "run.json").write_text(json.dumps(metadata, ensure_ascii=False, indent=2), encoding="utf-8")


def run_generation(request: ContentRequest, material_text: str) -> dict:
    job_id, job_dir = _create_job_dir()
    (job_dir / "source_material.md").write_text(material_text, encoding="utf-8")
    harness = ContentModelHarness(enable_image_generation=request.image_count > 0)
    if request.platform == Platform.XIAOHONGSHU:
        validate_project({"request": request, "material_text": material_text})
        final = generate_xiaohongshu_note(request, material_text, job_dir, harness)
    else:
        final = build_graph().invoke({"request": request, "material_text": material_text, "job_dir": str(job_dir), "harness": harness})
    _write_run_metadata(job_dir, request, harness)
    return {"job_id": job_id, "image_plan": final.get("image_plan", final.get("cards", [])), "warnings": final.get("warnings", [])}


def run_outline_generation(request: ContentRequest, material_text: str) -> dict:
    job_id, job_dir = _create_job_dir()
    (job_dir / "source_material.md").write_text(material_text, encoding="utf-8")
    harness = ContentModelHarness(enable_image_generation=False)
    state: WorkflowState = {"request": request, "material_text": material_text, "job_dir": str(job_dir), "harness": harness}
    validate_project(state)
    state.update(build_brief(state))
    state.update(generate_outline(state))
    (job_dir / "outline.md").write_text(state["outline"], encoding="utf-8")
    _write_run_metadata(job_dir, request, harness, stage="outline_ready")
    return {"job_id": job_id, "outline": state["outline"]}


def run_generation_from_outline(job_id: str, outline: str) -> dict:
    if not re.fullmatch(r"[a-f0-9]{12}", job_id):
        raise FileNotFoundError(job_id)
    outline = outline.strip()
    if len(outline) < 20:
        raise ValueError("请保留至少一条有实际内容的大纲要点")
    if len(outline) > 12000:
        raise ValueError("大纲过长，请控制在 12000 个字符以内")

    job_dir = settings.storage_dir / "jobs" / job_id
    source_path = job_dir / "source_material.md"
    metadata_path = job_dir / "run.json"
    if not source_path.exists() or not metadata_path.exists():
        raise RuntimeError("未找到待确认大纲的原始资料或任务记录")
    if (job_dir / "article.md").exists():
        raise ValueError("该大纲已经生成过成品；请在成品下方继续修改文章")

    metadata = json.loads(metadata_path.read_text(encoding="utf-8"))
    request = ContentRequest.model_validate(metadata["request"])
    material_text = source_path.read_text(encoding="utf-8")
    (job_dir / "outline.md").write_text(outline, encoding="utf-8")
    harness = ContentModelHarness(enable_image_generation=request.image_count > 0)
    final = build_graph().invoke(
        {"request": request, "material_text": material_text, "job_dir": str(job_dir), "harness": harness, "outline": outline}
    )
    _write_run_metadata(job_dir, request, harness)
    return {"job_id": job_id, "image_plan": final["image_plan"], "warnings": final.get("warnings", [])}


def run_revision(parent_job_id: str, feedback: str) -> dict:
    feedback = feedback.strip()
    if not feedback:
        raise ValueError("请说明希望如何修改当前成品")

    parent_dir = settings.storage_dir / "jobs" / parent_job_id
    source_path = parent_dir / "source_material.md"
    article_path = parent_dir / "article.md"
    metadata_path = parent_dir / "run.json"
    if not source_path.exists() or not article_path.exists() or not metadata_path.exists():
        raise RuntimeError("未找到当前成品的原始资料或版本记录，无法继续修改")

    metadata = json.loads(metadata_path.read_text(encoding="utf-8"))
    request = ContentRequest.model_validate(metadata["request"])
    material_text = source_path.read_text(encoding="utf-8")
    article = article_path.read_text(encoding="utf-8")
    job_id, job_dir = _create_job_dir()
    (job_dir / "source_material.md").write_text(material_text, encoding="utf-8")
    harness = ContentModelHarness(enable_image_generation=request.image_count > 0)
    final = build_revision_graph().invoke(
        {
            "request": request,
            "material_text": material_text,
            "article": article,
            "feedback": feedback,
            "job_dir": str(job_dir),
            "harness": harness,
        }
    )
    _write_run_metadata(job_dir, request, harness, parent_job_id=parent_job_id)
    return {"job_id": job_id, "image_plan": final["image_plan"], "warnings": final.get("warnings", [])}
