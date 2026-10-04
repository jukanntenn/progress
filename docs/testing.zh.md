# 测试指南

[English](testing.md) | 中文

Progress 使用**三层测试套件**（spec 15）：

- **`unit`**：纯函数/单类测试，注入伪造对象，无 IO。
- **`component`**：真实 SQLite 与真实本地 git 之下的多模块协作；外部服务（GitHub API、AI（人工智能）、changelog HTTP、SMTP）被模拟。原 API 层测试（经 httpx ASGITransport 驱动的 FastAPI 路由测试）也住在此层。
- **`e2e`**：端到端测试，经直接的 `cli/core.run()` 调用驱动完整流水线，面向**真实外部服务**。`feed` e2e 需要真实的 Miniflux + Postgres 栈（经 Docker Compose 拉起）；其余 e2e 集成全部使用本地 git + 被模拟的 GitHub API / pytest-httpserver。

**指导哲学**：只模拟你控制不了的东西，其余一切保持真实。把 mock 对准边界，绝不对准便利。本地与 CI 运行**完全相同**的命令 `uv run pytest`，且覆盖率始终开启。

## 1. 运行测试

```bash
# Whole suite (unit + component + e2e, including feed which needs Docker)
uv run pytest

# Single layer
uv run pytest tests/unit
uv run pytest tests/component
uv run pytest tests/e2e

# Single file / test
uv run pytest tests/unit/test_config.py
uv run pytest tests/unit/test_config.py::test_loads_toml
```

`pyproject.toml` 设置了 `testpaths = ["tests"]`。三个标记（`unit` / `component` / `e2e`）由根 `conftest.py` 的 `pytest_collection_modifyitems` 钩子按测试文件所在目录自动打上，因此用例从不需要手写 `@pytest.mark.xxx`（spec 15 §1.3）。第四个标记 `feed` 标出依赖 Docker 的 feed e2e。显式选择层：

```bash
uv run pytest -m unit            # only unit
uv run pytest -m component       # only component (incl. former API tests)
uv run pytest -m "not feed"      # everything except Docker-dependent feed e2e
uv run pytest -m e2e             # only e2e
```

### 1.1 覆盖率始终开启

`pyproject.toml` 经 `addopts` 注入 `--cov=progress --cov-report=term-missing --cov-report=xml`，因此每次 `uv run pytest` 都向终端打印覆盖率摘要并写出 `coverage.xml`（由 CI 的 codecov action 消费）。不存在需要记住的另一条覆盖率命令。

### 1.2 feed e2e 需要 Docker

`feed` 集成的全部价值在于与真实 Miniflux 对话，而 mock 发现不了「真实 Miniflux 的条目 JSON 偏离了我们的假设」。CI 在跑套件前经 `docker compose` 拉起 Miniflux + Postgres 栈；本地开发者也必须让 Docker 处于运行状态。命令处处相同：`uv run pytest`。要在本地跳过 feed e2e（如没有 Docker）：

```bash
uv run pytest -m "not feed"
```

## 2. 测试布局

```
conftest.py                       # Root conftest: uvloop, shared fixtures, observability
                                  # stub, ALLOW_MODEL_REQUESTS=False, marker auto-tagging
tests/
├── conftest.py                   # (shared fixtures live in root conftest)
├── unit/                         # Pure-function / single-class tests (fakes, no IO)
├── component/                    # Mocked external services + real SQLite/git + FastAPI ASGI
│   └── conftest.py               # RecordingChannel + app_client/auth_client fixtures
└── e2e/                          # Real external services, direct core.run() calls
    ├── conftest.py               # e2e atomic fixtures (repo_env / changelog_env / ...),
    │                             # seed_config / db_view helpers, smtp_server, override_agent
    ├── test_all_integrations_*.py    # 3 golden paths (cross-integration coordination)
    ├── repo/                     # per-integration e2e (real git + mocked GitHub API)
    ├── changelog/                # per-integration e2e (real git + pytest-httpserver)
    ├── proposal/                 # per-integration e2e (real git + mocked GitHub API)
    └── feed/                     # real Miniflux + Postgres via docker compose

web/e2e/                          # Playwright browser e2e (separate Node/pnpm suite)
```

共享 fixture（`tmp_state_home`、`workspace`、`git_helper`、`patch_clone_local`、`core_cfg`、`test_cfg`）住在**根 `conftest.py`** 里，从而对每一层可见、无需重复。pytest 从测试文件向上遍历到 rootdir 收集 conftest，因此根 conftest 的 fixture 处处可用。

### 2.1 为什么是 `component/` 而不是 `integration/`

`integration` 与 `integrations/` 插件包撞名（spec 06）。「真实 SQLite 之下、外部服务被模拟的多模块协作」的社区标准术语是**组件测试（component testing）**，故采用之（spec 15）。原 `tests/api/` 套件并入此处：FastAPI 路由测试就是组件测试（模拟 observability，并经 httpx ASGITransport 在进程内驱动应用）。

### 2.2 文件命名

测试文件命名为 `test_` + 被测模块名（`config.py` → `test_config.py`）。在各层内部，文件在适用的地方镜像源码包结构：

- `src/progress/cli/ai/agent.py` → `tests/unit/test_ai_agent.py`
- `src/progress/integrations/repo/tracker.py` → `tests/component/test_repo_integration.py`
- `src/progress/api/routes/reports.py` → `tests/component/test_reports.py`
- `src/progress/cli/core.py` (full pipeline) → `tests/e2e/test_all_integrations_*.py`

### 2.3 浏览器 e2e（`web/e2e/`）

Playwright 浏览器 e2e 是住在 `web/e2e/` 下的**独立 Node/pnpm 套件**，有自己的 `package.json` 与 `@playwright/test` 依赖。它经真实浏览器驱动真实的生产容器（Caddy + FastAPI）。它**不是** pytest 套件的一部分；见 `web/e2e/HANDBOOK.md` 与 `e2e.yml` 工作流。

## 3. 异步约定

整个运行时是异步的。`pyproject.toml` 设置了 `asyncio_mode = "auto"`，因此 `async def test_...` 函数与 `async def` fixture 都无需任何装饰器即可运行。不需要 `@pytest.mark.asyncio`，也不需要 `pytest_asyncio.fixture`。

## 4. Mock 策略（spec 15）

| 边界 | 工具 | 说明 |
|---|---|---|
| **GitHub API**（gidgethub.aiohttp） | `aioresponses` | 模拟 `aiohttp.ClientSession._request`，覆盖包括 gidgethub 在内的全部 aiohttp 调用方。真实的 gidgethub 解析/分页照跑。 |
| **本地 git 操作** | 真实 git 子进程 + tmp_path | 仅把远程 URL 换成本地 `file://` 路径。下游 GitPython / `git` CLI 操作真实运行。 |
| **AI**（Pydantic AI） | `TestModel` / `FunctionModel` + `agent.override` | 真实 agent（智能体）运行循环照跑；仅替换 LLM 后端。 |
| **SMTP**（aiosmtplib） | `aiosmtpd` 本地服务器 | 回环地址上的真实 SMTP 协议。 |
| **HTTP 服务器**（markpost / webhook / changelog 拉取） | `pytest-httpserver` | 响应确定的真实本地 HTTP 服务器。 |
| **时间** | `time-machine` | 快速冻结墙上时钟；比 `freezegun` 更可取。 |
| **FastAPI 应用**（组件测试） | `httpx.AsyncClient` + `ASGITransport` | 取代旧的同步 `TestClient`。用 `asgi-lifespan.LifespanManager` 触发 lifespan。 |
| **数据库** | 真实 SQLite 临时文件 | 真实 tortoise-orm 查询；从不模拟数据库。 |

### 4.1 `aioresponses` 覆盖 gidgethub

`aioresponses/core.py` 补丁了 `ClientSession._request`，这正是 `gidgethub.aiohttp` 使用的那个调用点。最佳实践：在被模拟的响应上带上 `x-ratelimit-*` 头，让 gidgethub 的 `RateLimit.from_http` 走真实代码路径（`sansio.py:270-283`）。

### 4.2 本地 git fixture 模式

仓库跟踪器经 `git` 子进程克隆；e2e/component 测试把 `progress.integrations.repo.tracker.clone_or_fetch`（跟踪器导入的绑定名）替换为向工作区 `git clone` 一个本地裸仓库 fixture。`patch_clone_local` fixture 住在**根 `conftest.py`**，从而在 `tests/component/` 与 `tests/e2e/` 之间共享、无需重复。

要模拟「自上次运行以来的新提交」，调用 `GitRepo.add_commit(msg, files=)`：它向工作副本提交并推送到裸远程，推进 HEAD。传入 `commit_date=` 获得确定的作者日期（避免依赖墙上时钟的排序断言偶发失败）。

## 5. 共享 fixture

### 5.1 根 `conftest.py`（跨全部层共享）

共享 fixture 被提升到根 conftest，从而处处生效；子目录 conftest 只补充该层特有的 fixture。

| Fixture / 钩子 | 作用域 | 用途 |
|---|---|---|
| `tmp_state_home` | function | 每个测试独享的 `<state_home>` 目录；SQLite 数据库位于 `<state_home>/progress.db`。 |
| `core_cfg` / `test_cfg` | function | 最小化的 `CoreConfig(state_home=tmp_state_home)`，其余字段全默认（零配置，spec 02）。 |
| `workspace` | function | 存放 git 仓库与文件 IO 的临时目录。 |
| `git_helper` | function | 带 `make_repo(...)` 与 `add_commit(...)` 助手的 `_GitHelper` 实例（两者都接受 `commit_date=` 以获得确定的时间戳）。 |
| `patch_clone_local` | function | 返回一个可调用对象，把跟踪器绑定的 `clone_or_fetch` 名替换为使用本地裸远程。 |
| `_stub_observability`（autouse） | function | 把每个调用点（CLI lifespan、API lifespan、直接调用）上的 `setup_observability` / `shutdown_observability` 桩成空操作，使任何测试都不污染全局 observability 状态。 |
| `_disable_real_model_requests`（autouse） | function | 作为安全开关全局禁用真实 AI 调用；用例经 `agent.override(model=TestModel())` 显式选用模拟 AI。 |
| `pytest_collection_modifyitems` | — | 按目录为每个测试自动打上 `unit` / `component` / `e2e` 标记（spec 15 §1.3）。 |

uvloop 事件循环策略也在此安装，以规避 aiosqlite 在默认 asyncio 循环下的挂起。

### 5.2 `tests/component/conftest.py`

| Fixture | 用途 |
|---|---|
| `recording_channel` | 记录它收到的每个通知载荷的 `RecordingChannel` 测试替身。 |
| `app_client` | 产出接线好 lifespan 并初始化好数据库的 `(app, client)`。observability 已由根 autouse fixture 桩掉。认证关闭。写入一个临时 TOML，让 `create_app(config_path)` 能从中读到 `state_home`。 |
| `auth_client` | 同 `app_client`，但认证**开启**并播种一个管理员用户。 |
| `authed_client` | 已以管理员（已知密码）登录的 `auth_client`。 |
| `client` | 便捷入口：只取 `app_client` 里的 httpx 客户端。 |
| `db_with_reports` | 为列表/详情测试向数据库播种两行 `Report`。 |

### 5.3 `tests/e2e/conftest.py`

| Fixture / 助手 | 用途 |
|---|---|
| `repo_env` / `changelog_env` / `proposal_env` | 按集成切片的原子 fixture；各自封装该集成的 mock 设置 + 配置播种（spec 15 §2.4.4）。 |
| `gh_mock` | 限定在 GitHub API mock（仅 gidgethub）范围内的 `aioresponses` 上下文。 |
| `smtp_server` | 启动本地 `aiosmtpd` SMTP 服务器；产出 `(host, port, messages)`。 |
| `override_agent(result_type, *, response_text=)` | 用 `TestModel` 覆盖缓存的 AI agent 的上下文管理器。 |
| `seed_config(state_home, section, cfg)` | 异步上下文管理器：打开数据库 → `set_config` → 关闭数据库，用于运行前播种。 |
| `db_view(state_home)` | 异步上下文管理器：打开数据库 → yield → 关闭数据库，用于运行后断言。 |

## 6. e2e 测试：直接调用 `core.run()`（spec 15）

E2e 测试直接调用 `cli.core.run()` 来驱动完整流水线：不起子进程、不用 `CliRunner`、不对内部助手做 monkeypatch。这是 spec 15 特别点出的关键设计修正。

```python
# tests/e2e/repo/test_first_run_baseline_commit.py
async def test_first_run_baseline_commit(test_cfg, workspace, git_helper, patch_clone_local, monkeypatch):
    repo = git_helper.make_repo(workspace, "owner_repo", initial_files={"README.md": "# hello\n"})
    patch_clone_local(monkeypatch, {"https://github.com/owner/repo.git": repo.bare_path})

    repo_cfg = RepoIntegrationConfig(repos=[{"url": "owner/repo", "branch": "main"}])
    async with seed_config(test_cfg.state_home, "repo", repo_cfg):
        pass

    outcome = await run(test_cfg)
    assert outcome.exit_code == 0

    # core.run() owns its lifespan (init_db → run → close_db), so post-run
    # queries must re-initialize the DB. The db_view helper wraps the
    # init → yield → close boilerplate.
    async with db_view(test_cfg.state_home):
        rows = await Report.all()
        assert len(rows) >= 1
```

### 6.1 lifespan 归属

`core.run()` 拥有自己的 lifespan：开始时调用 `init_db(state_home)`，退出时调用 `close_db()`。因此任何运行后的数据库查询（用于断言）都必须重新初始化数据库。`seed_config` 与 `db_view` 这两个异步上下文管理器（在 `tests/e2e/conftest.py`，spec 15 §2.4.3）封装了运行前播种与运行后查询的样板，使用例从不用手写 `init_db`/`close_db`/`try/finally`。

### 6.2 e2e 中哪些被模拟、哪些真实

| 外部服务 | 策略 | 理由 |
|---|---|---|
| GitHub API（gidgethub） | `aioresponses` | 模拟 `aiohttp.ClientSession._request`，覆盖包括 gidgethub 在内的全部 aiohttp 调用方；真实的 gidgethub 解析/分页照跑。GitHub API 路径（仓库 release/所有者发现、提案 RFC（决策记录）PR（Pull Request）标题）**只**用这一种 mock。 |
| 本地 git（`git` 子进程） | 经 `patch_clone_local` + 本地裸 git 仓库 fixture 的真实 git | spec 07 经 asyncio 子进程调 `git`；fixture 只把远程 URL 换成本地 `file://` 路径，下游 git 操作全部真实运行。 |
| Miniflux（feed 集成） | **经 Docker Compose 的真实 Miniflux + Postgres** | feed 集成的价值在于对话真实 Miniflux；mock 抓不住 JSON 漂移。`tests/e2e/feed/docker-compose.yml` 拉起该栈；`tests/e2e/feed/conftest.py` 等待健康检查通过并创建 API key。 |
| AI provider | Pydantic AI `TestModel` / `FunctionModel` + `agent.override` | 真实 agent 运行循环照跑；仅替换 LLM 后端。 |
| SMTP | `aiosmtpd` 本地服务器 | 完全可控的真实 SMTP 协议。 |
| HTTP 服务器（changelog 拉取 / 提案 RFC PR / markpost / feishu / webhook） | `pytest-httpserver` | 真实本地 HTTP 服务器；覆盖 gidgethub 之外的每一条 HTTP 出口。`aioresponses` 不能 autouse，否则会连 httpserver 流量一起拦截（spec 15 §3.2）。 |
| Bugsink / observability | 经 `_stub_observability` autouse（根 conftest）桩掉 | 仅错误收集器；单独验证轻而易举。 |
| SQLite / 文件系统 / Jinja 模板 | 真实 | 进程内完全可控；从不模拟。 |

## 7. 组件测试：经 httpx ASGITransport 驱动 FastAPI 路由（spec 15）

FastAPI 路由测试（原 `tests/api/` 层，现居 `tests/component/`）在进程内驱动真实应用：

```python
async with LifespanManager(app):
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        resp = await client.get("/api/v1/reports")
```

- 取代旧的同步 `TestClient`（它把异步 lifespan 跑在单独的线程/循环里，会破坏 tortoise-orm 绑定 contextvar 的连接）。
- `asgi-lifespan.LifespanManager` 驱动 FastAPI lifespan，使 `init_db` 先于任何请求运行。

### 7.1 错误处理器测试注意事项

Starlette 的 `@app.exception_handler(Exception)` 路由到 `ServerErrorMiddleware`（而非 `ExceptionMiddleware`）。`ServerErrorMiddleware` 处理后总是重新抛出，而 `httpx.ASGITransport` 默认 `raise_app_exceptions=True`。要测试 500 响应，构造 transport 时传 `raise_app_exceptions=False`：

```python
transport = ASGITransport(app=app, raise_app_exceptions=False)
```

## 8. 配置测试：直接构造 `CoreConfig`（spec 02）

测试直接构造 `CoreConfig`，只给它们关心的字段；其余全默认（spec 02 零配置）：

```python
cfg = CoreConfig(
    state_home=tmp_state_home,
    github=GitHubConfig(gh_token=SecretStr("test-token")),
    analysis=AnalysisConfig(provider="anthropic", api_key=SecretStr("test-key")),
)
```

`tests/unit/test_config.py` 与 `tests/component/test_config.py` 覆盖配置加载、节级 schema 校验、机密脱敏与数据库支撑的 upsert/reload。

## 9. 单元测试：窄而纯

单元测试住在 `tests/unit/`，瞄准单个模块或类。它们为协作者注入伪造对象、不做 IO。单元层覆盖：

- `cli/core.py` 的编排由 e2e（直接调用 `core.run`）覆盖，而非单元测试。
- `tests/unit/test_config.py` 使用直接构造 `CoreConfig`。
- 通知 / scrub / 文本 / 时区 / markdown / i18n / git_url / changelog 解析器 / 提案来源都有窄单元测试。
- 各集成的纯函数（解析器、`normalize`、`should_notify`、状态枚举、模板选择）按 spec 15 §1.2 住在此层；完整验收清单见各集成的 spec（`specs/integrations/*.md`）。

## 10. CI（CI spec）

全部 Python 测试跑在单个 CI 作业（`ci.yml` 的 `python-tests`）里，用**与本地相同的命令**：`uv run pytest`。该作业运行前经 `docker compose -f tests/e2e/feed/docker-compose.yml` 拉起 Miniflux + Postgres 栈，跑完再拆除。覆盖率（经 `addopts` 注入）流向 codecov。

浏览器 e2e（`web/e2e/`）跑在单独的工作流（`e2e.yml`）中，仅在 `src/`、`web/`、`docker/` 或 `web/e2e/` 变化时触发。

漂移检查（OpenAPI / i18n / 迁移 / TS 类型）是 CI 的独立关注点（`drift-checks` 作业）；编排见 CI spec。

## 11. 前端测试（spec 13）

- 组件级测试（`web/`）用 **Vitest + Testing Library + msw**。
- 覆盖真实用户交互流程的浏览器 e2e（`web/e2e/`）用 **Playwright**。
- **`openapi-typescript`** 从 OpenAPI schema 生成类型，前端 API 调用因此在编译期被类型检查。
