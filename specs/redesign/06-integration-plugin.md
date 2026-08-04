# 06 · 插件体系(Integrations)

## 决策:统一 Integration Protocol + 注册表发现 + 自包含包

每个 integration(内置 repo/changelog/proposal/feed,或第三方)实现统一 `Integration` 协议,通过注册表发现,自包含(models + migrations + templates + locales + config)。核心对 integration 完全透明。

## 插件契约(Integration Protocol)

```python
# integrations/base.py
class Integration(Protocol):
    name: str  # 唯一标识(注册表 key / config 表 section 值)
    config_schema: type[BaseModel]  # 该插件的配置 Pydantic 模型(生成 JSON Schema)

    async def setup(self, ctx: Components) -> None:
        ...
        # 初始化:接收 DB engine、aiohttp session、AI agent 等共享依赖

    async def sync(self) -> SyncResult:
        ...
        # 配置→状态期望态同步:从 config 表读自己 section,更新自己的状态表 + GC

    async def run(self, *, concurrency: int = 1) -> RunResult:
        ...
        # 实际工作:拉取外部数据 + 比对状态 + AI 分析 + 持久化结果
        # concurrency: 并发度(默认 1 串行,等价于原各自串行实现)

    async def teardown(self) -> None:
        ...
        # 清理
```

### 4 钩子的职责分离

| 钩子 | 职责 | 不做什么 |
|---|---|---|
| `setup` | 初始化(接收共享依赖) | 不做业务 |
| `sync` | 配置→状态期望态同步(含 GC) | 不拉取外部数据 |
| `run` | 拉取+分析+持久化 | 不管配置同步 |
| `teardown` | 清理 | — |

### `run` 的 `concurrency` 参数

**第一性原理**:并发是 integration 的执行策略,不是配置属性——同一种业务在不同场景(交互式 run vs 定时任务)可能需要不同并发度。放在 `Components`(全局共享)不合适,因为不同 integration 可能需要不同并发。放在 `run` 参数上最自然。

- 默认值 1,等价于原串行实现。
- `core.py` 从 `cfg.analysis.concurrency` 读取,透传给每个 integration 的 `run`。
- **AI 调用的全局序列化**:AI 请求受全局信号量约束(`AI_CONCURRENCY=1`,见 spec 08),所有 AI 分析被序列化。因此 `concurrency` 主要对**非 AI 工作**(git 操作、HTTP 拉取、GitHub API 调用)生效;对 AI 密集的 integration(repo/proposal),调大并发不会提升 AI 分析吞吐量。

### sync 的触发时机(明确决策)

**sync 只在 `run` 流程开始时执行**(`core.py` 里 `setup → sync → run → teardown` 的固定顺序),不在 config 修改时立即触发。

这是有意的设计,理由:
- **config 表是用户的意图表达**,对用户可见、可编辑(通过 `GET/PUT /api/v1/config`)。
- **状态表是程序内部的 checkpoint**(如 `last_seen_commit`、`last_seen_version`),不对用户暴露——它们是程序下次运行时自己消费的实现细节。
- 用户通过 Web UI 修改 config 后,状态表不会立即同步;同步发生在下次 `run` 命令时。这保持 `PUT /config/{section}` 的简洁(只写 config)和 `run` 的完整性(sync+run 是一个原子业务流程)。
- `PUT /config/{section}` 成功后只写 DB config 表,**不调用** integration 的 `sync()`。

### sync 与 run 分离的理由

当前 `check_all()` 把"配置同步"和"实际追踪"混在一起。分离后职责清晰:
- `sync` 是"配置驱动的期望态 upsert"(把 config 里的 repos 同步到 Repository 状态表,删配置中不再存在的)。
- `run` 是"实际工作"(拉 commit、分析、生成报告)。

## 配置↔状态关联(插件自治)

**关键原则**:配置与状态的关联是**插件自己的逻辑**,核心不插手。

```python
# integrations/repo/tracker.py(插件自己的逻辑)
async def sync(self) -> SyncResult:
    repo_configs = await get_config("repo")["repos"]  # 从 config 表读自己 section
    existing = {r.url: r async for r in Repository.all()}
    for cfg in repo_configs:
        repo = existing.get(cfg.url)
        if repo is None:
            await Repository.create(url=cfg.url, branch=cfg.branch)  # 建状态行
        elif repo.branch != cfg.branch:
            repo.branch = cfg.branch
            await repo.save()  # 改配置→改状态
    # GC:配置删了的状态行(插件自己决定删不删)
    deleted = set(existing) - {c.url for c in repo_configs}
    for url in deleted:
        await existing[url].delete()
```

**核心不知道也不管这个关联**——它只在生命周期钩子调用 `await integration.sync()` 时把控制权交给插件。

### 决策理由(插件完全自治)

- 插件配置格式不定(可能嵌套/列表),核心不能强映射关系表。
- 关联策略(GC 是否删、改配置时如何更新状态)因插件而异,核心无法统一。
- 这正是 Django app 模型:每 app 自带 models + admin + migrations,核心只提供 app 注册表 + 启动钩子。

## 注册表与发现

### 注册机制(原生 importlib.metadata)

**用原生 `importlib.metadata.entry_points` + Protocol + `@register` 装饰器**(~20 行,无依赖)。

```python
# integrations/registry.py
_REGISTRY: dict[str, type[Integration]] = {}


def register(name: str):
    def deco(cls):
        _REGISTRY[name] = cls
        return cls

    return deco


def discover() -> dict[str, type[Integration]]:
    # 内置:@register 装饰器注册(import 时自动)
    # 第三方:importlib.metadata.entry_points(group="progress.integrations")
    ...
```

### 内置 integration

```python
# integrations/repo/__init__.py
@register("repo")
class RepoIntegration:
    name = "repo"
    config_schema = RepoConfig
    ...
```

### 第三方 integration

第三方包在 `pyproject.toml` 声明:
```toml
[project.entry-points."progress.integrations"]
my-tracker = "my_pkg.integration:MyIntegration"
```

### 决策理由(不用 pluggy/stevedore)

- pluggy/stevedore 都基于 `importlib.metadata`(~20 行能实现)。
- 我们场景是"每 integration 一个实现、无跨插件排序",Protocol + 装饰器 + entry_points 足够。
- pluggy 为"多实现同 hook + 排序"场景设计,对我们 overkill。

### 否掉的方案

| 方案 | 否掉理由 |
|---|---|
| pluggy | 功能全但更重;适合 pytest 式多 hook 实现 |
| stevedore | OpenStack 味,manager 类无实质增益 |
| 手动枚举(无 entry_points) | 第三方无法扩展,违背插件化 |

## 包结构(自包含,Django app 式)

```
src/progress/integrations/
├── __init__.py
├── base.py           # Integration Protocol + 共享基类 + Result 类型
├── registry.py       # @register + entry_points 发现
├── repo/
│   ├── __init__.py   # @register("repo") + Integration 实现
│   ├── config.py     # RepoConfig(Pydantic,插件配置 schema)
│   ├── models.py     # Repository/GitHubOwner(状态,fat model)
│   ├── migrations/   # 该插件的迁移
│   ├── templates/    # 该插件的报告模板
│   ├── locales/      # 该插件的翻译
│   ├── tracker.py    # 业务逻辑
│   └── ...
├── changelog/
├── proposal/
└── feed/
```

### 自包含要求

每个 integration **必须**自带:
- `config.py`:Pydantic 配置模型(生成 JSON Schema,注册到 schema 注册表)。
- `models.py`:状态模型(fat model,承担查询/业务方法,无 repository,呼应 03)。
- `migrations/`:自己的迁移(tortoise 每 app 一个 migrations/)。
- `templates/`:自己的报告模板(若生成报告)。
- `locales/`:自己的翻译(若含可翻译文本)。

## 标识符:`name`

`Integration.name` 是唯一标识符,贯穿:
- 注册表 dict 的 key
- `config` 表 `section` 列的值(`section="repo"`)
- entry_points 的 key
- schema 注册表的 key
- API 路径段(`/api/v1/integrations/{name}/status`)
- 日志/trace 属性值

**列名仍叫 `section`**(03 定),值取自 `Integration.name`。

### 命名决策

脑暴过 `id`/`key`/`slug`/`identifier`/`kind`/`domain`/`section`/`namespace`。

**选定 `name`**。理由:`name` 配合类名 `RepoIntegration` 已清晰;"唯一标识"语义由注册表单键约束保证,不必让属性名承担过重表达。过度追求"贴切"反而陷入纠结。

## 统一结果类型

各 integration 返回统一的 `RunResult` / `SyncResult`,报告层统一消费:

```python
# integrations/base.py
@dataclass
class ReportSection:
    title: str  # 报告段标题
    content: str = ""  # 预渲染兜底(模板渲染失败时用)
    payload: dict[str, Any] = field(default_factory=dict)  # 结构化数据,供模板按字段渲染


@dataclass
class RunResult:
    name: str  # integration name
    status: str  # "success" | "partial" | "failed"
    summary: str  # 人类可读摘要
    reports: list[ReportSection]  # 报告段(供 reports pipeline 消费)
    events: list[Event] = field(default_factory=list)  # 领域事件(供 notifications dispatcher 消费)
    errors: list[ProgressException]
```

替代当前各自 bespoke 的 `RepositoryReport`/`ChangelogCheckResult`/`ProposalReport`。

### `reports` 与 `events` 双通道(关键设计)

integration 产出两类东西,语义不同,走不同管道:

| 通道 | 类型 | 消费者 | 处理方式 |
|---|---|---|---|
| `reports` | `list[ReportSection]` | `cli/reports/pipeline` | 聚合渲染 + AI 加工(title/summary)+ 落库 + 可选 MarkPost |
| `events` | `list[Event]` | `cli/notifications/dispatcher` | 直接派发到通知通道(无 AI 加工) |

- **reports** 会被 AI 再加工(生成聚合 title/summary),适合"需要整体概览"的场景(repo commit/release 报告)。
- **events** 是原子的业务事实,直接渲染成通知 payload,适合"无需加工、立即触达"的场景(changelog 新版本、proposal 状态变化、discovered repo)。
- 一个 integration 可以同时产出两者(例如 repo 既产 reports 给 pipeline 聚合,又产 DiscoveredRepoEvent 给 dispatcher)。

### `ReportSection.payload` 字段

模板渲染需要结构化数据(如 `repository_report.j2` 需要 `releases`/`commit_messages` 等字段),但不同 integration 的 payload schema 不同。用 `dict[str, Any]` 承载,由各 integration 自己的模板约定字段名。

- 最小侵入设计:不强制泛型,不强制继承基类,各 integration 自治。
- 模板渲染时:`template.render(section=sec, result=result, **sec.payload)`(payload 字段展开为模板变量)。
- `content` 字段作为预渲染兜底——当模板渲染失败时使用。

### 决策理由

报告层(09)统一消费各 integration 的结果,不应为每种 integration 写适配。通知层(10)统一消费各 integration 的事件,也不应为每种 integration 写适配。

## 核心 core.py 调度

```python
# cli/core.py(见 05)
async def run(cfg) -> RunOutcome:
    async with lifespan(cfg) as ctx:
        integrations = [cls() for cls in discover().values()]
        for i in integrations:
            await i.setup(ctx)
        outcome = RunOutcome()
        for i in integrations:
            await i.sync()
            result = await i.run(concurrency=cfg.analysis.concurrency)
            outcome.add(i.name, result)
        # 报告管道:消费 reports(聚合渲染 + AI 加工)
        if not trackers_only:
            await run_reports(outcome, cfg, session=ctx.session)
        # 通知管道:消费 events(直接派发到通道)
        await run_notifications(outcome, cfg)
        for i in integrations:
            await i.teardown()
        return outcome
```

**核心对 integration 完全透明**:新增 integration 只需 `@register` + 实现 4 钩子,核心零改动。

### 报告管道与通知管道分离

- **报告管道**(`run_reports`):消费 `outcome.results[*].reports`,聚合渲染 + AI 生成 title/summary + 落库 + 可选 MarkPost 批量发布 + 派发 `ReportEvent` 到通知管道。详见 spec 09。
- **通知管道**(`run_notifications`):消费 `outcome` 里所有 integration 产出的 `events`,逐个派发到通知通道。报告管道自己也会产出一个 `ReportEvent` 加入通知管道。详见 spec 10。

两个管道独立运行,互不阻塞。

## DB 模型发现

tortoise 需在 `Tortoise.init(modules=...)` 列出所有 models 模块。插件 models 经 entry_points 发现后加入此列表(03 的 `tortoise_config.py` 同源处理)。

源码核实:`apps.py:45-52` `_discover_models` 接受 `ModuleType`(运行时加载的模块对象),无需静态字符串路径。

**约束**:`AppConfig.migrations` 必须是字符串(dotted path),`loader.py:45` 用 `import_module`(所以 entry_points integration 必须暴露可 import 的 migrations 包路径)。

## 删除清单

| 删除 | 理由 |
|---|---|
| `contrib/` 命名 | 改 `integrations/` 名实相符 |
| 各 `Manager`/`Tracker` bespoke 接口 | 统一 Integration Protocol |
| `contracts.py` 命名 | 改 `base.py`(社区主流,见 01) |
| 硬编码到 cli/orchestration/bootstrap | 改注册表发现 |
