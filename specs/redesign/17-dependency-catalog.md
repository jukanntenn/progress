# 17 · 依赖清单与选型理由

本文列出全部第三方库选型 + 选型理由 + 否掉的方案。每个选型都有源码核实或社区证据支撑(见各篇引用)。

## 后端依赖(Python)

### 核心

| 库 | 用途 | 选型理由 | 否掉方案 |
|---|---|---|---|
| **Python 3.12+** | 运行时 | asyncio、类型系统、zoneinfo | — |
| **fastapi[standard]** | Web 框架(含 uvicorn) | async、Pydantic 集成、OpenAPI 自动生成 | Flask(同步)、Litestar(生态小) |
| **typer** | CLI 框架 | 生态最大、用户选定 | Cyclopts(native async 但单维护者)、Fire(半休眠)、bare Click(boilerplate) |
| **tortoise-orm** | ORM | async、满足全部需求(类型/迁移/JSON/FastAPI)、全新设计零迁移包袱 | SQLAlchemy(重写成本无净收益)、SQLModel(pre-1.0 锁版本)、PonyORM/Peewee(无 async) |
| **aiosqlite** | SQLite 驱动 | tortoise async 后端 | — |

### 配置与校验

| 库 | 用途 | 选型理由 | 否掉方案 |
|---|---|---|---|
| **pydantic** | 数据模型/校验 | v2 主流、SecretStr、model_json_schema | — |
| **pydantic-settings** | 配置加载(env+TOML) | TomlConfigSettingsSource、settings_customise_sources | dotenv/dynaconf(冗余) |
| **tomlkit** | TOML 读写(注释保留) | round-trip 保注释(适合 Web 编辑写回文件) | tomli_w(只写不读、不保注释);stdlib tomllib 只读 |
| **jsonschema** | JSON Schema 校验(Draft 2020-12) | 插件配置应用侧校验(SQLite 无原生 schema 校验) | — |

### HTTP 与 Git

| 库 | 用途 | 选型理由 | 否掉方案 |
|---|---|---|---|
| **aiohttp** | HTTP 客户端(统一) | 活跃(505 commits/3 月);gidgethub 原生 adapter;OTel AioHttpClientInstrumentor | **httpx(停滞 19 月/issue 关闭/0 commits 3 月)**;httpx2(2 月龄生态未验证);requests(sync) |
| **gidgethub** | GitHub API | async-native、自动分页、限流追踪、sans-IO 可测 | PyGithub/github3.py(均 sync) |
| **tenacity** | 重试 | @retry 自动检测 async、wait_exponential_jitter | 手写 aretry(无 jitter、双份) |
| (stdlib asyncio) | 本地 git subprocess | 调研证实无 async-native git 库 | GitPython(sync+index.lock)、dulwich(sync)、pygit2(sync C) |

### AI

| 库 | 用途 | 选型理由 | 否掉方案 |
|---|---|---|---|
| **pydantic-ai** | AI 分析(结构化输出) | v2.10.0 稳定、output_type 强类型、多 provider、源头 schema 约束、TestModel 测试 | shell-out claude/codex CLI(用大炮打蚊子,抽取任务禁用 agent 能力);裸 SDK(手写更多);claude-agent-sdk(仍 agentic CLI) |
| **json-repair** | JSON 修复兜底 | 保稳定性(用户硬需求);Pydantic AI 无内置 repair | — |

### 报告/渲染

| 库 | 用途 | 选型理由 | 否掉方案 |
|---|---|---|---|
| **jinja2** | 模板引擎 | Python 标准、select_autoescape 安全默认 | — |
| **markdown-it-py** | Markdown→HTML | CommonMark、Google Assured OSS | mistune(也可)、python-markdown(无 sanitize) |
| **nh3** | HTML sanitize(bleach 继任) | bleach 官方废弃(2026-06-05);nh3 Rust/ammonia ~20× bleach | **bleach(废弃)**;lxml.html.clean(移出核心) |
| **feedgen** | RSS 生成 | Python 唯一完整生成器(无更好替代) | feedparser(只读) |

### i18n

| 库 | 用途 | 选型理由 | 否掉方案 |
|---|---|---|---|
| **babel**(dev) | gettext 提取(pybabel) | Python gettext 提取标准;DEFAULT_KEYWORDS 含 _ | 手维护 .po(漂移) |
| (stdlib gettext + ContextVar) | 运行时 i18n | async 正解(ContextVar > thread-local) | Fluent(场景不需要其表达力) |

### 通知

| 库 | 用途 | 选型理由 | 否掉方案 |
|---|---|---|---|
| **aiosmtplib** | email SMTP | async | — |
| (aiohttp) | feishu webhook | 已统一 aiohttp | Apprise(URL scheme 配置不一致 + sync 内部) |

### 可观测性

| 库 | 用途 | 选型理由 | 否掉方案 |
|---|---|---|---|
| **opentelemetry-api/sdk** | OTel 插桩 | 行业标准 | — |
| **opentelemetry-instrumentation-aiohttp-client** | aiohttp 插桩 | 覆盖 gidgethub + 所有 aiohttp 调用 | httpx instrumentation(httpx 停滞) |
| **opentelemetry-instrumentation-fastapi** | FastAPI 插桩 | 标准 | — |
| **opentelemetry-instrumentation-sqlite3** | SQLite 插桩 | 标准 | — |
| **opentelemetry-instrumentation-logging** | 日志插桩 | trace 注入 | — |
| **opentelemetry-exporter-otlp-proto-http** | OTLP 导出(可选) | 远端模式 | — |
| **opentelemetry-exporter-otlp-json-file** | 本地 JSONL 导出(默认) | 替代 Console hack | Console exporter(需 _ThreadSafeLineFile hack) |
| **structlog** | 结构化日志 | JSON 输出、ProcessorFormatter 桥接 stdlib、trace 注入 processor | stdlib logging dictConfig(手搓 trace 注入) |
| **sentry-sdk[fastapi]** | 错误捕获→Bugsink | traces_sample_rate=0(OTel 独占 trace)、错误带 trace_id | — |

### 测试(dev)

| 库 | 用途 | 选型理由 | 否掉方案 |
|---|---|---|---|
| **pytest** | 测试框架 | 标准 | — |
| **pytest-asyncio**(auto) | async 测试 | asyncio-only 项目推荐默认 | — |
| **pytest-mock** | mocker fixture | 替代裸 unittest.mock | — |
| **aioresponses** | aiohttp mock | 覆盖 gidgethub | responses(requests mock,⑦ 换 aiohttp 后无用) |
| **time-machine** | 时间 mock | C 级,快 | freezegun(慢) |
| **aiosmtpd** | 本地 SMTP server | email 测试 | — |
| **pytest-httpserver** | HTTP server mock | markpost/webhook 测试 | — |
| **httpx** | ASGITransport(API 测试) | async FastAPI 测试客户端 | 同步 TestClient(与 async lifespan 不兼容) |
| (pydantic-ai TestModel) | AI mock | 免真实 LLM API | — |
| **faker** | 测试数据 | 标准 | — |

## 前端依赖(TypeScript)

| 库 | 用途 | 选型理由 | 否掉方案 |
|---|---|---|---|
| **vite** | 构建 | SPA 标准打包器;RESTful 动态路由原生支持 | Next.js(不支持运行时动态路由静态导出) |
| **react 19** | UI 框架 | 主流 | — |
| **react-router**(v7/v8 Declarative) | 路由 | 惯例、迁移成本最低(v6 非破坏);Vite 官方不 endorse 任何 router,平级 peer | TanStack Router(类型安全更强但迁移成本高);Next.js(不支持 RESTful 静态) |
| **@tanstack/react-query** | 数据获取 | 标准 | SWR(项目已弃) |
| **openapi-typescript** | TS 类型生成 | 从 openapi.json 生成 runtime-free 类型 | 手写(漂移) |
| **openapi-fetch** | 类型化 fetch 客户端 | 轻量、零 runtime | hey-api(重)、orval |
| **openapi-react-query** | 类型化 hooks | 与 TanStack Query 集成 | — |
| **@base-ui/react** | 组件原语 | 用户硬性条件(MUI Base UI,前 Radix 团队) | Radix(shadcn 默认但用户选 Base UI) |
| **tailwindcss v4** | 样式 | CSS-first 主流 | 双系统(当前病根) |
| **react-hook-form** + **zod** | 表单 + 校验 | 标准 | — |
| **react-i18next** + **i18next** | i18n | 框架无关标准(Vite 无 Next 绑定) | next-intl(Next 绑定) |
| **react-markdown** + **remark-gfm** + **rehype-sanitize** | Markdown 客户端渲染 | 安全(allowlist) | dangerouslySetInnerHTML(XSS) |
| **vitest** + **@testing-library/react** + **msw** | 单元/组件测试 | 标准 | — |
| **playwright** | e2e | 标准 | — |
| **eslint 9 flat** + **typescript-eslint** + **prettier** + **prettier-plugin-tailwindcss** | lint/format | 标准 | — |

## 基础设施

| 库/工具 | 用途 | 选型理由 | 否掉方案 |
|---|---|---|---|
| **uv** | 包管理 | 速度、lockfile | pip |
| **Caddy** | 反代 + 静态 serve | 配置简、自动 HTTPS | Nginx(配置繁) |
| **s6-overlay** | 进程管理 | 容器多进程标准 | supervisor |
| **Docker** | 容器化 | 标准 | — |

## 关键否掉决策汇总(供回顾)

| 否掉的方案 | 否掉理由 | 篇 |
|---|---|---|
| Cyclopts(替 Typer) | 单维护者 bus factor | 05 |
| SQLAlchemy(替 tortoise) | 重写无净收益 | 03 |
| SQLModel | pre-1.0 锁版本 | 03 |
| httpx | 停滞 19 月/issue 关闭 | 07 |
| Apprise(统一通知) | URL scheme 与 Pydantic 配置不一致 | 10 |
| shell-out claude/codex CLI | 抽取任务用 agent 是浪费 | 08 |
| bleach | 官方废弃 | 09 |
| Next.js(前端) | 不支持运行时动态路由静态导出 | 13 |
| `output: "export"` + 查询参数 | 放弃 RESTful(硬约束) | 13 |
| Next + Node server | 3 进程 + 双重回环,性能优势用不上 | 13 |
| DB blob 存配置 | 反模式(漂移/明文/补偿代码) | 02 |
| 字段级 managed_by + mtime 仲裁 | 过度复杂,二分配置消除冲突 | 02 |
| Fluent i18n | 场景不需要其表达力 | 11 |
| Fluent | 同上 | 11 |
| 裸 stdlib logging | 手搓 trace 注入 | 04 |
| 隐式默认命令(裸跑=run) | 显示帮助更不意外 | 05 |

## 版本管理

- **不锁死版本**:用 `>=` 下限 + uv.lock 锁定具体版本。
- **pyproject.toml** 是声明源,**uv.lock** 是可复现锁定。
- **OTel 插桩包**用 `>=` 但注意与 API/SDK 版本兼容窗口(源码核实 0.64b0 对应 1.43.0)。
- **sentry-sdk** `>=2.60.0` 无上限(注意 OTLPIntegration 在 2.62.0+)。

## 依赖审计(实现时)

实现时跑 `uv tree` + 安全审计(`pip-audit` 或 `uv audit`),确保:
- 无已知漏洞依赖。
- 无重复依赖(不同版本冲突)。
- 无未使用依赖(删)。
