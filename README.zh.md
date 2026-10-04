<div align="center">

# Progress

[English](README.md) | 中文

**追踪多个仓库的代码变更，运行 AI（人工智能）分析，为你关注的开源项目交付进展报告。**

[![CI](https://github.com/jukanntenn/progress/actions/workflows/ci.yml/badge.svg?branch=main)](https://github.com/jukanntenn/progress/actions/workflows/ci.yml) [![Python](https://img.shields.io/badge/Python-3.12+-3776AB?logo=python&logoColor=white)](https://www.python.org/) [![Docker](https://img.shields.io/badge/Docker-Ready-2496ED?logo=docker)](https://www.docker.com/) [![FastAPI](https://img.shields.io/badge/FastAPI-0.115+-009688?logo=fastapi)](https://fastapi.tiangolo.com/) [![Vite](https://img.shields.io/badge/Vite-React%2019-646CFF?logo=vite&logoColor=white)](https://vite.dev/)

</div>

---

## 功能特性

- 📊 **多仓库监控**：一次性跟踪多个 GitHub 仓库的提交与发布
- 🤖 **AI 驱动的分析**：通过任意 [Pydantic AI](https://ai.pydantic.dev/) 提供方（Anthropic、OpenAI、OpenAI 兼容端点），把原始 diff 转写成简洁的 Markdown 变更报告
- 📝 **提案跟踪**：监视 EIP / ERC / PEP / RFC / DEP 提案，状态变化时发出通知
- 📋 **Changelog 跟踪**：从任意 changelog URL 检测新版本
- 📰 **Feed 集成**：从 Miniflux 实例接入星标/自有 RSS 源并分析新条目
- 📬 **通知**：把报告推送到飞书、邮件或控制台
- 🌐 **Web 面板**：浏览聚合报告、通过 UI 在线编辑配置，并经 RSS 订阅
- 🔭 **可观测性**：结构化日志、OpenTelemetry 链路追踪，并通过 [Bugsink](https://www.bugsink.com/) 采集错误
- 🌍 **国际化**：经 Babel 提取的消息目录（英文 + 简体中文）
- 🐳 **单容器部署**：一个加固镜像（Caddy + FastAPI + Vite SPA，由 s6-overlay 托管并内置 supercronic 调度器），一分钟内即可就绪

## 工作原理

1. **克隆与 diff**：Progress 拉取每个已配置的仓库，计算自上次运行以来的 diff
2. **分析**：Progress 把 diff 发送给 AI 提供方（例如 `anthropic:claude-sonnet-4`），产出人类可读的摘要
3. **发布**：报告写入数据库，可选择上传到 [Markpost](https://github.com/jukanntenn/markpost)，并推送到你的通知渠道
4. **调度**：cron 表达式按你选定的节奏触发整条流水线

## 快速开始

完整指南见 [docs/deployment.md](docs/deployment.zh.md)。

1. 准备配置与数据目录：

   ```bash
   cp config.example.db.toml config.db.toml   # DB seed (credentials, repos, channels)
   cp config.example.toml      config.toml     # infrastructure (state_home)
   mkdir -p data
   chown 100:101 data                          # image runs as uid 100 / gid 101
   ```

2. 编辑 `config.db.toml`：至少设置 `[core.github].gh_token` 与 `[core.analysis]`，并添加一个 `[[repo.repos]]` 条目（见[配置说明](#configuration)）。

3. 创建 `docker-compose.yml`：

   ```yaml
   services:
     progress:
       image: ghcr.io/jukanntenn/progress:latest
       container_name: progress
       ports:
         - "5000:5000"
       user: "100:101"
       read_only: true
       tmpfs:
         - /tmp
         - /run:rw,exec,mode=0755,uid=100,gid=101
         - /home/progress
       cap_drop: ["ALL"]
       security_opt: ["no-new-privileges:true"]
       volumes:
         - ./config.toml:/app/config.toml:ro
         - ./data:/app/data
       environment:
         - TZ=UTC
         - S6_READ_ONLY_ROOT=1
         - PROGRESS_SCHEDULE_CRON=0 8 * * *   # daily at 08:00
       restart: unless-stopped
   ```

4. 启动容器，然后在 `http://<your-host>:5000` 打开 Web UI：

   ```bash
   docker compose up -d
   docker compose logs -f
   ```

设置 `PROGRESS_SCHEDULE_CRON` 后，Progress 会在启动时运行一次流水线，随后按给定的 cron 计划执行。不设置该变量时，可用 `docker compose exec progress progress run` 手动驱动运行。

<a id="configuration"></a>

## 配置说明

Progress 采用**双文件**配置模型：

- **`config.toml`**（Ansible 级）：仅承载基础设施，目前只有 `state_home`（`progress.db`、日志和克隆仓库都存放在这里）。参见 `config.example.toml`。
- **`config.db.toml`**（数据库种子）：应用配置，启动时导入数据库。复制 `config.example.db.toml` 作为种子。首次运行后**数据库即为真源**：日常设置通过 **Web UI**（`/config` 页面）或 API（`PUT /api/v1/config/{section}`）修改，也可以编辑 `config.db.toml` 后重启以重新导入种子。

优先级：**数据库 > 种子（`config.db.toml`）> 代码默认值**；环境变量覆盖（`PROGRESS_` 前缀）在种子导入时叠加生效。凭据缺失（`gh_token`、`api_key`）会优雅降级：受影响的集成被禁用并发出告警，而不是崩溃（零配置）。

完整模型见 [docs/config.md](docs/config.zh.md)。一份最小化的 `config.db.toml` 种子：

```toml
[core]
language = "en"
timezone = "UTC"

[core.github]
gh_token = "ghp_xxxxxxxxxxxxxxxxxxxx"        # empty -> GitHub tracking disabled

[core.analysis]
provider = "anthropic"                        # any Pydantic AI provider
model = "claude-sonnet-4"
api_key = "sk-xxxxxxxxxxxxxxxx"               # empty -> AI analysis disabled

[[core.notification.channels]]
type = "console"                              # console | email | feishu
enabled = true

[repo]
first_run_lookback_commits = 3

[[repo.repos]]
url = "vitejs/vite"                           # "owner/repo", HTTPS, or SSH URL
branch = "main"
enabled = true
```

用带 `PROGRESS_` 前缀的环境变量可以覆盖任意配置值（嵌套键以 `__` 分隔）：

```bash
PROGRESS_CORE__TIMEZONE="Asia/Shanghai"
PROGRESS_CORE__GITHUB__GH_TOKEN="ghp_xxx"
PROGRESS_CORE__ANALYSIS__PROVIDER="openai"
PROGRESS_STATE_HOME="/app/data"
```

## Web 服务

容器在 `5000` 端口暴露 Web UI 与 JSON API：

| 路径                           | 说明                                    |
| ------------------------------ | --------------------------------------- |
| `/healthz`、`/readyz`          | 存活/就绪探针（k8s 风格）               |
| `/reports`                     | 聚合报告浏览器（根路径 `/` 重定向到此） |
| `/reports/:id`                 | 单条报告的完整内容                      |
| `/integrations`                | 各集成的状态概览                        |
| `/config`                      | 在线配置编辑器（写入数据库）            |
| `/api/v1/version`              | 构建/版本信息（JSON）                   |
| `/api/v1/reports`              | 报告列表与详情（JSON）                  |
| `/api/v1/integrations`         | 集成状态（JSON）                        |
| `/api/v1/config`               | 读取在线配置（JSON）                    |
| `/api/v1/config/schema`        | 配置模型的 JSON Schema                  |
| `PUT /api/v1/config/{section}` | 更新单个配置节                          |
| `/api/v1/rss`                  | 最新报告的 RSS 订阅源                   |

## 开发

参见 [docs/development.md](docs/development.zh.md)。环境要求：Python 3.12+ 搭配 [uv](https://github.com/astral-sh/uv)，前端为 Node 22+ 搭配 [pnpm](https://pnpm.io/) 11+。

质量门禁（在本地运行与 CI 相同的检查）：

```bash
uv sync --extra dev
uv run ruff check && uv run ruff format --check
uv run ty check
uv run pytest -m "not e2e or (e2e and not feed)"

cd web && pnpm install && pnpm lint && pnpm typecheck && pnpm test && pnpm build
```

更多文档见 [`docs/`](docs/)：[config.md](docs/config.zh.md)、[deployment.md](docs/deployment.zh.md)、[development.md](docs/development.zh.md)、[observability.md](docs/observability.zh.md)、[testing.md](docs/testing.zh.md)。
