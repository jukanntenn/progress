# 01 · 项目结构

## 决策:src-layout + 对称入口包 + Django app 式插件包

项目采用 **Python src-layout**,后端代码在 `src/progress/`。顶层布局为 monorepo,前端 `web/` 独立、不进 Python 包。

### 核心结构原则:对称入口包

CLI 和 Web API 是同一个应用的**两个独立入口**,各自独立生命周期,互不依赖。它们只共享底层基础设施(`config/`、`db/`、`errors.py`、`observability/`、`utils/`)和业务领域包(`integrations/`、`reports/`、`notifications/`、`ai/`、`git/`)。

```
        ┌─────────────────────────────────────────┐
        │  共享底座 (config/db/errors/observability/utils) │
        │  共享业务 (integrations)                        │
        └──────────┬──────────────────┬─────────────┘
                   │                  │
        ┌──────────▼───────┐  ┌───────▼──────────┐
        │   cli/ (CLI入口)  │  │  api/ (HTTP入口)  │  ← 对称、互不 import
        │  - core.py 编排   │  │  - FastAPI routes │
        │  - reports/       │  │  - 自包含 lifespan│
        │  - notifications/ │  └──────────────────┘
        │  - ai/ git/       │
        └──────────────────┘
```

**分层规则(强制,无歧义)**:
- `cli/` 与 `api/` **互不 import**。
- 只 CLI 用的模块进 `cli/`(如 `reports/`、`notifications/`、`ai/`、`git/`)。
- 只 API 用的模块进 `api/`(如 `routes/`、`markdown.py`)。
- 两边都用的进共享层(`config/`、`db/`、`integrations/`、`observability/`、`utils/`)。

### 决策理由

- **CLI 与 API 几乎无交集**:审计证实 API 只读已落库数据 + 配置 CRUD,**从不触发追踪**;追踪/分析/报告生成是 CLI 独有的后台批处理。强行共享一个大组合根会让 API 拖进 CLI 的编排逻辑(反之亦然)。
- **两个入口各自独立起服务**:API 用 `uvicorn progress.api.main:app`,CLI 用 `progress run`,各自管理 DB + 可观测性生命周期。
- **对称结构**避免"哪个入口是主"的歧义。

### 否掉的方案

| 方案 | 否掉理由 |
|---|---|
| 共享一个顶层 `app.py` 组合根统领 CLI+API | API 不需要 CLI 的编排逻辑(repo_manager/proposal_tracker 等),组合根返回的 5 元组 API 几乎不用(审计证实当前 `bootstrap.initialize_components` 就是此问题) |
| CLI 与 API 共用编排入口 | 两者生命周期不同(CLI 短命一次性、API 常驻),编排逻辑无共享价值 |
| `contrib/` 命名 | 误导:暗示"可选/第三方",实则全部硬编码。改用 `integrations/` 名实相符 |

## 完整目录结构

```
progress/
├── pyproject.toml                  # uv 单一依赖源(删 requirements.txt)
├── uv.lock
├── alembic.ini                     # 不使用(改用 tortoise 内置迁移,见 03)
├── babel.cfg                       # gettext 提取配置(见 11)
├── config.example.toml             # 唯一示例配置(Ansible 类)
├── README.md / README_zh.md
│
├── src/progress/                   # ── Python 后端(src-layout)──
│   ├── __init__.py                 # __version__ + 受控 __all__
│   ├── __main__.py                 # python -m progress 支持
│   ├── errors.py                   # 结构化异常层级(带上下文)
│   │
│   ├── config/                     # ── 共享:配置系统(见 02)──
│   │   ├── __init__.py             # 公共门面(导出 Config)
│   │   ├── root.py                 # 顶层项目级配置聚合根
│   │   ├── loader.py               # 分层 sources 加载
│   │   └── schema.py               # JSON schema 导出
│   │
│   ├── db/                         # ── 共享:数据层基础设施(见 03)──
│   │   ├── __init__.py             # engine + session + 初始化
│   │   ├── base.py                 # BaseModel + 通用 Mixin
│   │   ├── tortoise_config.py      # TORTOISE_ORM dict(CLI 与运行时同源)
│   │   └── models/                 # 核心状态模型(Report/Batch)
│   │
│   ├── integrations/               # ── 共享:业务插件包(见 06)──
│   │   ├── __init__.py
│   │   ├── base.py                 # Integration Protocol + 共享基类
│   │   ├── registry.py             # @register + entry_points 发现
│   │   ├── repo/                   # 每个 integration 自包含
│   │   │   ├── __init__.py         # @register("repo")
│   │   │   ├── config.py           # RepoConfig(Pydantic,插件配置)
│   │   │   ├── models.py           # 状态模型(fat model,见 03)
│   │   │   ├── migrations/         # 该插件自己的迁移
│   │   │   ├── templates/          # 该插件自己的报告模板
│   │   │   ├── locales/            # 该插件自己的翻译
│   │   │   ├── tracker.py          # 业务逻辑
│   │   │   └── ...
│   │   ├── changelog/
│   │   └── proposal/
│   │
│   ├── observability/              # ── 共享:可观测性(见 04)──
│   │   ├── __init__.py             # setup/shutdown + 公共 API
│   │   ├── logging.py              # structlog 配置
│   │   ├── telemetry.py            # OTel Provider/exporter
│   │   ├── scrub.py                # 统一密钥脱敏
│   │   └── metrics.py              # 业务指标 + 装饰器
│   │
│   ├── utils/                      # ── 共享:纯工具函数(参考 Django)──
│   │   ├── __init__.py
│   │   ├── http.py                 # aiohttp session 工厂 + tenacity 重试
│   │   ├── templating.py           # Jinja2 引擎工厂(autoescape)
│   │   ├── markdown.py             # markdown-it-py + nh3 sanitize
│   │   ├── timezone.py             # tz 工具
│   │   ├── text.py                 # 文本工具
│   │   └── i18n.py                 # gettext + ContextVar locale
│   │
│   ├── cli/                        # ── CLI 入口包(与 api/ 对称)──
│   │   ├── __init__.py             # typer app + 命令定义(薄)
│   │   ├── core.py                 # ★ run_*() 业务编排入口(厚,e2e 直调)
│   │   ├── lifespan.py             # @asynccontextmanager(CLI 进程生命周期)
│   │   ├── outcome.py              # RunOutcome 结构化结果
│   │   ├── reports/                # 报告生成(只 CLI 用,见 09)
│   │   │   ├── pipeline.py
│   │   │   ├── models.py
│   │   │   └── templates/reports/
│   │   ├── notifications/          # 通知(只 CLI 用,见 10)
│   │   │   ├── base.py
│   │   │   ├── renderer.py
│   │   │   ├── dispatcher.py
│   │   │   ├── events.py
│   │   │   ├── config.py
│   │   │   ├── channels/{email,feishu,console}.py
│   │   │   └── templates/
│   │   ├── ai/                     # AI 分析(只 CLI 用,见 08)
│   │   │   ├── agent.py
│   │   │   └── prompts/
│   │   └── git/                    # git/github 客户端(只 CLI 用,见 07)
│   │       ├── github.py
│   │       ├── local.py
│   │       └── url.py
│   │
│   └── api/                        # ── FastAPI 入口包(与 cli/ 对称)──
│       ├── __init__.py             # create_app + lifespan + 中间件装配
│       ├── main.py                 # app = create_app()(ASGI 入口)
│       ├── routes/                 # 端点(见 12)
│       ├── deps.py                 # Depends:get_session/get_config
│       ├── middleware.py           # CORS(dev)/GZip/Secure/CorrelationId
│       ├── errors.py               # 异常→HTTP 映射 + 统一错误信封
│       ├── schemas.py              # 共享 Pydantic response models
│       └── markdown.py             # markdown 渲染(只 API 用)
│
├── web/                            # ── 前端(顶层独立,不进 Python 包,见 13)──
│                                   #   Vite + React + React Router SPA
├── tests/                          # 单元/component/api 测试(见 15)
│   ├── unit/
│   ├── component/
│   └── api/
├── e2e/                            # 端到端测试(直调 cli/core.run_*)
├── docker/                         # 容器化(见 14)
│   ├── Dockerfile
│   ├── docker-compose.yml
│   ├── Caddyfile
│   └── s6/
├── devops/                         # 部署运维
│   ├── ansible/                    # 现有,保留
│   └── dev.py                      # 本地开发启动器
├── data/                           # 运行时产物(gitignore)
├── scripts/                        # 辅助脚本
│   ├── export_openapi.py           # 导出 openapi.json(见 12)
│   ├── makemessages.py             # 提取可翻译字符串 → locales/*.pot + 更新 .po
│   └── compile_messages.py         # 编译 *.po → *.mo
└── docs/                           # 合并后的单一文档树
```

## 关键归属决策(逐项说明)

### `cli/` 内的模块(只 CLI 用)

| 模块 | 归 `cli/` 的理由 |
|---|---|
| `reports/` | 报告生成链路(追踪后聚合+AI 标题+发布+通知)只 CLI 触发,API 只读已落库 Report 行(审计证实 API 不 import reporting) |
| `notifications/` | 通知由报告/提案事件触发,API 不发通知 |
| `ai/` | AI 分析在追踪链路内,只 CLI 用 |
| `git/` | gidgethub + 本地 git 在追踪链路内,只 CLI 用 |

### `api/` 内的模块(只 API 用)

| 模块 | 归 `api/` 的理由 |
|---|---|
| `routes/` | FastAPI 端点专属 |
| `markdown.py` | 只 API 在请求时渲染 markdown,CLI 不渲染 |
| `middleware.py` | CORS/GZip/安全头是 HTTP 专属 |

### 共享层

| 模块 | 共享理由 |
|---|---|
| `config/` | CLI 和 API 都加载配置 |
| `db/` | CLI 写追踪结果,API 读报告/读写配置,都访问 DB |
| `integrations/` | CLI 通过 integration 写追踪,API 读 integration 模型 + 状态 |
| `observability/` | 两个入口各自起自己的可观测性 |
| `utils/` | 纯工具函数,两边都用 |

## `integrations/` 命名(决策记录)

业务插件包命名脑暴过 `contrib`/`plugins`/`trackers`/`extensions`/`modules`/`apps`/`integrations`。

**选定 `integrations/`**。理由:
- 精准表达"把 GitHub repo / changelog / proposal 这些外部数据源集成为可追踪单元"的本质。
- "integration"在可观测/追踪领域是标准词(GitHub integration、Slack integration)。
- 不与 Python `module` 词义重叠(否掉 `modules`)。
- 不暗示"可选/第三方"(否掉 `contrib`)。
- 不过窄(否掉 `trackers`,未来加非 tracker 类插件会别扭)。

### `integrations/base.py` 命名(决策记录)

抽象接口模块命名脑暴过 `contracts`/`base`/`abc`/`types`/`interfaces`/`protocols`/`core`。

**选定 `base.py`**。理由:
- Python 社区最主流、零歧义(Django/SQLAlchemy/FastAPI/httpx 通行)。
- 与现有代码一致(当前已有 `notification/base.py`、`ai/analyzers/base.py`)。
- 不撞名(`core.py` 已用于 CLI 编排;`types.py` 已用于 ai;`abc.py` 与 stdlib 同名)。
- 适合混合 ABC + Protocol。

## 删除清单(全新设计,历史包袱全部删除)

以下现有文件/目录在全新设计中**彻底删除**(不保留、不兼容):

| 删除项 | 理由 |
|---|---|
| `src/progress/web/` | 旧 Vite+React18+SWR 副本,前端统一到顶层 `web/`(Vite 重写) |
| `requirements.txt` | uv.lock 是唯一真相源 |
| `config.toml`(根目录被追踪的) | 与 gitignore 矛盾,且新版配置分层见 02 |
| `src/progress/storages/` | 生产死代码(审计证实零生产调用) |
| `src/progress/orchestration.py` | CLI 副本,并入 `cli/core.py` |
| `src/progress/bootstrap.py` | 无类型 5 元组,并入 `cli/lifespan.py` |
| `src/progress/config_store.py` | DB blob 反模式,新版配置见 02 |
| `src/progress/publish.py` | 并入 `cli/reports/` |
| `src/progress/reporting.py` | God 函数,拆解进 `cli/reports/pipeline.py` |
| `src/progress/consts.py` | 杂物抽屉,常量归各领域 |
| `specs/` 下的旧文档 | 替换为 `specs/redesign/` |
| `PLAN.md` / `wiki/` | 设计残留 |

## devops/ 与 data/ 的说明

- **`devops/`**:保留现有 `ansible/`(部署编排)和 `dev.py`(本地开发启动器)。Ansible 模板随配置系统(02)和 Docker(14)更新。
- **`data/`**:运行时产物(`progress.db`、`logs/`、`repos/`、`observability/`),**全部 gitignore**。由 `state_home` 配置项派生(见 02)。

## 文档单一来源

合并现有 `docs/` 与 `guides/` 为单一 `docs/` 文档树,消除双文档树漂移。`docs/` 内按主题组织(development、deployment、configuration 等)。
