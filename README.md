# Content Agent

一个资料驱动的内容生成 Agent。当前支持微信公众号和小红书图文两个独立渠道：用户上传资料、选择唯一主要用户和内容需求后，系统按渠道生成内容、图片和可预览的发布产物。用户可继续在工作台提出修改意见，系统会保留原版本并生成新的成品版本。知乎、LinkedIn、邮件、PPT 和视频仍属于后续扩展方向。

本版刻意不做企业知识库、证据评级、法规审批和自动发布。它保留资料、生成版本与模型运行记录，后续可平滑补上这些能力。

## 代码结构

```text
app/
├── api.py                 # 应用组装、生命周期和静态资源挂载
├── dependencies.py        # FastAPI 依赖注入：settings / database_url
├── routers/               # HTTP 路由：系统、内容生成、任务、页面
├── services/
│   ├── generation_service.py # 任务创建、状态流转和渠道调度
│   ├── job_runner.py      # 后台任务池与重启恢复
│   ├── content_service.py # 上传文件与生成产物
│   └── task_service.py    # PostgreSQL 任务持久化
├── models/                # SQLAlchemy ORM 模型和数据库初始化
├── channels/              # 渠道适配层：每个内容平台一个 generate 实现
├── prompts.py             # 提示词与视觉/版式资产（独立于编排）
├── forbidden_words.py     # 内置禁用词库（R3：分类固化，无手动输入）
├── schemas/               # Pydantic 请求与响应模型
└── workflow.py            # 公众号内容生成节点与 LangGraph 编排
```

路由层只负责参数校验、状态码和响应转换；`generation_service` 负责任务生命周期和后台执行入口；`workflow` 只负责公众号内容节点；`channels` 负责平台差异。数据库表模型集中在 models，配置通过 FastAPI `Depends` 注入，便于后续加入迁移、鉴权和更多内容渠道。

## 能力边界

1. 上传 PDF、DOCX、TXT、Markdown、XLSX、XLSM、CSV 或图片资料。
2. 选择八类用户中的唯一主要用户。
3. 阿里百炼文本 API 使用 Qwen3.7 生成公众号 Markdown 与图片计划。
4. 独立图片 API 默认使用阿里百炼 `qwen-image-3.0` 生成封面和正文配图。
5. 使用固定版本的 `gzh-design-skill` 主题组件库生成公众号兼容 HTML，并运行其合规校验和预览包装脚本。
6. 先生成可编辑文章大纲，确认后再生成正文、配图与公众号排版成品。
7. 生成时可控制目标字数和事实依据范围；文章语气、结构与内容重点由主要用户画像自动匹配，禁用词由系统内置。

公众号采用“标题候选 → 大纲候选 → 正文 → 配图 → 排版”的确认式流程；小红书采用“卡片规划 → 图片来源分配 → 图片生成/实拍图处理 → 发布文案与预览”的流程。上传的小红书实拍图会优先使用，图片不足时由 AI 补足，图片数量始终以用户选择为准。

## 启动

```powershell
cd D:\PythonProject\content-agent
if (!(Test-Path .env)) {
    Copy-Item .env.example .env
}
docker compose up --build
```

打开 `http://localhost:8000`。FastAPI 和 PostgreSQL 都运行在 Docker 中，任务历史使用 PostgreSQL，文章和图片产物保存在本机 `storage` 目录。

停止服务：

```powershell
docker compose down
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
IMAGE_BASE_URL=https://dashscope.aliyuncs.com/compatible-mode/v1
IMAGE_MODEL=qwen-image-3.0
```

默认生图模型为阿里百炼的 `qwen-image-3.0`。当 `IMAGE_BASE_URL` 使用 `dashscope.aliyuncs.com` 时，程序会自动切换到百炼原生的异步生图接口（`/api/v1/services/aigc/image-generation/generation`），并轮询任务后下载图片；不要把该模型当作 `/v1/images/generations` 的 OpenAI 图片接口调用。请将 `IMAGE_API_KEY` 设置为百炼 API Key。若使用其他兼容服务，可按其接口要求覆盖 `IMAGE_BASE_URL`，程序仍会使用 OpenAI 兼容图片接口。

当供应商返回 `429`、`502`、`503` 或 `504` 时，系统会读取其 `retry_after`（若有）并自动退避重试一次；重试耗尽后会显示对应的文本或图片 API 暂不可用提示。

百炼异步图片任务最多等待 `IMAGE_TASK_TIMEOUT_SECONDS`（默认 600 秒），与文本请求超时独立配置。

默认 API 请求使用 Windows 全局代理。仅当你已确认可以直连供应商端点时，在 `.env` 设置 `API_USE_SYSTEM_PROXY=false`。

对于百炼 Qwen 内容生成，默认会发送 `enable_thinking=false`，避免非流式思考造成的超时。需要深度推理时可设为 `TEXT_ENABLE_THINKING=true`，并相应提高 `REQUEST_TIMEOUT_SECONDS`。

接口文档位于 `http://localhost:8000/docs`。

## 测试

```powershell
cd D:\PythonProject\content-agent
.venv\Scripts\python.exe -m pytest -q
node --check frontend\app.js
.venv\Scripts\python.exe -m compileall -q app
```

测试覆盖接口参数校验、标题与大纲选择、公众号图片数量与排版、小红书实拍图/AI 图分配、禁用词、版本修改、任务数据库和下载产物。

数据库数据位于 Docker volume `content-agent_postgres_data`，不会因为停止容器而丢失。删除该 volume 才会清空任务数据库。

## 产物

每次生成写入 `storage/jobs/<job_id>/`：

- `source_material.md`：从上传文件提取的资料。
- `article.md`：主内容 Markdown。
- `image_plan.json`：每张图的用途、位置与 Prompt。
- `images/`：模型生成图片。
- `article_with_images.md`：已插入图片的 Markdown。
- `wechat.html`：可粘贴进公众号的正文片段。

小红书图文会额外生成 `cards/` 中的 3:4 成品卡片、`caption.txt` 发布文案、`card_plan.json` 卡片计划和 `xiaohongshu_preview.html` 预览页。图片背景由模型生成，中文标题与正文由本地排版，避免模型直接生成中文造成的错字或不可读。
- `wechat_preview.html`：包含复制按钮的本地预览页面。
- `run.json`：本次请求、模型和输出元数据。

项目根目录下的 `*.log` 仅用于本地调试启动和依赖安装，不是业务必需文件，已加入 `.gitignore`。正式运行可直接使用上述 FastAPI 启动命令，无需把输出重定向为日志文件。
