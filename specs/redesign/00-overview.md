# 00 · 全新设计总览

本目录是 `progress` 项目的**全新设计规范**。规范以"从零重新设计、彻底重构、追求最优"为目标,不保留任何历史包袱,不与现有实现兼容。

## 设计目标

`progress` 是一个 GitHub 多仓库项目追踪工具:追踪多个开源仓库的代码变化、运行 AI 分析、生成报告、发送通知,帮助用户跟进开源项目进展。

本次全新设计要达成的目标:

1. **结构清晰** —— 按领域高内聚组织,消除散乱扁平的模块堆叠。
2. **可扩展** —— 插件化架构,新增追踪类型(新的 integration)零改核心。
3. **类型安全** —— 全栈强类型,前后端契约自动生成、永不手写。
4. **安全** —— XSS 防护、密钥脱敏、容器加固、无应用层认证(信任网络边界)。
5. **可观测** —— 统一的可观测性栈(OTel + structlog + Bugsink),单一插桩层。
6. **可测试** —— 清晰的测试分层,核心入口可被 e2e 直调,免 subprocess。
7. **零配置** —— 合理默认值,缺失必要配置时功能降级而非报错,系统照常运行。
8. **社区标准** —— 选用社区广泛使用、持续维护的开源项目,拒绝重复造轮子。

## 设计原则

以下原则贯穿所有规范,任何具体决策都不得违背:

### P1 · 第一性原理优先
每个设计决策从"这个事物的本质是什么"出发,而非"现有实现怎么做"。不被现状束缚,追求最优。

### P2 · 约定优于配置 (Convention over Configuration)
遵循约定减少显式配置。仅在约定无法覆盖的差异点提供配置项。

### P3 · 零配置 (Zero Configuration)
系统应能在不提供任何配置的情况下启动(使用代码默认值)。缺失必要前提(如凭据)时,对应功能降级禁用 + 日志提醒,系统不报错退出。

### P4 · 代码常量归代码,动态配置归配置
用户几乎不会改的实现细节(超时、重试次数、阈值)是代码常量,不进配置。配置只装"用户意图、凭据、业务输入"。

### P5 · 高内聚低耦合
每个领域包自包含(models + migrations + templates + locales + config),对外通过明确接口暴露。插件完全自治。

### P6 · 单一真相源 (Single Source of Truth)
避免同一信息多处定义导致的漂移。例如:API 类型从 OpenAPI 生成(后端 Pydantic 模型是真相源),前端类型永不手写。

### P7 · YAGNI (You Aren't Gonna Need It)
不预先设计当前不需要的功能。例如:不预先加应用层认证(自托管工具信任网络边界),未来需要再加。

### P8 · 安全默认
所有安全相关默认值取最严格合理的选项。密钥自动脱敏,模板自动转义,markdown 自动 sanitize,容器非 root 运行。

## 技术栈全景

### 后端 (Python 3.12+)

| 关注点 | 选型 | 规范篇 |
|---|---|---|
| 语言/运行时 | Python 3.12+, asyncio | — |
| CLI 框架 | Typer | 05 |
| Web 框架 | FastAPI | 12 |
| ASGI server | uvicorn | 12, 14 |
| ORM | tortoise-orm (async) | 03 |
| 数据库 | SQLite + aiosqlite | 03 |
| 迁移 | tortoise 内置 migrations | 03 |
| 配置 | pydantic + pydantic-settings + tomlkit | 02 |
| 校验(JSON Schema) | jsonschema (Draft 2020-12) | 02, 06 |
| HTTP 客户端 | aiohttp (统一) | 07 |
| GitHub API | gidgethub (aiohttp adapter) | 07 |
| 本地 git | asyncio subprocess | 07 |
| AI 分析 | Pydantic AI + json_repair 兜底 | 08 |
| 重试 | tenacity | 07 |
| 模板引擎 | Jinja2 (select_autoescape) | 09 |
| Markdown 渲染 | markdown-it-py + nh3 sanitize | 09 |
| RSS | feedgen | 12 |
| i18n | stdlib gettext + ContextVar + Babel | 11 |
| 通知 | aiosmtplib (email) + aiohttp (webhook) | 10 |
| 可观测性 | OTel + structlog + sentry-sdk→Bugsink | 04 |
| 插件机制 | importlib.metadata entry_points + Protocol + @register | 06 |

### 前端 (TypeScript)

| 关注点 | 选型 | 规范篇 |
|---|---|---|
| 构建 | Vite | 13 |
| 框架 | React 19 | 13 |
| 路由 | React Router (Declarative mode, v7/v8) | 13 |
| 数据获取 | TanStack Query | 13 |
| API 类型 | openapi-typescript + openapi-fetch + openapi-react-query | 12, 13 |
| 组件原语 | @base-ui/react | 13 |
| 样式 | Tailwind CSS v4 | 13 |
| 表单 | React Hook Form + Zod | 13 |
| i18n | react-i18next | 13 |
| Markdown | react-markdown + remark-gfm + rehype-sanitize | 13 |
| 测试 | Vitest + Testing Library + msw + Playwright | 15 |
| Lint/Format | ESLint 9 flat + typescript-eslint + Prettier | 13 |

### 基础设施

| 关注点 | 选型 | 规范篇 |
|---|---|---|
| 容器 | Docker (2 进程: Caddy + uvicorn) | 14 |
| 反代/静态 serve | Caddy | 14 |
| 进程管理 | s6-overlay | 14 |
| 部署 | Ansible | (运维, 不在规范范围) |

## 规范导读

规范按依赖顺序组织,建议按序号阅读:

| 篇 | 主题 | 关键决策 |
|---|---|---|
| [01](01-project-structure.md) | 项目结构 | src-layout、对称入口包 `cli/`+`api/`、Django app 式 `integrations/` |
| [02](02-config-system.md) | 配置系统 | 三类配置、`state_home`、`config` 表 section+data、`config.db.toml` 种子约定、SecretStr、配置清单 |
| [03](03-database.md) | 数据库 | tortoise-orm、config 表、状态表、每 app 自带 migrations、CLI 配置同源、register_tortoise |
| [04](04-observability.md) | 可观测性 | 单一 OTel 插桩层、structlog+TimedRotatingFileHandler、Bugsink 仅错误、密钥统一脱敏 |
| [05](05-cli.md) | CLI/编排 | Typer、薄 CLI / 厚 `cli/core.py`、lifespan、`RunOutcome`、退出码 |
| [06](06-integration-plugin.md) | 插件体系 | Integration Protocol (setup/sync/run/teardown)、registry、entry_points、自包含包 |
| [07](07-git-http-clients.md) | Git/HTTP 客户端 | gidgethub、asyncio subprocess、统一 aiohttp、session 每入口点管 |
| [08](08-ai-analysis.md) | AI 分析 | Pydantic AI 结构化输出、json_repair 兜底、TestModel 测试 |
| [09](09-reports.md) | 报告生成 | 流水线拆解、Jinja2 autoescape、nh3 sanitize、feedgen |
| [10](10-notifications.md) | 通知 | Channel/Renderer/Dispatcher 正交、aiosmtplib、经典 TOML discriminated union |
| [11](11-i18n.md) | i18n | gettext+ContextVar、Babel 提取、多目录 locales、locale code 统一小写 |
| [12](12-api-server.md) | FastAPI 服务端 | app factory、lifespan、CORS 仅 dev、无认证、端点设计、openapi 静态导出 |
| [13](13-frontend.md) | 前端 | Vite+React Router、openapi 类型闭环、Base UI、react-i18next、安全 |
| [14](14-docker.md) | Docker | 2 进程、非 root、Caddy 静态 serve + SPA 回退、加固 |
| [15](15-testing.md) | 测试 | unit/component/api/e2e 四层、marker 分层、mock 策略、e2e 矩阵(golden path + 每 integration 包)、工具链 |
| [16](16-naming-conventions.md) | 命名规范 | 动词原形、集合复数、领域术语统一、消除同义词 |
| [17](17-dependency-catalog.md) | 依赖清单 | 所有第三方库选型 + 理由 + 否掉方案 |

## 规范的权威性

本规范是实现的**权威依据**:

- 规范记录**决策、决策理由、否掉的方案及否掉理由**。
- 规范包含**接口设计、规范说明**等设计内容,不含具体代码实现。
- 实现者依照规范实现,**没有自由选择余地,没有歧义**。
- 实现者按规范落地,不产生漂移。
- 如规范存在矛盾或遗漏,应**修订规范**,而非在实现中自行决定。

## 与现有实现的关系

本规范是**全新设计**。现有实现(`src/progress/`、`web/`、`tests/`、`e2e/`、`docker/` 等)将被**完全替换**,不保留兼容性。实现时按本规范从零构建。
