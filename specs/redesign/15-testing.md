# 15 · 测试

## 决策

三层测试结构(unit/component/e2e);API 层(FastAPI routes)并入 component(同用真 SQLite + httpx ASGITransport,只是入口不同);e2e 直调 `core.run()` 免 subprocess;mock 按 boundary 选(不按方便);每个 integration 自带完整验收清单(`specs/integrations/*`),e2e 只测"契约 + 跨 integration 协同";CI 与 drift 检查由独立 CI 规范承担,不在本 spec。

## 1. 三层测试结构

```
tests/
├── unit/          # 单元测试(纯函数/单类,注入 fake,无 IO,毫秒级)
├── component/     # 组件测试(多模块协作 + 真 SQLite;含 FastAPI route 测试)
└── e2e/           # 端到端(core.run 全流程,真实外部服务)
```

### 1.1 命名决策:component(替代 integration)

`integration` 与 `integrations/`(插件包,spec 06)撞概念。选 **`component`**(社区标准词,Spring/component testing;对应测试金字塔;不撞名)。

否掉 `integration` 的理由:撞 `integrations/`(插件包)概念,易混淆。

### 1.2 分层原则

| 层 | 职责 | 速度 |
|---|---|---|
| **unit** | 纯函数 / 单类,注入 fake,无 IO(parser、normalize、should_notify、模板选择、URL 规范化、状态机判断等) | 毫秒级 |
| **component** | 多模块协作 + 真 SQLite,测 integration 内部 `setup/sync/run` 各阶段;**含 FastAPI route 全流程**(httpx ASGITransport,见 §4);可任意 mock | 中等 |
| **e2e** | 通过真实 `cli/core.run()` 跑 integration ↔ core.run 的契约 + 跨 integration 协同 | 较慢 |

**为何 API 不单列一层**:FastAPI route 测试与 component 测试用同一套基础设施(真 SQLite tmp 文件、httpx ASGITransport、共享 `app_client`/`db_with_reports` 等 fixture,见 §4),仅入口不同(HTTP layer vs integration 内部方法)。单列一层会强制 `tests/api/` 与 `tests/component/` 两份 conftest 重复维护 fixture。并入 component 后,fixture 集中在 `tests/component/conftest.py`,route 测试与 integration 测试共享同一套 DB/client fixture。

**e2e 与 component 的边界**:每个 integration 的 spec(`specs/integrations/<name>.md`)自带完整验收清单("测试矩阵"章节),覆盖 unit/component/e2e 全层。spec 15 不复述这些清单——它只声明**分层原则**和 **e2e 层的筛选结果**(见 §2.5/§2.6/§2.7)。读者从 integration spec 的"测试矩阵"中,按 spec 15 的分层原则自行判断每条验收属于哪一层。

### 1.3 marker 分层执行

三个 layer marker:`unit` / `component` / `e2e`,加一个特殊 marker:`feed`(feed e2e 需 Docker,见 §2.8)。在 `pyproject.toml` 的 `[tool.pytest.ini_options].markers` 注册。

**自动打标**:根 `conftest.py` 的 `pytest_collection_modifyitems` 钩子按测试文件所在目录路径自动添加 marker,case 文件**不需要**手写 `@pytest.mark.xxx`:

```python
# conftest.py(根级)
def pytest_collection_modifyitems(items):
    for item in items:
        path = str(item.fspath)
        if "/tests/e2e/" in path or path.startswith("tests/e2e/"):
            item.add_marker(pytest.mark.e2e)
        elif "/tests/unit/" in path:
            item.add_marker(pytest.mark.unit)
        elif "/tests/component/" in path:
            item.add_marker(pytest.mark.component)
```

执行示例:
- `uv run pytest -m unit` —— 只跑 unit 层
- `uv run pytest -m "not e2e"` —— 排除 e2e(本地快速跑)
- `uv run pytest -m e2e` —— 只跑 e2e

目录路径过滤(`uv run pytest tests/unit`)仍然有效,marker 是补充而非替代。

## 2. e2e 测试

### 2.1 直调 core.run(免 subprocess)

**e2e 直调 `cli/core.run()`**,免 subprocess、免 monkeypatch(呼应 spec 05 薄 CLI / 厚 core)。`core.run()` 自己拥有 lifespan(`init_db → run → close_db`),e2e case 不绕过它。

```python
# tests/e2e/test_all_integrations_first_run_baseline.py
async def test_all_integrations_first_run_baseline(test_cfg, ...):
    # seed config into DB before run
    async with seed_config(test_cfg.state_home, "repo", repo_cfg), \
               seed_config(test_cfg.state_home, "changelog", changelog_cfg), \
               seed_config(test_cfg.state_home, "proposal", proposal_cfg):
        pass

    outcome = await run(test_cfg)         # 免 subprocess
    assert outcome.exit_code == 0

    async with db_view(test_cfg.state_home):
        rows = await Report.all()
        # assert cross-integration aggregation
```

### 2.2 测试矩阵

e2e 层共 **18 个 case**:**3 条 golden path + 15 个 per-integration case(每 integration 5 个)**。

#### 2.2.1 三条 golden path(跨 integration 协同)

同一个 cfg 同时配置 repo + changelog + proposal + notification + AI,一次 `core.run` 验证全栈协同。

| 文件 | 场景 | 增量分配 | assert 焦点 |
|---|---|---|---|
| `test_all_integrations_first_run_baseline.py` | 三种 integration 首次协同运行 | 三者都首次 | reports pipeline 把三者的 reports 聚合成 1 条 aggregated report 落库;AI 生成 unified title/summary;notification 一次性派发所有 event(repo ReportEvent + changelog ChangelogEvent + proposal ProposalEvent) |
| `test_all_integrations_second_run_with_increments.py` | 第二次运行 | repo 单独增量(changelog/proposal no-op) | repo 的 report 与 no-op 状态在 aggregated report 中正确混合;checkpoint 推进只发生在 repo;notification 只派发 repo 的 event |
| `test_all_integrations_third_run_no_changes.py` | 第三次运行 | changelog 单独增量(repo/proposal no-op) | 同上;changelog 的增量正确反映,repo/proposal 验证幂等性 |

**"轮流增量"原则**:golden path 的目标是验证**协同机制**(reports pipeline 如何混合不同 integration 的状态、notification 如何统一派发),不是验证"三种 integration 同时 busy"的负载。每条 golden path 让一个 integration 单独增量,fixture 构造简单,assert 焦点在"协同"。

#### 2.2.2 per-integration e2e 包(孤立配置)

每个 integration 一个包(`tests/e2e/repo/` / `tests/e2e/changelog/` / `tests/e2e/proposal/`),包内每个 case 的 cfg **只 enable 当前 integration**,其余 integration 的 config 为空——`core.run` 仍跑全部已注册 integration,但空 config 的 integration no-op。case 失败时定位明确(不会因其他 integration 的 fixture 坏了而误报)。

**职责划分**:
- **golden path** 关注"**协同**"(reports pipeline 聚合、unified title/summary、notification 统一派发)
- **per-integration** 关注"**契约 + 边界**"(report_type、checkpoint 推进、DB 状态、错误聚合、该 integration 特有的业务规则)

每 integration 限定 **5 个 e2e case**,只选"通过真实 `core.run` 才能验证契约"的场景;parser 边界、纯函数、内部状态机、并发参数等下沉 unit/component。

### 2.3 组织结构

```
tests/e2e/
├── conftest.py                                       # 共享原子 fixture + helpers(详见 §2.4)
│
├── test_all_integrations_first_run_baseline.py       # golden path 1
├── test_all_integrations_second_run_with_increments.py  # golden path 2
├── test_all_integrations_third_run_no_changes.py     # golden path 3
│
├── repo/                                             # repo integration e2e 包
│   ├── __init__.py
│   ├── test_first_run_baseline_commit.py
│   ├── test_incremental_commit_diff.py
│   ├── test_clone_failure_marks_run_partial.py
│   ├── test_release_tracking_with_github_api.py
│   └── test_owner_discovery_emits_event.py
│
├── changelog/                                        # changelog integration e2e 包
│   ├── __init__.py
│   ├── test_first_run_markdown.py
│   ├── test_first_run_html_chinese.py
│   ├── test_incremental_multiple_new_versions.py
│   ├── test_fetch_404_marks_run_partial.py
│   └── test_disabled_tracker_skipped.py
│
└── proposal/                                         # proposal integration e2e 包
    ├── __init__.py
    ├── test_first_run_baseline_one_report.py
    ├── test_incremental_new_proposal_notifies.py
    ├── test_incremental_status_change_notify_filter.py
    ├── test_clone_failure_marks_run_partial.py
    └── test_rfc_pr_title_resolution.py
```

**命名约定**:
- **顶层 golden path**:文件名带 `all_integrations` 前缀,表达"跨 integration"
- **per-integration 包**:包名 = integration 名;包内文件名 = 场景名,**不重复 integration 名**(如 `tests/e2e/repo/test_first_run_baseline_commit.py`,不是 `test_repo_first_run_baseline_commit.py`)
- 一场景一文件,除非多个相关性非常高的 case 需要共享大量代码才合并

**conftest 分工**:
- `tests/e2e/conftest.py`:放所有 integration 共享的东西(原子 fixture、helpers、autouse)
- `tests/e2e/<integration>/conftest.py`(**可选**):仅放该 integration 包内多 case 真共享的 helper(如 proposal 包内多 case 都要"构造含 frontmatter 的 EIP 仓库"的 builder)。其他 integration 看不到,避免污染。**只有当某包真有"多 case 共享大量代码"时才建包内 conftest**,否则不建。

### 2.4 共享 fixture 与基础设施

#### 2.4.1 根 `conftest.py`(全测试层共享)

跨 `tests/unit`、`tests/component`、`tests/e2e` 三层共享的 fixture 提到根 `conftest.py`,消除层间复制粘贴。pytest 沿目录树向上查找 conftest,根 conftest 对所有子目录有效。

根 conftest 承担:
- **uvloop 设置**(解决 aiosqlite 在默认 asyncio loop 上的 hang)
- **共享 fixture**:`tmp_state_home` / `workspace` / `git_helper` / `patch_clone_local` / `core_cfg` / `test_cfg`
- **`_stub_observability` autouse**:monkeypatch `progress.cli.lifespan.setup_observability/shutdown_observability`、`progress.api.setup_observability/shutdown_observability/instrument_fastapi_app`、以及任何直接调用点为 no-op,避免跨测试的全局 observability 状态污染(写日志、起 OTel provider)
- **`ALLOW_MODEL_REQUESTS=False` autouse**:全局禁真实 AI 调用(防意外),测试用 `agent.override(model=TestModel())` 显式开 mock
- **marker 自动打标钩子**(`pytest_collection_modifyitems`,见 §1.3)

#### 2.4.2 各层 conftest 分工

每层 conftest 只保留该层专属的 fixture,与根 conftest 不重复:
- `tests/component/conftest.py`:component 层专属——`recording_channel`(fake notification channel)、FastAPI route 测试用的 `app_client`/`auth_client`/`authed_client`/`client`/`db_with_reports`(见 §4)
- `tests/e2e/conftest.py`:e2e 专属的原子 fixture(按 integration 切,见 §2.4.4)

**不建 `tests/unit/conftest.py` 或 `tests/conftest.py` 中间层**:unit 测试用根 conftest 的共享 fixture 即可;曾设的 `tests/conftest.py` 中间层已删除(只引入了与根 conftest 重复的 import,无独立价值)。

#### 2.4.3 `seed_config` + `db_view`(init/close 样板封装)

`core.run()` 自己拥有 lifespan(`init_db → run → close_db`),测试不能在 lifespan 外 query DB,导致每个 e2e case 都要写"前播种 + 后验证"两次 init/close——冗长且易泄漏。提两个 async context manager 封装:

```python
# tests/e2e/conftest.py
from contextlib import asynccontextmanager
from progress.db import close_db, init_db, set_config


@asynccontextmanager
async def seed_config(state_home: str, section: str, cfg: BaseModel):
    """前播种:open DB → set_config → close DB。"""
    await init_db(state_home)
    try:
        await set_config(section, cfg.model_dump(mode="json"))
    finally:
        await close_db()


@asynccontextmanager
async def db_view(state_home: str):
    """后验证:open DB → yield → close DB。供 case 在 yield 段 query DB。"""
    await init_db(state_home)
    try:
        yield
    finally:
        await close_db()
```

case 内用法见 §2.1 示例。

#### 2.4.4 原子 fixture(按 integration 切)

按 integration 切分(而非按 mock 工具切),与 e2e 包组织结构对齐。每个 fixture 封装该 integration 的 mock + seed config 的耦合:

```python
# tests/e2e/conftest.py(示意)
@pytest.fixture
def repo_env(workspace, git_helper, patch_clone_local):
    """真 git repo + patch_clone_local 用 file:// remote。"""
    ...


@pytest.fixture
def changelog_env(httpserver):
    """pytest-httpserver 起 local server + seed changelog config。"""
    ...


@pytest.fixture
def proposal_env(workspace, git_helper, patch_clone_local):
    """真 git repo with proposal 文件(.md frontmatter / .rst field-list)+ seed config。"""
    ...


@pytest.fixture
def smtp_env(aiosmtpd_controller):
    """aiosmtpd 起 local SMTP server + seed email channel config。"""
    ...


@pytest.fixture
def ai_env(test_agent):
    """agent.override(model=TestModel()) + AI config。"""
    ...
```

#### 2.4.5 静态测试数据(`tests/fixtures/`)

事实性的样本数据(真实 EIP/PEP/RFC/DEP `.md`/`.rst` 文件、changelog markdown/HTML 样本等)放 `tests/fixtures/`,跨 unit/component/e2e 三层共享。

**边界**:`tests/fixtures/` **只放纯静态数据文件**(`.md`/`.rst`/`.html`/`.json`),**不放 Python builder/fixture**(builder 留 conftest,数据放 fixtures)。Python 用 `importlib.resources` 读取。

理由:
- proposal parser 的 unit 测试(`tests/unit/test_proposal_sources.py`)和 proposal e2e(`tests/e2e/proposal/`)都要用同一份 EIP/PEP/RFC/DEP 样本,放一起避免复制
- changelog markdown 样本同理,component + e2e 共用
- 真实提案文件是事实数据(`eip-1.md` 长什么样由 ethereum/EIPs 仓库决定),集中放便于"上游格式变了,改一处"

### 2.5 repo integration e2e 场景

| 文件 | 场景 | 为什么必须 e2e |
|---|---|---|
| `test_first_run_baseline_commit.py` | 单 repo 首次检查:clone、lookback、产 repo_update report、commit checkpoint 推进到 HEAD | 验证 clone 真路径 + Report 落库 + checkpoint 推进的完整契约 |
| `test_incremental_commit_diff.py` | 第二次 run 推一个新 commit:diff 分析、commit_count=1、checkpoint 前进 | 验证增量 diff 路径在跨 run 状态机上正确 |
| `test_clone_failure_marks_run_partial.py` | clone URL 无 mock → clone 失败 → `exit_code==1`、status=partial/failed、错误进 `outcome.errors` | 验证错误聚合契约(spec 06 partial/failed 规则)在 `core.run` 层正确 |
| `test_release_tracking_with_github_api.py` | 配置 release 跟踪,aioresponses mock GitHub Releases API,首次只上报最新 1 个 release,release checkpoint 推进 | 验证 release 路径(走 gidgethub + aioresponses)+ "首次只 1 个"业务规则 |
| `test_owner_discovery_emits_event.py` | 配置 owner,aioresponses mock `/orgs/{owner}/repos`,首次只发现 1 个仓库,产出 DiscoveredRepoEvent 进 `outcome.events`,不入 Repository 表 | 验证 owner 发现 + event 构造 + 不入 Repository 表(spec §7.3) |

完整验收清单(含下沉到 unit/component 的项)见 `specs/integrations/repo.md §13`。

### 2.6 changelog integration e2e 场景

| 文件 | 场景 | 为什么必须 e2e |
|---|---|---|
| `test_first_run_markdown.py` | 首次运行 `markdown_heading` parser,只上报 1 个版本,水位推进到它 | 验证 markdown 路径 + "首次只 1 个"规则 + 水位推进 |
| `test_first_run_html_chinese.py` | 首次运行 `html_chinese_version` parser(`uTools vX.Y.Z`)| 验证 HTML 路径(两种 parser 覆盖)|
| `test_incremental_multiple_new_versions.py` | 第二次 run,日志新增 3 个版本:报告渲染全部 3 个,水位推进到列表第一个,只发 1 个 ChangelogEvent(携带最新)| 验证"报告渲染全部 vs 通知只发最新 1 个"的关键分离(spec §1.5)|
| `test_fetch_404_marks_run_partial.py` | httpserver 返回 404 → status=failed/partial,其他 tracker 不受影响(多 tracker 配置)| 验证单 tracker 失败不影响其他 + 错误聚合 |
| `test_disabled_tracker_skipped.py` | 一个 enabled + 一个 disabled tracker:disabled 跳过且**不**盖戳 `last_check_time` | 验证 `skipped` 状态的"不盖戳"语义(spec §2)|

完整验收清单见 `specs/integrations/changelog.md §12`。

### 2.7 proposal integration e2e 场景

proposal 走 git clone(不是 HTTP scrape),e2e 用 **EIP** 作为代表类型(frontmatter 解析最典型);RFC 因 GitHub PR 标题解析路径单独有 1 个 case。

| 文件 | 场景 | 为什么必须 e2e |
|---|---|---|
| `test_first_run_baseline_one_report.py` | 首次运行(全新 EIP 仓库 fixture):全部提案入库,只产 1 个报告(最新创建的)| 验证"首次全部入库 + 只 1 报告"的刻意设计(spec §6)+ checkpoint 推进 |
| `test_incremental_new_proposal_notifies.py` | 第二次 run,新增一个 EIP 文件:产 new 事件,走 `proposal_new_prompt.j2`,notifiable → 聚合落库 + ProposalEvent | 验证 new 事件契约 + AI 调用 + 通知派发 |
| `test_incremental_status_change_notify_filter.py` | 两种状态变化:Draft→Final(notifiable)+ Draft→Review(非 notifiable)。验证快照都更新,但只有 Final 那个落库为报告 + 通知 | 验证"快照更新与通知过滤分离"(spec §11)——proposal 最关键的设计决策 |
| `test_clone_failure_marks_run_partial.py` | proposal 仓库 clone 失败 → stage="clone" 错误上报 + 重抛 → outcome partial | 验证 clone 错误在 proposal 路径的聚合 |
| `test_rfc_pr_title_resolution.py` | RFC st(stub)提案:有 PR 号,aioresponses mock GitHub PR API 返回标题 → 用 PR 标题;无 PR 号 → fallback。验证 fallback 路径 | 验证 §12 RFC 特殊解析 + fallback 不阻塞 |

完整验收清单见 `specs/integrations/proposal.md §19`。

### 2.8 feed integration e2e(Docker 依赖)

feed integration 的价值在于与真实 Miniflux + Postgres 对话(mock 抓不到 JSON drift)。其 e2e 与 repo/changelog/proposal 同级(不特殊化),只是需要 Docker Compose 起外部服务:

- 包目录:`tests/e2e/feed/`
- `tests/e2e/feed/docker-compose.yml` 起 Miniflux + Postgres,healthcheck 就绪后创建 API key
- `tests/e2e/feed/conftest.py` 等待 healthcheck 通过,提供 feed 配置的 fixture
- 额外 marker `feed` 标记这些 case,CI 通过 Docker 起栈后纳入 `uv run pytest`(本地开发者有 Docker 时也跑;无 Docker 时 `-m "not feed"` 跳过)

feed e2e 完整验收清单见 `specs/integrations/feed.md`。

## 3. mock 策略(按 boundary 选,不按方便)

### 3.1 对照表

| 对象 | mock 工具 |
|---|---|
| **GitHub API(gidgethub)** | aioresponses(mock aiohttp,覆盖 gidgethub.aiohttp) |
| **本地 git 操作** | 临时 repo fixture(真 git subprocess,tmp_path;仅 remote URL 替换为 `file://`) |
| **AI(Pydemic AI)** | TestModel / FunctionModel + `agent.override`(spec 08) |
| **SMTP(aiosmtplib)** | aiosmtpd(起本地 SMTP server) |
| **HTTP server**(changelog fetch / proposal RFC PR / markpost / feishu / webhook) | pytest-httpserver |
| **时间** | time-machine |
| **FastAPI app** | httpx ASGITransport + asgi-lifespan.LifespanManager |
| **DB** | 真 SQLite tmp 文件 |

### 3.2 aioresponses vs pytest-httpserver 的分工

| 工具 | 适用范围 |
|---|---|
| **aioresponses** | 仅 gidgethub/GitHub API(repo release/owner 发现、proposal RFC PR 标题解析)|
| **pytest-httpserver** | 其余所有 HTTP 出站(changelog fetch、markpost POST、feishu POST、webhook)|

**为什么不全用 aioresponses**:aioresponses patch `ClientSession._request`,会拦截**所有** aiohttp 流量,包括 pytest-httpserver 起的本地 server——两者不能 autouse 共存。`aioresponses` 仅给 gidgethub(需要拦截 sans-IO 栈),其他直接写的 HTTP 出站用 pytest-httpserver 起 local server 更接近真实。

### 3.3 opt-in 原则

所有 mock 工具 fixture **默认 opt-in**(case 按需 `request`),不 autouse:

| 工具 | autouse 代价 |
|---|---|
| aioresponses | 与 pytest-httpserver 冲突,不能 autouse |
| aiosmtpd | 每 case 起一个 SMTP server,绝大多数 case 用不到 |
| TestModel/agent.override | 每 case override 所有 agent,绝大多数 case 不 assert AI 内容 |
| time-machine | 每 case 锁时间,绝大多数 case 不依赖固定时间 |

**例外(autouse)**:
- `ALLOW_MODEL_REQUESTS=False` —— 全局禁真实 AI 调用(安全开关,非 mock 资源)
- `_stub_observability` —— 避免 observability 全局状态污染

### 3.4 aioresponses 最佳实践(源码核实)

`aioresponses/core.py:260` patch `ClientSession._request`,覆盖所有 aiohttp 用户(含 gidgethub.aiohttp)。**mock 响应带 `x-ratelimit-*` header**——gidgethub `RateLimit.from_http` 优雅处理缺 header,但带 header 更真实(`sansio.py:270-283`)。

## 4. API(FastAPI route)测试

FastAPI route 测试归入 `tests/component/`(见 §1.2"为何 API 不单列一层"),与 component 测试共享同一套 DB/client fixture。

```python
async with AsyncClient(transport=ASGITransport(app=create_app(test_cfg))) as client:
    resp = await client.get("/api/v1/reports")
```

- 替代同步 `TestClient`(async 正解)
- 用 `asgi-lifespan` 的 `LifespanManager` 触发 lifespan

`tests/component/conftest.py` 中的 route 测试 fixture:
- `app_client` —— yield `(app, client)`,lifespan wired up + DB initialized + observability stubbed(根 conftest autouse 已经 stub);auth **禁用**(供无需鉴权的 report/config/integration route 测试)
- `auth_client` —— yield `(app, client)`,auth **启用** + 预置 admin 用户(env `PROGRESS_TEST_TOKEN`)
- `authed_client` —— 在 `auth_client` 基础上自动登录,返回已带 Bearer token 的 client
- `client` —— 仅 httpx client(派生自 `app_client`)
- `db_with_reports` —— seed 两行 Report 供 list/detail 测试

## 5. 工具链

### 5.1 保留

| 工具 | 用途 |
|---|---|
| pytest + pytest-asyncio(auto 模式) | asyncio-only 项目推荐默认 |
| pytest-mock | mocker fixture |
| **aioresponses** | aiohttp mock(主用于 gidgethub) |
| time-machine | 时间 mock(快,优于 freezegun) |
| aiosmtpd | 本地 SMTP server |
| pytest-httpserver | HTTP server mock |
| httpx | ASGITransport(API 测试) |
| pydantic-ai TestModel/FunctionModel | AI mock(spec 08) |
| asgi-lifespan | FastAPI lifespan 触发 |

### 5.2 删除

| 工具 | 理由 |
|---|---|
| **responses**(requests mock) | ⑦ 换 aiohttp,requests 不再用 |
| vcrpy | golden-file replay 非必需,显式 mock 层已足够 |

### 5.3 pytest-asyncio auto 模式

`asyncio_mode = "auto"`——auto 是 asyncio-only 项目**推荐默认**(auto 标记所有 async 测试 + fixtures)。保持。

uvloop 设置写在根 `conftest.py`(解决 aiosqlite 在默认 asyncio loop 上的 hang 问题)。

## 6. 与其他 spec 的关系

| spec | 关系 |
|---|---|
| 02(config) | zero-config——测试只用 `CoreConfig(state_home=...)` 通用接口构造,无 `for_e2e_tests` 工厂 |
| 05(CLI) | 薄 CLI / 厚 core——e2e 直调 `core.run()` 的依据 |
| 06(integration plugin) + `specs/integrations/*` | 每个 integration 自带完整测试矩阵;spec 15 只声明分层原则 + e2e 层筛选结果 |
| 07(git/http) | aioresponses + 真 git subprocess 的依据 |
| 08(AI) | TestModel / FunctionModel + `agent.override` |
| 09(reports) | reports pipeline 各阶段可单测,e2e 测聚合 |
| 10(notifications) | dispatcher/component 测,channel 用 aiosmtpd/httpserver |
| 11(i18n)/ 12(api)/ 13(frontend) | drift 检查(OpenAPI/Babel/tortoise 迁移)、CI 流水线编排、e2e 执行频率(本地 + release 前)由独立 CI 规范承担(待建),不在本 spec;前端测试(Vitest + Playwright + openapi-typescript)见 spec 13 |
