# 开发指南

[English](development.md) | 中文

## 前置条件

| 工具              | 版本   | 说明                                  | 安装                                                                                                |
| ----------------- | ------ | ------------------------------------- | --------------------------------------------------------------------------------------------------- |
| Python            | 3.12+  | 后端语言                              | [python.org/downloads](https://www.python.org/downloads/)                                           |
| uv                | 0.9+   | Python 包／项目管理器                 | [docs.astral.sh/uv](https://docs.astral.sh/uv/getting-started/installation/)                        |
| Node.js           | 22+    | 前端运行时                            | [nodejs.org](https://nodejs.org/)                                                                   |
| pnpm              | 11+    | 前端包管理器                          | [pnpm.io/installation](https://pnpm.io/installation/)                                               |
| prek              | latest | Git pre-commit 钩子（ruff/ty/eslint） | `uv tool install prek`（[j178/prek](https://github.com/j178/prek)）                                  |
| GitHub CLI (`gh`) | latest | 初次克隆仓库                          | [cli.github.com](https://cli.github.com/)                                                            |

## 快速开始

### 安装依赖

```bash
uv sync --extra dev   # backend (includes dev/test tooling)
cd web && pnpm install && cd ..   # frontend
prek install          # git pre-commit hooks (once per clone)
```

### 方式 1 —— VS Code 任务（推荐）

项目自带 `.vscode/tasks.json`。打开命令面板（`Ctrl+Shift+P`）→ **Tasks: Run Task** → 任选其一：

- **Start All** —— 并行运行后端与前端
- **Start Backend** —— 在端口 8000 运行 `uv run fastapi dev`（热重载）
- **Start Frontend** —— 在 `web/` 运行 `pnpm dev`（Vite HMR），端口 5173

### 方式 2 —— 手动

**后端**（FastAPI，热重载）：

```bash
uv run fastapi dev
```

**前端**（Vite HMR）：

```bash
cd web
pnpm dev
```

Vite 开发服务器在 [http://localhost:5173](http://localhost:5173) 上运行，并把 `/api/*`、`/healthz`、`/readyz` 代理到位于 `http://127.0.0.1:8000` 的后端（见 `web/vite.config.ts`）。

> 本地开发无需 `config.toml`。后端从 `PROGRESS_STATE_HOME` 环境变量读取 `state_home`（默认为相对 cwd 的 `"data"`）。VS Code 任务会把 `PROGRESS_STATE_HOME` 设为 `${workspaceFolder}/data`。

### 调试（VS Code）

`.vscode/launch.json` 提供 **FastAPI (debug)** 配置：按 F5 即可在 debugpy 下启动 uvicorn，支持断点与 `--reload`。另有一个 **Attach** 配置，用于连接 5678 端口上的 debugpy 会话。

## Lint 与格式化

```bash
uv run ruff check .       # backend linter
uv run ruff format .      # backend formatter
uv run ty check           # backend type checker
prek run --all-files      # everything (ruff + ty + eslint + prettier + hygiene)
```

前端：

```bash
cd web
pnpm lint                 # ESLint
pnpm format               # Prettier
pnpm typecheck            # tsc --noEmit
```

## 运行测试

**后端：**

```bash
uv run pytest -v                          # all tests
uv run pytest tests/test_repo.py -v       # single file
```

**前端：**

```bash
cd web
pnpm test                 # Vitest, single run (CI)
pnpm test:watch           # Vitest in watch mode
```

**端到端（Playwright，需要 Docker）：**

```bash
docker compose -f docker/docker-compose.local.yml up -d --build --wait
cd web/e2e && pnpm install && pnpm exec playwright install chromium && pnpm test
docker compose -f docker/docker-compose.local.yml down -v
```

测试分层约定见 [docs/testing.zh.md](testing.zh.md)。

## 配置

本地开发**无需** `config.toml`。`state_home` 取自 `PROGRESS_STATE_HOME` 环境变量（由 VS Code 任务设置，默认 `"data"`）。

应用配置（语言、凭据、业务调参）存于数据库的 `config` 表，通过 Web UI（`/config`）或 `PUT /api/v1/config/{section}` 编辑。若配置旁存在 `config.db.toml` 种子文件，则每次启动都会重新导入。

环境变量覆盖以 `PROGRESS_` 为前缀、`__` 表示嵌套：

```bash
PROGRESS_STATE_HOME="/app/data"
PROGRESS_TIMEZONE="Asia/Shanghai"
PROGRESS_LANGUAGE="en"
PROGRESS_GITHUB__GH_TOKEN="ghp_your_token_here"
```

完整配置模型见 [docs/config.zh.md](config.zh.md)，运行时／Docker 配置见 [docs/deployment.zh.md](deployment.zh.md)。

## 数据库迁移

见 [docs/migrations.zh.md](migrations.zh.md)。`scripts/migration.py` 包装脚本覆盖生成／应用／预览／回滚／漂移检查。

## 漂移检查

`scripts/check_drift.py` 是 CI 全部漂移／回归检查的单一真源。推送前先在本地运行，提前抓住 CI 会抓的问题：本地与 CI 调用同一脚本，两条路径因此绝不会漂移。

```bash
uv run python scripts/check_drift.py
```

它运行 CI `drift-checks` 作业的七项检查，每项各带横幅与 `[OK]`/`[FAIL]` 汇总：

1. **deptry** —— 已声明未使用／已使用未声明的依赖。
2. **import-linter** —— 禁止的跨层导入（[tool.importlinter]）。
3. **OpenAPI 漂移** —— `web/openapi.json` 与 FastAPI 实际产物一致。
4. **前端类型漂移** —— `web/src/api/schema.ts` 与 `openapi.json` 一致。
5. **i18n .pot 漂移** —— `src/progress/locales/progress.pot` 与新提取的字符串一致（POT-Creation-Date 已剥离 —— 非确定性字段）。
6. **i18n catalog lint** —— 无 fuzzy、空或过期的 `.po` 条目。
7. **迁移漂移** —— 每个模型变更都有配套迁移文件。

前置条件：`uv sync --extra dev` 与 `cd web && pnpm install`（后者服务于前端类型漂移检查）。**不**要求干净工作树：检查针对 `HEAD` 做 diff，未提交的源码改动会呈现为漂移（有意为之；要隔离单项检查，先提交或 stash）。

OpenAPI 与 `.pot` 检查运行后会把新生成的产物留在磁盘上（与 CI 行为一致）。若这次重新生成本就是预期更新，将其重新提交；否则用 `git checkout -- <path>` 丢弃。

## CLI

```bash
uv run progress run -c config.toml       # run the full pipeline
uv run progress serve -c config.toml     # serve the API
```

## 国际化

```bash
uv run python scripts/makemessages.py      # extract strings → locales/*.pot + update .po
uv run python scripts/compile_messages.py  # compile *.po → *.mo
```

细节见 [specs/redesign/11-i18n.md](../specs/redesign/11-i18n.md)。

## 可观测性

OpenTelemetry 追踪与指标导出到本地 JSON-Lines 文件，崩溃转发到 Bugsink（Sentry 兼容）服务器。在数据库 `config` 表的 `[observability]` 段配置。

搭建步骤见 [docs/observability.zh.md](observability.zh.md)。
