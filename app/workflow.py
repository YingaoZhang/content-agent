import json
import re
import uuid
from pathlib import Path
from typing import TypedDict

from .config import settings

from langgraph.graph import END, START, StateGraph

from .audiences import AUDIENCE_STRATEGIES
from .gzh_adapter import render_wechat_html
from .harness import ContentModelHarness
from .schemas import ContentRequest, ImagePlanItem


class WorkflowState(TypedDict, total=False):
    request: ContentRequest
    material_text: str
    job_dir: str
    harness: ContentModelHarness
    brief: dict
    article: str
    feedback: str
    image_plan: list[dict]
    article_with_images: str
    html_path: str
    preview_path: str
    warnings: list[str]


WRITING_SYSTEM = """你是一位资深中文内容主编。仅根据用户提供的资料写作，不要引入资料外的具体数据、认证、效果或案例。
写一篇可直接用于微信公众号的完整 Markdown 长文，目标 6500 字符左右，最低不少于 4500 字符。
必须包含：一个有张力的 # 标题；300 至 500 字的开篇引入和引用金句；4 至 6 个 ## 章节；每章至少 2 个自然段、每段 120 至 260 字；必要时使用 ### 小节；300 至 500 字的结语与行动号召。
先充分展开资料中的背景、问题、方法、产品/能力、应用场景和下一步行动，再收束文章。避免机械的“首先/其次/最后”，不声称资料没有支持的事实，不用空洞重复来凑字数。"""

REVISION_SYSTEM = """你是一位资深中文内容主编。根据用户的修改意见修订一篇微信公众号 Markdown 文章。
只保留资料能够支撑的事实，不新增资料外的具体数据、认证、效果或案例。完整输出修改后的文章，不要说明修改过程，不要输出 Markdown 代码围栏。保留文章的 # 标题与清晰章节结构；没有被要求修改的内容尽量保持原意。"""


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

资料：
{state['material_text']}
"""
    article = state["harness"].text(WRITING_SYSTEM, user, "generate_master_content")
    if not article.startswith("#"):
        article = f"# {request.topic}\n\n{article}"
    if len(article) < settings.article_min_chars:
        expand_system = """你是微信公众号资深编辑。请在不改变原文事实、不新增资料外信息的前提下，把文章扩写到目标长度。
保留原有标题和章节，补充资料中已有的背景、机制、场景、细节、段落过渡和读者行动建议；不要重复句子，不要添加来源中没有的数字或承诺。
只输出完整 Markdown 文章，目标长度约 6500 字符，最低 4500 字符。"""
        article = state["harness"].text(expand_system, f"目标长度：{settings.article_target_chars} 字符\n\n原文：\n{article}\n\n资料：\n{state['material_text']}", "expand_master_content")
        if not article.startswith("#"):
            article = f"# {request.topic}\n\n{article}"
    return {"article": article}


def revise_article(state: WorkflowState) -> WorkflowState:
    article = state["harness"].text(
        REVISION_SYSTEM,
        f"""用户修改意见：
{state['feedback']}

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
    system = """你是微信公众号视觉总监。根据文章真实内容规划配图，严格只输出 JSON：{\"images\":[{\"filename\":\"cover.png\",\"placement\":\"cover\",\"alt\":\"中文图片说明\",\"insert_after_heading\":\"\",\"visual_focus\":\"本图要证明/表达的具体内容\",\"prompt\":\"English prompt for GPT Image 2\"}]}。
必须恰好返回指定数量的图片，第一张 placement 必须是 cover，其余全部是 body。
每张 body 图的 insert_after_heading 必须从给定章节标题中原样选择；visual_focus 必须对应该章节的具体信息，禁止泛泛写“科技感”“抽象分子”。英文 Prompt 必须明确主体、场景、构图、光线和与章节内容的视觉关系，不要生成长文本、Logo、品牌名或资料中没有的产品属性。"""
    data = state["harness"].json(system, f"需要恰好 {request.image_count} 张图片。可绑定的章节标题：{json.dumps(headings, ensure_ascii=False)}\n\n文章：\n{state['article']}", "plan_images")
    items = [ImagePlanItem.model_validate(item).model_dump() for item in data.get("images", [])]
    if len(items) != request.image_count:
        raise RuntimeError(f"图片计划数量不正确：期望 {request.image_count}，实际 {len(items)}")
    items[0]["filename"] = "cover.png"
    items[0]["placement"] = "cover"
    for item_index, item in enumerate(items[1:], start=1):
        item["placement"] = "body"
        if item["insert_after_heading"] not in headings:
            item["insert_after_heading"] = headings[min(item_index - 1, len(headings) - 1)] if headings else ""
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
    items = []
    for index, item in enumerate(state["image_plan"]):
        filename = re.sub(r"[^a-zA-Z0-9_.-]", "-", item["filename"] or f"image-{index + 1}.png")
        if not filename.endswith(".png"):
            filename += ".png"
        state["harness"].image(item["prompt"], images_dir / filename)
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


def _create_job_dir() -> tuple[str, Path]:
    job_id = uuid.uuid4().hex[:12]
    job_dir = settings.storage_dir / "jobs" / job_id
    job_dir.mkdir(parents=True, exist_ok=False)
    return job_id, job_dir


def _write_run_metadata(job_dir: Path, request: ContentRequest, harness: ContentModelHarness, parent_job_id: str | None = None) -> None:
    metadata = {
        "request": request.model_dump(mode="json"),
        "text_api": {"base_url": settings.text_base_url, "model": settings.text_model},
        "image_api": {"base_url": settings.image_base_url, "model": settings.image_model},
        "trace": harness.trace,
    }
    if parent_job_id:
        metadata["parent_job_id"] = parent_job_id
    (job_dir / "run.json").write_text(json.dumps(metadata, ensure_ascii=False, indent=2), encoding="utf-8")


def run_generation(request: ContentRequest, material_text: str) -> dict:
    job_id, job_dir = _create_job_dir()
    (job_dir / "source_material.md").write_text(material_text, encoding="utf-8")
    harness = ContentModelHarness(enable_image_generation=request.image_count > 0)
    final = build_graph().invoke({"request": request, "material_text": material_text, "job_dir": str(job_dir), "harness": harness})
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
