[English](README.md) | 简体中文

<div align="center">

# Progress

**追踪多个仓库的代码变更，运行 AI 分析，为你关注的开源项目生成进展报告。**

[![CI](https://github.com/jukanntenn/progress/actions/workflows/ci.yml/badge.svg?branch=main)](https://github.com/jukanntenn/progress/actions/workflows/ci.yml)
[![Python](https://img.shields.io/badge/Python-3.12+-3776AB?logo=python&logoColor=white)](https://www.python.org/)
[![Docker](https://img.shields.io/badge/Docker-Ready-2496ED?logo=docker)](https://www.docker.com/)
[![FastAPI](https://img.shields.io/badge/FastAPI-0.115+-009688?logo=fastapi)](https://fastapi.tiangolo.com/)
[![Vite](https://img.shields.io/badge/Vite-React%2019-646CFF?logo=vite&logoColor=white)](https://vite.dev/)

</div>

---

## 功能特性

- 📊 **多仓库监控** — 同时监控多个 GitHub 仓库，跟踪代码变更
- 🤖 **AI 智能分析** — 通过任意 [Pydantic AI](https://ai.pydantic.dev/) 提供方（Anthropic、OpenAI、OpenAI 兼容端点）将 diff 转换为简洁的 Markdown 报告
- 📝 **提案跟踪** — 监控 EIP / ERC / PEP / RFC / DEP 提案，状态变化时通知
- 📋 **Changelog 跟踪** — 从任意 changelog URL 检测新版本
- 📰 **Feed 集成** — 从 Miniflux 实例拉取星标/订阅的 RSS 源并分析新条目
- 📬 **通知推送** — 将报告推送到飞书、邮件或控制台
- 🌐 **Web 面板** — 浏览聚合报告、通过 UI 在线编辑配置、RSS 订阅
- 🔭 **可观测性** — 结构化日志、OpenTelemetry 链路、通过 [Bugsink](https://www.bugsink.com/) 采集错误
- 🌍 **国际化** — 基于 Babel 提取的消息目录（英文 + 简体中文）
- 🐳 **单容器部署** — 一个加固镜像（Caddy + FastAPI + Vite SPA，由 s6-overlay 托管，内置 supercronic 调度器），一分钟拉起

## 工作原理

1. **克隆 & diff** — Progress 拉取每个配置的仓库，计算自上次运行以来的 diff
2. **分析** — diff 被发送给 AI 提供方（例如 `anthropic:claude-sonnet-4`），生成人类可读的摘要
3. **发布** — 报告存入数据库，可选上传到 [Markpost](https://github.com/jukanntenn/markpost)，并推送到通知渠道
4. **调度** — 通过 cron 表达式按设定的节奏触发整条流水线

## 快速开始

完整指南见 [docs/deployment.md](docs/deployment.md)。

1. 准备配置文件和数据目录：

   ```bash
   cp config.example.db.toml config.db.toml   # 数据库种子（凭据、仓库、通知渠道）
   cp config.example.toml      config.toml     # 基础设施（state_home）
   mkdir -p data
   chown 100:101 data                          # 镜像以 uid 100 / gid 101 运行
   ```

2. 编辑 `config.db.toml` —— 至少设置 `[core.github].gh_token`、`[core.analysis]`，并添加一个 `[[repo.repos]]` 条目（详见[配置说明](#配置说明)）。

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
         - PROGRESS_SCHEDULE_CRON=0 8 * * *   # 每天 08:00 运行
       restart: unless-stopped
   ```

4. 启动容器，然后访问 `http://<你的主机>:5000`：

   ```bash
   docker compose up -d
   docker compose logs -f
   ```

   设置 `PROGRESS_SCHEDULE_CRON` 后，Progress 会在启动时运行一次流水线，然后按 cron 调度执行。不设置则手动触发：`docker compose exec progress progress run`。

## 在宿主机上运行

1. 克隆项目：

   ```bash
   git clone https://github.com/jukanntenn/progress.git
   cd progress
   ```

2. 安装依赖（使用 [uv](https://github.com/astral-sh/uv)）：

   ```bash
   uv sync --extra dev
   ```

3. 准备配置文件（同上，复制两个示例文件并编辑 `config.db.toml`）。

4. 运行流水线或启动 API 服务：

   ```bash
   uv run progress run  -c config.toml        # 运行完整跟踪流水线
   uv run progress serve -c config.toml       # 启动 API 服务（默认 0.0.0.0:8000）
   ```

   首次运行时会自动克隆配置的仓库、计算 diff、进行 AI 分析并生成报告。`run` 还支持 `--trackers-only` 只运行跟踪类集成（跳过报告/通知）。

5. 定期运行可借助系统 crontab（见[定时任务](#定时任务)），或在容器内使用 `PROGRESS_SCHEDULE_CRON`。

## 配置说明

Progress 采用**双文件**配置模型：

- **`config.toml`**（Ansible 级）—— 仅基础设施，目前只含 `state_home`（决定 `progress.db`、日志、克隆仓库的存放位置）。见 `config.example.toml`。
- **`config.db.toml`**（数据库种子）—— 应用配置，启动时导入数据库。复制 `config.example.db.toml` 作为种子。首次运行后**数据库即为唯一事实来源** —— 通过 **Web UI**（`/config` 页面）或 API（`PUT /api/v1/config/{section}`）在线修改，或编辑 `config.db.toml` 后重启重新导入。

优先级：**数据库 > 种子（`config.db.toml`）> 代码默认值**；环境变量覆盖（`PROGRESS_` 前缀）在种子导入时叠加生效。凭据缺失（`gh_token`、`api_key`）会优雅降级 —— 对应集成被禁用并告警，而非崩溃（零配置）。

完整模型见 [docs/config.md](docs/config.md)。一个最小化的 `config.db.toml` 种子：

```toml
[core]
language = "en"
timezone = "UTC"

[core.github]
gh_token = "ghp_xxxxxxxxxxxxxxxxxxxx"        # 留空 -> GitHub 跟踪禁用

[core.analysis]
provider = "anthropic"                        # 任意 Pydantic AI 提供方
model = "claude-sonnet-4"
api_key = "sk-xxxxxxxxxxxxxxxx"               # 留空 -> AI 分析禁用

[[core.notification.channels]]
type = "console"                              # console | email | feishu
enabled = true

[repo]
first_run_lookback_commits = 3

[[repo.repos]]
url = "vitejs/vite"                           # "owner/repo"、HTTPS 或 SSH URL
branch = "main"
enabled = true
```

### 配置项说明

| 配置项 | 说明 |
| --- | --- |
| `[core].language` | 报告/通知/UI 语言，默认 `en` |
| `[core].timezone` | IANA 时区，默认 `UTC` |
| `[core.github].gh_token` | GitHub token（SecretStr），留空禁用 GitHub 跟踪 |
| `[core.analysis].provider` | Pydantic AI 提供方，例如 `anthropic` / `openai` |
| `[core.analysis].model` | 模型名，例如 `claude-sonnet-4`，留空用提供方默认 |
| `[core.analysis].api_key` | API key（SecretStr），留空禁用 AI 分析（截断兜底） |
| `[core.analysis].base_url` | OpenAI 兼容端点；留空用提供方默认 |
| `[core.analysis].language` | AI 输出语言（独立于顶层 `language`） |
| `[core.markpost].enabled` | 是否启用 Markpost 上传，默认 `false` |
| `[core.markpost].url` | Markpost 发布 URL（SecretStr） |
| `[core.markpost].max_batch_size` | 单批次最大字节数，默认 1048576 |
| `[[core.notification.channels]]` | 通知通道（`type` 判别联合：`console` / `email` / `feishu`） |
| `[core.observability.bugsink].dsn` | Bugsink DSN（SecretStr），留空禁用错误采集 |
| `[core.web].base_url` | 报告反向链接的公网 base URL |
| `[repo].first_run_lookback_commits` | 首次运行某仓库时回溯的提交数 |
| `[[repo.repos]]` | 仓库列表（`url` / `branch` / `enabled`） |
| `[[repo.owners]]` | 组织/用户发现（`type` = `organization` \| `user`，`name`） |
| `[[changelog.trackers]]` | Changelog 跟踪源（`name` / `url` / `parser_type` / `enabled`） |
| `[proposal].trackers` | 启用的提案类型，例如 `["eip", "erc", "pep", "rfc", "dep"]` |
| `[feed].base_url` | Miniflux 实例 URL，留空禁用 feed 集成 |
| `[feed].api_key` | Miniflux API key（SecretStr） |

所有 `SecretStr` 字段（`gh_token`、`api_key`、`password`、`webhook_url`、`dsn`、`markpost.url`）在文件中写真实值，Web UI 与 `GET /api/v1/config` 会自动序列化为 `**********`。

### 环境变量

使用 `PROGRESS_` 前缀覆盖任意配置值，嵌套层级用双下划线 `__` 分隔：

```bash
# 注意：前缀是 PROGRESS_（单个下划线），__ 只是节与键之间的分隔符
export PROGRESS_CORE__TIMEZONE="Asia/Shanghai"
export PROGRESS_CORE__GITHUB__GH_TOKEN="ghp_your_token_here"
export PROGRESS_CORE__ANALYSIS__PROVIDER="openai"
export PROGRESS_CORE__ANALYSIS__API_KEY="sk-xxxx"
export PROGRESS_CORE__NOTIFICATION__CHANNELS='[{"type":"feishu","enabled":true,"webhook_url":"https://open.feishu.cn/..."}]'
export PROGRESS_STATE_HOME="/app/data"
```

在 Docker 部署中通过环境变量注入敏感信息尤其方便，可配合 `.env` 文件：

```yaml
# docker-compose.yml
services:
  progress:
    image: ghcr.io/jukanntenn/progress:latest
    environment:
      - PROGRESS_CORE__GITHUB__GH_TOKEN=${GH_TOKEN}
      - PROGRESS_CORE__ANALYSIS__API_KEY=${ANALYSIS_API_KEY}
      - PROGRESS_SCHEDULE_CRON=0 8 * * *
```

> 应用配置的环境变量仅在**首次种子写入**时生效；如需从文件重新导入，编辑 `config.db.toml` 后重启服务。基础设施配置（如 `PROGRESS_STATE_HOME`）则每次启动都按 **环境变量 > 配置文件 > 默认值** 解析。

## 定时任务

### 宿主机定时任务

使用系统 crontab：

```bash
crontab -e
# 每天早上 8 点运行
0 8 * * * cd /path/to/progress && uv run progress run -c config.toml
```

crontab 时间格式：

```text
┌───────────── 分钟 (0 - 59)
│ ┌───────────── 小时 (0 - 23)
│ │ ┌───────────── 日期 (1 - 31)
│ │ │ ┌───────────── 月份 (1 - 12)
│ │ │ │ ┌───────────── 星期 (0 - 7，周日为 0 或 7)
│ │ │ │ │
* * * * *
```

### Docker 定时任务

在容器中通过 `PROGRESS_SCHEDULE_CRON` 环境变量配置（supercronic 读取，s6-overlay 托管）：

```yaml
services:
  progress:
    image: ghcr.io/jukanntenn/progress:latest
    environment:
      - PROGRESS_SCHEDULE_CRON=0 8 * * *   # 每天 8:00 运行
    # ...其余配置同“快速开始”
```

修改后重启容器生效：`docker compose down && docker compose up -d`。

## Web 服务

容器在端口 `5000` 暴露 Web UI 与 JSON API：

| 路径 | 说明 |
| --- | --- |
| `/healthz`、`/readyz` | 存活/就绪探针（k8s 风格） |
| `/reports` | 聚合报告浏览（根路径 `/` 重定向到此） |
| `/reports/:id` | 单条报告完整内容 |
| `/integrations` | 各集成状态概览 |
| `/config` | 在线配置编辑器（写入数据库） |
| `/api/v1/version` | 版本信息（JSON） |
| `/api/v1/reports` | 报告列表与详情（JSON） |
| `/api/v1/integrations` | 集成状态（JSON） |
| `/api/v1/config` | 读取在线配置（JSON，只读） |
| `/api/v1/config/schema` | 配置模型的 JSON Schema |
| `PUT /api/v1/config/{section}` | 更新某个配置节 |
| `/api/v1/rss` | 最新报告的 RSS 订阅源 |

使用 RSS：复制 `http://<你的主机>:5000/api/v1/rss` 到任意 RSS 阅读器（Feedly、Inoreader、NetNewsWire 等）即可订阅。

## 开发

详见 [docs/development.md](docs/development.md)。要求：Python 3.12+ 配 [uv](https://github.com/astral-sh/uv)，前端需 Node 22+ 配 [pnpm](https://pnpm.io/) 11+。

本地质量门控（与 CI 一致）：

```bash
uv sync --extra dev
uv run ruff check && uv run ruff format --check
uv run ty check
uv run pytest -m "not e2e or (e2e and not feed)"

cd web && pnpm install && pnpm lint && pnpm typecheck && pnpm test && pnpm build
```

更多文档见 [`docs/`](docs/)：[config.md](docs/config.md)、[deployment.md](docs/deployment.md)、[development.md](docs/development.md)、[observability.md](docs/observability.md)、[testing.md](docs/testing.md)。
