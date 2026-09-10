import json
import re
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from typing import TypedDict

from .config import settings

from langgraph.graph import END, START, StateGraph

from .audiences import AUDIENCE_STRATEGIES
from .forbidden_words import forbidden_words_rule
from .gzh_adapter import render_wechat_html
from .harness import ContentModelHarness
from .prompts import (
    OUTLINES_SYSTEM,
    REVISION_SYSTEM,
    THEME_VISUAL_DIRECTIONS,
    TITLES_SYSTEM,
    WRITING_SYSTEM,
)
from .schemas import ContentRequest, FactPolicy, ImagePlanItem


class WorkflowState(TypedDict, total=False):
    request: ContentRequest
    material_text: str
    job_dir: str
    harness: ContentModelHarness
    brief: dict
    title: str
    titles: list[str]
    outlines: list[str]
    outline: str
    article: str
    feedback: str
    image_plan: list[dict]
    article_with_images: str
    html_path: str
    preview_path: str
    warnings: list[str]


def _image_visual_direction(request: ContentRequest) -> str:
    theme_direction = THEME_VISUAL_DIRECTIONS.get(request.theme, THEME_VISUAL_DIRECTIONS["石墨极简风"])
    focus_context = f"Content priorities: {request.key_points}." if request.key_points else "Content priorities should follow the source material."
    return (
        f"WeChat long-form editorial image series. {theme_direction}. {focus_context} "
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
    audience_strategy = AUDIENCE_STRATEGIES[request.primary_audience]
    fact_rule = (
        "所有事实、数据、认证、效果与案例都必须能在上传资料中找到依据，不得补充资料外信息。"
        if request.fact_policy == FactPolicy.MATERIALS_ONLY
        else "优先使用上传资料；可以补充不含具体数据、认证、效果或案例的通用常识，且必须明确、克制。"
    )
    forbidden_rule = forbidden_words_rule()
    length_rule = (
        f"目标长度：约 {request.target_length} 个中文字符，可根据内容完整性上下浮动。"
        if request.target_length else
        "目标长度：不设固定字数，以内容完整、事实准确和渠道阅读体验为准。"
    )
    return f"""写作质量要求（已根据主要用户自动匹配）：
{length_rule}
语气：{audience_strategy['tone']}。
文章结构：{audience_strategy['structure']}。
内容重点：{audience_strategy['focus']}。
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
    return {"brief": {"topic": request.topic, "objective": request.objective, "key_points": request.key_points, "cta": request.call_to_action, "strategy": strategy}}


def generate_titles(state: WorkflowState) -> list[str]:
    """Generate 5 distinct candidate titles from the material and brief."""
    request = state["request"]
    brief = state["brief"]
    data = state["harness"].json(
        TITLES_SYSTEM,
        f"""内容主题：{request.topic}
内容目标：{request.objective}
重点突出内容：{request.key_points or '由资料和主要用户策略自动提炼'}
主要用户策略：{json.dumps(brief['strategy'], ensure_ascii=False)}
行动号召：{request.call_to_action}
{writing_constraints(request)}

资料：
{state['material_text']}""",
        "plan_article_titles",
    )
    titles = [str(title).strip() for title in data.get("titles", []) if str(title).strip()]
    if len(titles) != 5:
        raise RuntimeError(f"候选标题数量不正确：期望 5 个，实际 {len(titles)} 个")
    return titles


def generate_candidate_outlines(state: WorkflowState) -> list[str]:
    """Generate 2 distinguishable candidate outlines for the selected title."""
    request = state["request"]
    brief = state["brief"]
    title = state.get("title") or request.topic
    data = state["harness"].json(
        OUTLINES_SYSTEM,
        f"""已选标题：{title}
内容主题：{request.topic}
内容目标：{request.objective}
重点突出内容：{request.key_points or '由资料和主要用户策略自动提炼'}
主要用户策略：{json.dumps(brief['strategy'], ensure_ascii=False)}
行动号召：{request.call_to_action}
{writing_constraints(request)}

资料：
{state['material_text']}""",
        "plan_article_outlines",
    )
    outlines = [str(outline).strip() for outline in data.get("outlines", []) if str(outline).strip()]
    if len(outlines) != 2:
        raise RuntimeError(f"候选大纲数量不正确：期望 2 份，实际 {len(outlines)} 份")
    for index, outline in enumerate(outlines):
        if not outline.startswith("#"):
            outlines[index] = f"# {title}\n\n{outline}"
    return outlines


def generate_article(state: WorkflowState) -> WorkflowState:
    request = state["request"]
    brief = state["brief"]
    title = state.get("title") or request.topic
    user = f"""内容主题：{request.topic}
内容目标：{request.objective}
重点突出内容：{request.key_points or '由资料和主要用户策略自动提炼'}
主要用户策略：{json.dumps(brief['strategy'], ensure_ascii=False)}
行动号召：{request.call_to_action}
作者署名：{request.author_name}
作者简介：{request.author_bio}
{writing_constraints(request)}

已选定标题（文章 # 标题必须使用它）：
{title}

已确认文章大纲：
{state.get('outline', '未提供额外大纲，请按主要用户策略组织文章。')}

资料：
{state['material_text']}
"""
    article = state["harness"].text(WRITING_SYSTEM, user, "generate_master_content")
    if not article.startswith("#"):
        article = f"# {title}\n\n{article}"
    minimum_length = (
        min(settings.article_min_chars, max(1000, int(request.target_length * 0.7)))
        if request.target_length else 0
    )
    if len(article) < minimum_length:
        expand_system = """你是微信公众号资深编辑。请在不改变原文事实、不新增资料外信息的前提下，把文章扩写到目标长度。
保留原有标题和章节，补充资料中已有的背景、机制、场景、细节、段落过渡和读者行动建议；不要重复句子，不要添加来源中没有的数字或承诺。
只输出完整 Markdown 文章。"""
        article = state["harness"].text(expand_system, f"{writing_constraints(request)}\n最低长度：{minimum_length} 字符\n\n原文：\n{article}\n\n资料：\n{state['material_text']}", "expand_master_content")
        if not article.startswith("#"):
            article = f"# {title}\n\n{article}"
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


def _normalize_image_plan_item(raw_item: object, index: int) -> dict:
    """Fill optional fields that image planners occasionally omit."""
    item = dict(raw_item) if isinstance(raw_item, dict) else {}
    visual_focus = str(item.get("visual_focus") or "文章核心信息").strip()
    prompt = str(item.get("prompt") or item.get("image_prompt") or "").strip()
    if not prompt:
        prompt = (
            f"A clear editorial image illustrating {visual_focus}; concrete subject, "
            "balanced composition, natural light, no text, logos, or watermarks."
        )
    return {
        **item,
        "filename": str(item.get("filename") or f"image-{index + 1}.png").strip(),
        "placement": str(item.get("placement") or ("cover" if index == 0 else "body")).strip(),
        "alt": str(item.get("alt") or visual_focus or "文章配图").strip(),
        "prompt": prompt,
        "insert_after_heading": str(item.get("insert_after_heading") or "").strip(),
        "visual_focus": visual_focus,
    }


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
        f"公众号主题：{request.theme}\n重点突出内容：{request.key_points or '由文章内容自动提炼'}\n主要读者：{request.primary_audience.value}\n"
        f"全篇视觉方向（必须遵守）：{visual_direction}\n"
        f"可绑定的章节标题：{json.dumps(headings, ensure_ascii=False)}\n\n文章：\n{state['article']}",
        "plan_images",
    )
    raw_items = data.get("images", [])
    if not isinstance(raw_items, list):
        raise RuntimeError("图片计划格式不正确：images 必须是数组")
    items = [
        ImagePlanItem.model_validate(_normalize_image_plan_item(item, index)).model_dump()
        for index, item in enumerate(raw_items)
    ]
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
