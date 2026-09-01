# Content Agent

一个资料驱动的内容生成 Agent。当前实现微信公众号作为第一个渠道模块：用户上传资料、选择唯一主要用户和内容需求后，系统生成内容、配图建议、AI 图片与微信公众号 HTML 排版预览。用户可继续在工作台提出修改意见，系统会保留原版本并生成新的成品版本。后续可按同一主内容扩展小红书、知乎、LinkedIn 和邮件。

本版刻意不做企业知识库、证据评级、法规审批和自动发布。它保留资料、生成版本与模型运行记录，后续可平滑补上这些能力。

## 能力边界

1. 上传 PDF、DOCX、TXT、Markdown、XLSX、XLSM、CSV 或图片资料。
2. 选择八类用户中的唯一主要用户。
3. 阿里百炼文本 API 使用 Qwen3.7 生成公众号 Markdown 与图片计划。
4. 独立图片 API 使用 GPT Image 2 生成封面和正文配图。
5. 使用固定版本的 `gzh-design-skill` 主题组件库生成公众号兼容 HTML，并运行其合规校验和预览包装脚本。
6. 先生成可编辑文章大纲，确认后再生成正文、配图与公众号排版成品。
7. 生成时可控制目标字数、文章语气、结构、事实依据范围和禁用词。

## 启动

```powershell
cd D:\PythonProject\content-agent
uv sync --all-groups
Copy-Item .env.example .env
```

项目已将 `uv` 默认索引配置为清华 PyPI 镜像。临时切回官方源时可执行：

```powershell
$env:UV_DEFAULT_INDEX = "https://pypi.org/simple"
uv sync --all-groups
```

在 `.env` 中分别设置文本、视觉与图片 API 配置。它们可以指向不同的供应商、端点与密钥。不要把密钥提交到 Git：

```env
TEXT_API_KEY=<阿里百炼 API Key>
TEXT_BASE_URL=https://dashscope.aliyuncs.com/compatible-mode/v1
TEXT_MODEL=qwen3.7-plus
TEXT_ENABLE_THINKING=false
TEXT_MAX_TOKENS=4000
# Optional: leave empty to reuse the multimodal TEXT_MODEL for image reference materials.
VISION_API_KEY=
VISION_BASE_URL=
VISION_MODEL=
IMAGE_API_KEY=
IMAGE_BASE_URL=https://tokenflux.dev/v1
IMAGE_MODEL=gpt-image-2
```

当供应商返回 `429`、`502`、`503` 或 `504` 时，系统会读取其 `retry_after`（若有）并自动退避重试一次；重试耗尽后会显示对应的文本或图片 API 暂不可用提示。

默认 API 请求使用 Windows 全局代理。仅当你已确认可以直连供应商端点时，在 `.env` 设置 `API_USE_SYSTEM_PROXY=false`。

对于百炼 Qwen 内容生成，默认会发送 `enable_thinking=false`，避免非流式思考造成的超时。需要深度推理时可设为 `TEXT_ENABLE_THINKING=true`，并相应提高 `REQUEST_TIMEOUT_SECONDS`。

启动 FastAPI 后端与前端工作台：

```powershell
uv run python -m uvicorn app.api:app --host 127.0.0.1 --port 8000 --reload
```

打开 `http://localhost:8000`。前端静态页面由 FastAPI 提供，接口文档位于 `http://localhost:8000/docs`。

也可以使用项目入口启动：

```powershell
uv run python api_server.py
```

## 产物

每次生成写入 `storage/jobs/<job_id>/`：

- `source_material.md`：从上传文件提取的资料。
- `article.md`：主内容 Markdown。
- `image_plan.json`：每张图的用途、位置与 Prompt。
- `images/`：模型生成图片。
- `article_with_images.md`：已插入图片的 Markdown。
- `wechat.html`：可粘贴进公众号的正文片段。
- `wechat_preview.html`：包含复制按钮的本地预览页面。
- `run.json`：本次请求、模型和输出元数据。

项目根目录下的 `*.log` 仅用于本地调试启动和依赖安装，不是业务必需文件，已加入 `.gitignore`。正式运行可直接使用上述 FastAPI 启动命令，无需把输出重定向为日志文件。
