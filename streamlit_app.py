import json
import shutil
import uuid
from pathlib import Path

import streamlit as st

from app.config import settings
from app.harness import ProviderUnavailableError
from app.materials import merge_materials
from app.schemas import AUDIENCE_LABELS, Audience, ContentRequest
from app.workflow import run_generation


st.set_page_config(page_title="Content Agent", page_icon="✦", layout="wide", initial_sidebar_state="expanded")


def store_uploads(files) -> list[Path]:
    upload_dir = settings.storage_dir / "uploads" / uuid.uuid4().hex
    upload_dir.mkdir(parents=True, exist_ok=False)
    paths = []
    for uploaded in files:
        suffix = Path(uploaded.name).suffix.lower()
        if suffix not in {".pdf", ".docx", ".txt", ".md"}:
            raise ValueError(f"不支持文件：{uploaded.name}")
        target = upload_dir / uploaded.name
        target.write_bytes(uploaded.getbuffer())
        paths.append(target)
    return paths


def cleanup_uploads(paths: list[Path]) -> None:
    if paths:
        shutil.rmtree(paths[0].parent, ignore_errors=True)


def download_file(label: str, path: Path, mime: str) -> None:
    if path.exists():
        st.download_button(label, data=path.read_bytes(), file_name=path.name, mime=mime, use_container_width=True)


def reset_chat() -> None:
    st.session_state.messages = []
    st.session_state.last_job = None


st.markdown("""
<style>
  .block-container { max-width: 1440px; padding: 1.5rem 2rem 3rem; }
  h1, h2, h3 { font-family: Georgia, 'Songti SC', serif; letter-spacing: 0 !important; }
  [data-testid='stChatMessage'] { border: 1px solid #E4E7DE; border-radius: 8px; padding: 1rem 1.1rem; margin-bottom: .8rem; }
  [data-testid='stChatMessage']:has([data-testid='stChatMessageAvatarAssistant']) { background: #F7FAF2; }
  [data-testid='stChatInput'] { border-color: #AFC28F; }
  div[data-testid='stMetric'] { background: #F2F6EA; padding: .7rem; border-radius: 6px; }
</style>
""", unsafe_allow_html=True)

if "messages" not in st.session_state:
    st.session_state.messages = []
if "last_job" not in st.session_state:
    st.session_state.last_job = None

with st.sidebar:
    st.caption("CONTENT AGENT / CONVERSATION WORKBENCH")
    st.title("内容台")
    st.write("先说你想做什么，资料和受众作为上下文附着在请求上。")
    st.divider()
    st.subheader("上下文")
    uploaded_files = st.file_uploader("资料", type=["pdf", "docx", "txt", "md"], accept_multiple_files=True, help="支持多份资料，生成时只使用这里的内容。")
    primary_audience = st.selectbox("主要用户（必选且只能一类）", list(Audience), index=None, format_func=lambda item: AUDIENCE_LABELS[item], placeholder="选择主要用户")
    brand_name = st.text_input("品牌名称", placeholder="可选")
    with st.expander("生成偏好", expanded=False):
        image_count = st.select_slider("图片数量", options=[2, 3, 4, 5], value=3, format_func=lambda value: f"{value} 张")
        theme = st.selectbox("公众号排版主题", ["石墨极简风", "摸鱼绿", "红白色系", "橄榄手记"])
        call_to_action = st.text_input("行动号召", value="了解更多")
    st.divider()
    st.caption(f"文本：{settings.text_model} · 图片：{settings.image_model}")
    if not settings.text_api_key or not settings.image_api_key:
        st.warning("请在 .env 配置文本和图片 API Key。")
    if st.button("清空对话", use_container_width=True):
        reset_chat()
        st.rerun()

st.caption("CONTENT AGENT")
st.title("把想法说出来，内容台来完成")
st.write("当前首个渠道：微信公众号。你可以用自然语言提出主题、语气、长度和行动目标。")

for message in st.session_state.messages:
    with st.chat_message(message["role"]):
        st.markdown(message["content"])

if not st.session_state.messages:
    with st.chat_message("assistant"):
        st.markdown("你好，我可以根据你上传的资料生成公众号长文、章节配图和排版预览。")
        st.markdown("例如：**基于这些资料，为研发/配方师写一篇解释原料机制与应用价值的公众号文章，语气专业，结尾引导技术交流。**")

prompt = st.chat_input("告诉我你想生成什么内容……")
if prompt:
    if not primary_audience or not uploaded_files:
        st.warning("请先在左侧选择主要用户并上传资料，再提交请求。")
        st.stop()
    st.session_state.messages.append({"role": "user", "content": prompt})
    with st.chat_message("user"):
        st.markdown(prompt)

    upload_paths: list[Path] = []
    try:
        upload_paths = store_uploads(uploaded_files)
        material_text = merge_materials(upload_paths)
        request = ContentRequest(topic=prompt[:120], primary_audience=primary_audience, objective=prompt, call_to_action=call_to_action, brand_name=brand_name, image_count=image_count, theme=theme)
        with st.chat_message("assistant"):
            with st.status("正在理解请求、撰写长文并规划对应视觉", expanded=True) as status:
                st.write("读取资料与受众上下文…")
                result = run_generation(request, material_text)
                status.update(label="内容成品已完成", state="complete")
            st.markdown("已完成：公众号 Markdown、按章节绑定的配图、图片 Prompt 和公众号排版预览。")
        st.session_state.messages.append({"role": "assistant", "content": "已完成：公众号 Markdown、按章节绑定的配图、图片 Prompt 和公众号排版预览。"})
        st.session_state.last_job = result["job_id"]
    except ProviderUnavailableError as exc:
        st.error(str(exc))
    except Exception as exc:
        st.error(f"生成失败：{exc}")
    finally:
        cleanup_uploads(upload_paths)

if st.session_state.last_job:
    job_dir = settings.storage_dir / "jobs" / st.session_state.last_job
    markdown_path = job_dir / "article_with_images.md"
    html_path = job_dir / "wechat.html"
    preview_path = job_dir / "wechat_preview.html"
    image_dir = job_dir / "images"
    st.divider()
    st.subheader("本轮产物")
    metrics = st.columns(3)
    metrics[0].metric("主内容", f"{len(markdown_path.read_text(encoding='utf-8')):,} 字符")
    metrics[1].metric("视觉资产", f"{len(list(image_dir.glob('*.png')))} 张")
    metrics[2].metric("渠道", "微信公众号")
    tab_article, tab_images, tab_wechat = st.tabs(["内容 Markdown", "图片与 Prompt", "公众号排版"])
    with tab_article:
        st.markdown(markdown_path.read_text(encoding="utf-8"))
        download_file("下载 Markdown", markdown_path, "text/markdown")
    with tab_images:
        plan_path = job_dir / "image_plan.json"
        if plan_path.exists():
            plan = json.loads(plan_path.read_text(encoding="utf-8"))
            st.dataframe([{"图片": item["filename"], "位置": item["placement"], "对应章节": item.get("insert_after_heading", "封面"), "视觉重点": item.get("visual_focus", "")} for item in plan], use_container_width=True, hide_index=True)
            for item in plan:
                with st.expander(f"{item['filename']} · {item.get('insert_after_heading', '封面')}"):
                    st.write(item.get("visual_focus", ""))
                    st.code(item["prompt"], language="text")
        for index, image in enumerate(sorted(image_dir.glob("*.png"))):
            st.image(str(image), caption="封面" if index == 0 else f"正文配图 {index}", use_container_width=True)
    with tab_wechat:
        st.info("HTML 已通过 gzh-design-skill 校验。下载预览页后，可打开并复制到公众号编辑器。")
        col_html, col_preview = st.columns(2)
        with col_html:
            download_file("下载公众号 HTML", html_path, "text/html")
        with col_preview:
            download_file("下载可复制预览页", preview_path, "text/html")
        st.code(html_path.read_text(encoding="utf-8")[:4000], language="html")
