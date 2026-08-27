import base64
import json
import shutil
import uuid
from pathlib import Path

import streamlit as st
import streamlit.components.v1 as components

from app.config import settings
from app.harness import ProviderUnavailableError, VisionApiClient
from app.materials import IMAGE_SUFFIXES, merge_materials
from app.schemas import AUDIENCE_LABELS, Audience, ContentRequest
from app.workflow import run_generation, run_revision


st.set_page_config(page_title="Content Agent", page_icon="✦", layout="wide", initial_sidebar_state="expanded")


def store_uploads(files) -> list[Path]:
    upload_dir = settings.storage_dir / "uploads" / uuid.uuid4().hex
    upload_dir.mkdir(parents=True, exist_ok=False)
    paths = []
    for uploaded in files:
        suffix = Path(uploaded.name).suffix.lower()
        if suffix not in {".pdf", ".docx", ".txt", ".md", ".xlsx", ".xlsm", ".csv", ".png", ".jpg", ".jpeg", ".webp"}:
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


def preview_html(html_path: Path, image_dir: Path) -> str:
    """Embed generated images so the result renders inside Streamlit without a static-file server."""
    content = html_path.read_text(encoding="utf-8")
    job_id = image_dir.parent.name
    for image in image_dir.glob("*.png"):
        encoded = base64.b64encode(image.read_bytes()).decode("ascii")
        source = f"/assets/jobs/{job_id}/images/{image.name}"
        content = content.replace(source, f"data:image/png;base64,{encoded}")
    return content


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
    uploaded_files = st.file_uploader("资料", type=["pdf", "docx", "txt", "md", "xlsx", "xlsm", "csv", "png", "jpg", "jpeg", "webp"], accept_multiple_files=True, help="支持文档、表格和图片资料。图片需要配置视觉模型后才能提取内容。")
    primary_audience = st.selectbox("主要用户（必选且只能一类）", list(Audience), index=None, format_func=lambda item: AUDIENCE_LABELS[item], placeholder="选择主要用户")
    brand_name = st.text_input("品牌名称", placeholder="可选")
    with st.expander("生成偏好", expanded=False):
        image_count = st.select_slider("图片数量", options=list(range(10)), value=3, format_func=lambda value: "不生成图片" if value == 0 else f"{value} 张")
        theme = st.selectbox("公众号排版主题", ["石墨极简风", "摸鱼绿", "红白色系", "留白禅意风", "摸鱼票据风", "橄榄手记"])
        call_to_action = st.text_input("行动号召", value="了解更多")
    st.divider()
    st.caption(f"文本：{settings.text_model} · 图片：{settings.image_model}")
    has_image_materials = bool(uploaded_files and any(Path(file.name).suffix.lower() in IMAGE_SUFFIXES for file in uploaded_files))
    if not settings.text_api_key:
        st.warning("请在 .env 配置文本 API Key。")
    elif image_count > 0 and not settings.image_api_key:
        st.warning("生成图片时，请在 .env 配置图片 API Key。")
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

is_revision = st.session_state.last_job is not None
prompt = st.chat_input("对当前成品提出修改建议，例如：语气更专业一些，删掉第三章" if is_revision else "告诉我你想生成什么内容……")
if prompt:
    if not is_revision and (not primary_audience or not uploaded_files):
        st.warning("请先在左侧选择主要用户并上传资料，再提交请求。")
        st.stop()
    st.session_state.messages.append({"role": "user", "content": prompt})
    with st.chat_message("user"):
        st.markdown(prompt)

    upload_paths: list[Path] = []
    try:
        with st.chat_message("assistant"):
            if is_revision:
                with st.status("正在根据修改意见调整内容并刷新成品", expanded=True) as status:
                    result = run_revision(st.session_state.last_job, prompt)
                    status.update(label="修改后的成品已完成", state="complete")
                completion_message = "已按你的意见生成新版本，可继续提出修改建议。"
            else:
                upload_paths = store_uploads(uploaded_files)
                has_images = any(path.suffix.lower() in IMAGE_SUFFIXES for path in upload_paths)
                material_text = merge_materials(upload_paths, image_to_text=VisionApiClient().describe if has_images else None)
                request = ContentRequest(topic=prompt[:120], primary_audience=primary_audience, objective=prompt, call_to_action=call_to_action, brand_name=brand_name, image_count=image_count, theme=theme)
                task_label = "正在理解请求、撰写长文并进行公众号排版" if image_count == 0 else "正在理解请求、撰写长文并规划对应视觉"
                with st.status(task_label, expanded=True) as status:
                    st.write("读取资料与受众上下文…")
                    result = run_generation(request, material_text)
                    status.update(label="内容成品已完成", state="complete")
                completion_message = "已完成：公众号成品预览。可继续在对话框提出修改建议。"
            st.markdown(completion_message)
        st.session_state.messages.append({"role": "assistant", "content": completion_message})
        st.session_state.last_job = result["job_id"]
    except ProviderUnavailableError as exc:
        st.error(str(exc))
    except Exception as exc:
        st.error(f"生成失败：{exc}")
    finally:
        cleanup_uploads(upload_paths)

if st.session_state.last_job:
    job_dir = settings.storage_dir / "jobs" / st.session_state.last_job
    article_path = job_dir / "article.md"
    html_path = job_dir / "wechat.html"
    preview_path = job_dir / "wechat_preview.html"
    image_dir = job_dir / "images"
    st.divider()
    st.subheader("本轮产物")
    metrics = st.columns(3)
    metrics[0].metric("主内容", f"{len(article_path.read_text(encoding='utf-8')):,} 字符")
    metrics[1].metric("视觉资产", f"{len(list(image_dir.glob('*.png')))} 张")
    metrics[2].metric("渠道", "微信公众号")
    tab_wechat, tab_images = st.tabs(["公众号成品", "生成图片"])
    with tab_wechat:
        st.caption("排版已通过公众号兼容性校验。")
        components.html(preview_html(html_path, image_dir), height=1050, scrolling=True)
        download_file("下载可复制预览页", preview_path, "text/html")
    with tab_images:
        images = sorted(image_dir.glob("*.png"))
        if not images:
            st.info("本次选择不生成图片。")
        for index, image in enumerate(images):
            st.image(str(image), caption="封面" if index == 0 else f"正文配图 {index}", use_container_width=True)
