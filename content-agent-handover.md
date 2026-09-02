Content Agent 项目交接文档

资料驱动的多渠道内容生成 Agent · 当前已实现渠道：微信公众号

文档日期：2026-09-01  |  项目目录：D:\PythonProject\content-agent

**交接结论：**当前项目已经从早期 Streamlit 单体 Demo 重构为 Docker + FastAPI + PostgreSQL 架构，支持资料上传、公众号文章大纲确认、成稿生成、配图生成、HTML 排版预览、版本修订和任务历史管理。

# 1. 当前完成范围

| 能力 | 当前状态 |
|---|---|
| 资料输入 | 支持 PDF、DOCX、TXT、Markdown、XLSX、XLSM、CSV 以及图片资料。 |
| 受众策略 | 内置 8 类主要用户；每次生成选择一个主要用户，并据此影响语气、关注点和结构。 |
| 公众号内容生成 | 支持先生成可编辑大纲，确认后生成 Markdown 正文、图片计划和公众号 HTML。 |
| 图片生成 | 根据图片计划调用独立图片 API，生成封面和正文配图；正文图片保留章节绑定信息。 |
| 公众号排版 | 使用 vendor/gzh-design-skill 组件库生成、校验并包装公众号 HTML 预览页。 |
| 任务管理 | 任务历史写入 PostgreSQL，可查看任务列表、任务详情、状态和生成文件，并支持删除任务。 |
| 版本修订 | 用户可对已完成文章提交修改意见，系统保留父版本关系并生成新的任务版本。 |
| 运行方式 | 应用与数据库统一通过 Docker Compose 启动；SQLite 已彻底移除。 |

# 2. 当前架构

Docker Compose  ├── app：FastAPI + LangGraph + 模型调用 + 前端静态文件  └── db：PostgreSQL 16

浏览器 -> FastAPI routers -> services/workflow -> PostgreSQL + storage/jobs + 外部模型 API

## 2.1 三层代码结构

| 路径 | 职责 |
|---|---|
| app/api.py | 组装 FastAPI 应用、生命周期、数据库初始化、静态资源挂载。 |
| app/routers/ | HTTP 路由，负责请求校验、状态码和响应转换。 |
| app/services/ | 上传、任务结果组装、文件安全检查等业务逻辑。 |
| app/models/ | SQLAlchemy ORM 模型和 PostgreSQL 初始化。 |
| app/schemas/ | Pydantic 请求与响应模型。 |
| app/workflow.py | LangGraph 内容生成工作流、扩写、图片计划、排版和修订。 |
| app/harness.py | 文本、视觉和图片 API 客户端，包含代理、超时和重试策略。 |
| app/materials.py | 多种资料格式的文本提取、图片描述和内容合并。 |
| app/audiences.py | 主要用户类型及其内容策略。 |
| app/gzh_adapter.py | 微信公众号主题列表、排版适配和 gzh-design-skill 脚本调用。 |
| frontend/ | 当前实际使用的前端：index.html、app.js、styles.css。通过 URL 路径 /static 提供访问。 |
| vendor/gzh-design-skill/ | 固定版本的公众号排版组件库和校验脚本。 |

# 3. API 路径

| 方法 | 路径 | 用途 |
|---|---|---|
| GET | / | 返回前端首页。 |
| GET | /api/health | 健康检查，正常返回 status=ok。 |
| GET | /api/themes | 获取可用公众号排版主题。 |
| POST | /api/outlines | 上传资料并生成待确认大纲。 |
| POST | /api/outlines/{job_id}/generate | 提交修改后的大纲，生成完整成品。 |
| POST | /api/generate | 直接执行完整生成流程。 |
| POST | /api/jobs/{job_id}/revision | 基于已有任务反馈生成新版本。 |
| GET | /api/jobs | 查询任务历史。 |
| GET | /api/jobs/{job_id} | 查询任务详情。 |
| DELETE | /api/jobs/{job_id} | 删除任务及其关联文件。 |
| GET | /api/jobs/{job_id}/files/{filename} | 下载或查看任务文件。 |

# 4. 数据与文件存储

**PostgreSQL 数据库：**Docker 服务名为 db，数据库名、用户名和密码当前均为 content_agent，宿主机端口为 5432。

DATABASE_URL=postgresql+psycopg://content_agent:content_agent@db:5432/content_agent

## 4.1 当前业务表

| 表名 | 内容 |
|---|---|
| content_jobs | 任务 ID、状态、标题、主题、目标、请求 JSON、大纲、警告、父版本关系、创建时间和更新时间。 |

**本地文件产物：**每次生成写入 storage/jobs/<job_id>/，数据库保存元数据，文件系统保存大文件。**注意：**删除 Docker 容器不会清除 PostgreSQL volume；删除 volume 才会清空数据库。

- source_material.md：提取后的资料

- article.md：主内容 Markdown

- image_plan.json：图片计划

- images/：生成图片

- article_with_images.md：插入图片后的 Markdown

- wechat.html：公众号正文片段

- wechat_preview.html：带预览/复制功能的页面

- run.json：本次运行参数和元数据

# 5. 启动与停止

cd D:\PythonProject\content-agentCopy-Item .env.example .env   # 仅在 .env 不存在时执行docker compose up --build

浏览器访问：**http://localhost:8000**

接口文档：**http://localhost:8000/docs**

docker compose down

## 5.1 检查运行状态

docker compose psdocker compose logs appdocker compose logs db

# 6. 查看 PostgreSQL 数据

docker compose exec db psql -U content_agent -d content_agent

\dt\d content_jobsSELECT count(*) FROM content_jobs;SELECT job_id, status, title, created_at FROM content_jobs ORDER BY created_at DESC;\q

# 7. 配置与安全

- TEXT_API_KEY、TEXT_BASE_URL、TEXT_MODEL：文本生成服务。

- VISION_API_KEY、VISION_BASE_URL、VISION_MODEL：可选的视觉资料理解服务；为空时复用文本配置。

- IMAGE_API_KEY、IMAGE_BASE_URL、IMAGE_MODEL：图片生成服务。

- REQUEST_TIMEOUT_SECONDS、PROVIDER_RETRY_*：超时和供应商错误重试。

- API_USE_SYSTEM_PROXY：是否使用 Windows 系统代理，当前默认值为 true。

- 真实密钥只放在本地 .env 或部署环境中，不得提交到 Git、写入日志、前端或任务产物。

# 8. 验证结果与 Git 状态

当前已验证：

- FastAPI 应用可以连接 PostgreSQL 并完成启动初始化。

- Docker Compose 配置可解析，app 和 db 服务可正常运行。

- 健康接口 /api/health 返回 {"status":"ok"}。

- 项目测试最近一次全量结果为 24 passed。

- SQLite 相关代码、数据库文件和本地启动入口已清理。

当前分支：main与远程状态：main 与 origin/main 同步最新提交：147e1c8 refactor: use PostgreSQL exclusively

# 9. 当前未完成内容

**多渠道生成：**小红书、知乎、LinkedIn 和邮件目前已完成内容风格定位和产品规划，但尚未实现独立生成模式、路由、模板和验收测试。

- 企业账号、权限隔离和多租户。

- 异步任务队列、失败重试和任务恢复。

- 对象存储或可长期访问的图片 URL。

- 上传文件大小限制、恶意文件扫描和数据保留策略。

- 事实引用、内容审核、品牌合规和发布前检查。

- 模型调用耗时、成本、成功率和存储占用监控。

# 10. 建议后续顺序

| 优先级 | 建议事项 | 验收重点 |
|---|---|---|
| P0 | 密钥轮换和生产配置隔离 | 代码库、日志和前端中不存在真实密钥。 |
| P0 | 任务与文件保留/清理策略 | 过期任务可自动清理且有记录。 |
| P1 | 完善端到端测试 | 模拟模型服务，覆盖大纲、成稿、图片、排版和修订链路。 |
| P1 | 实现多渠道内容适配 | 同一资料可选择小红书、知乎、LinkedIn 或邮件，并输出对应格式。 |
| P2 | 账号、权限和异步化 | 任务按用户隔离，长任务可查询、重试和恢复。 |

# 11. 交接操作清单

- 确认 D:\PythonProject\content-agent 为当前代码目录。

- 确认 .env 已配置文本、视觉和图片服务密钥，且未提交到 Git。

- 执行 docker compose up --build，访问 http://localhost:8000。

- 在 /docs 检查接口，在页面完成一次大纲生成和成品生成。

- 执行 docker compose exec db psql -U content_agent -d content_agent 查看任务记录。

- 执行 uv run python -m pytest -q；若本机 uv 不可用，使用项目虚拟环境中的 pytest。

- 提交代码后使用 git push origin main 推送；当前交接文档本身也应纳入版本控制。
