# Testing Guide

Progress uses a **three-layer test suite** (spec 15):

- **`unit`** — pure-function / single-class tests with injected fakes, no IO.
- **`component`** — multi-module collaboration under real SQLite and real local
  git; external services (GitHub API, AI, changelog HTTP, SMTP) are mocked.
  Former API-layer tests (FastAPI routes via httpx ASGITransport) live here too.
- **`e2e`** — end-to-end tests driving the full pipeline via direct
  `cli/core.run()` calls against **real external services**. The `feed` e2e
  needs a real Miniflux + Postgres stack (brought up via Docker Compose); all
  other e2e integrations use local git + mocked GitHub API / pytest-httpserver.

**Guiding philosophy**: mock only what you cannot control, keep everything else
real. Match the mock to the boundary, never to convenience. Local and CI run
the **identical** command — `uv run pytest` — with coverage always on.

## 1. Running tests

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

`pyproject.toml` sets `testpaths = ["tests"]`. Three markers (`unit` /
`component` / `e2e`) are auto-applied by the root `conftest.py`'s
`pytest_collection_modifyitems` hook based on the test file's directory, so
cases never need a hand-written `@pytest.mark.xxx` (spec 15 §1.3). A fourth
marker `feed` tags the Docker-dependent feed e2e. Select layers explicitly:

```bash
uv run pytest -m unit            # only unit
uv run pytest -m component       # only component (incl. former API tests)
uv run pytest -m "not feed"      # everything except Docker-dependent feed e2e
uv run pytest -m e2e             # only e2e
```

### 1.1 Coverage is always on

`pyproject.toml` injects `--cov=progress --cov-report=term-missing
--cov-report=xml` via `addopts`, so every `uv run pytest` run prints a coverage
summary to the terminal and writes `coverage.xml` (consumed by the codecov
action in CI). There is no separate coverage command to remember.

### 1.2 The feed e2e needs Docker

The `feed` integration's whole value is talking to a real Miniflux, and a mock
cannot discover "real Miniflux entry JSON drifts from our assumptions". CI
brings up the Miniflux + Postgres stack via `docker compose` before running the
suite; local developers must have Docker running too. The command is identical
everywhere — `uv run pytest`. To skip feed e2e locally (e.g. no Docker):

```bash
uv run pytest -m "not feed"
```

## 2. Test layout

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

Shared fixtures (`tmp_state_home`, `workspace`, `git_helper`,
`patch_clone_local`, `core_cfg`, `test_cfg`) live in the **root `conftest.py`**
so they are visible to every layer without duplication. pytest traverses upward
from a test file to the rootdir collecting conftests, so the root conftest's
fixtures are in scope everywhere.

### 2.1 Why `component/` instead of `integration/`

`integration` collides with the `integrations/` plugin package (spec 06). The
community-standard term for "multi-module collaboration under real SQLite but
mocked external services" is **component testing**, so we use that (spec 15).
The former `tests/api/` suite is merged here: FastAPI route tests are
component tests (they mock observability and drive the app in-process via
httpx ASGITransport).

### 2.2 File naming

Test files are named `test_` + the name of the tested module
(`config.py` → `test_config.py`). Inside each layer, files mirror the source
package structure where applicable:

- `src/progress/cli/ai/agent.py` → `tests/unit/test_ai_agent.py`
- `src/progress/integrations/repo/tracker.py` → `tests/component/test_repo_integration.py`
- `src/progress/api/routes/reports.py` → `tests/component/test_reports.py`
- `src/progress/cli/core.py` (full pipeline) → `tests/e2e/test_all_integrations_*.py`

### 2.3 Browser e2e (`web/e2e/`)

Playwright browser e2e is a **separate Node/pnpm suite** living under `web/e2e/`
with its own `package.json` and `@playwright/test` dependency. It drives the
real production container (Caddy + FastAPI) through a real browser. It is **not**
part of the pytest suite — see `web/e2e/HANDBOOK.md` and the `e2e.yml` workflow.

## 3. Async conventions

The whole runtime is async. `pyproject.toml` sets `asyncio_mode = "auto"`, so
both `async def test_...` functions and `async def` fixtures run without any
decorator. There is no need for `@pytest.mark.asyncio` or
`@pytest_asyncio.fixture`.

## 4. Mock strategy (spec 15)

| Boundary | Tool | Notes |
|---|---|---|
| **GitHub API** (gidgethub.aiohttp) | `aioresponses` | Mocks `aiohttp.ClientSession._request`, covers all aiohttp callers including gidgethub. Real gidgethub parsing/pagination runs. |
| **Local git operations** | Real git subprocess + tmp_path | Only the remote URL is replaced with a local `file://` path. Downstream GitPython / `git` CLI operations run for real. |
| **AI** (Pydantic AI) | `TestModel` / `FunctionModel` + `agent.override` | Real agent run-loop executes; only the LLM backend is replaced. |
| **SMTP** (aiosmtplib) | `aiosmtpd` local server | Real SMTP protocol over loopback. |
| **HTTP server** (markpost / webhooks / changelog fetch) | `pytest-httpserver` | Real local HTTP server with deterministic responses. |
| **Time** | `time-machine` | Fast wall-clock freezing; preferred over `freezegun`. |
| **FastAPI app** (component tests) | `httpx.AsyncClient` + `ASGITransport` | Replaces the legacy sync `TestClient`. Use `asgi-lifespan.LifespanManager` to trigger lifespan. |
| **DB** | Real SQLite tmp file | Real tortoise-orm queries; never mock the DB. |

### 4.1 `aioresponses` covering gidgethub

`aioresponses/core.py` patches `ClientSession._request`, which is the exact
call site `gidgethub.aiohttp` uses. Best practice: include `x-ratelimit-*`
headers on mocked responses so gidgethub's `RateLimit.from_http` runs the real
code path (`sansio.py:270-283`).

### 4.2 Local git fixture pattern

The repo tracker clones via `git` subprocess; e2e/component tests patch
`progress.integrations.repo.tracker.clone_or_fetch` — the bound name the tracker
imports — to instead `git clone` a local bare repo fixture into the workspace.
The `patch_clone_local` fixture lives in the **root `conftest.py`** so it is
shared across `tests/component/` and `tests/e2e/` without duplication.

To simulate "new commit since last run", call `GitRepo.add_commit(msg, files=)`
which commits to the working copy and pushes to the bare remote, advancing HEAD.
Pass `commit_date=` for a deterministic author date (avoids flaky
wall-clock-dependent ordering assertions).

## 5. Shared fixtures

### 5.1 Root `conftest.py` (shared across all layers)

Shared fixtures are lifted to the root so they apply everywhere; sub-directory
conftests only add layer-specific fixtures.

| Fixture / hook | Scope | Purpose |
|---|---|---|
| `tmp_state_home` | function | Per-test `<state_home>` directory; the SQLite DB lives at `<state_home>/progress.db`. |
| `core_cfg` / `test_cfg` | function | Minimal `CoreConfig(state_home=tmp_state_home)` — all other fields default (zero-config, spec 02). |
| `workspace` | function | Scratch directory for git repos and file IO. |
| `git_helper` | function | `_GitHelper` instance with `make_repo(...)` and `add_commit(...)` helpers (both accept `commit_date=` for deterministic timestamps). |
| `patch_clone_local` | function | Returns a callable that patches the tracker's bound `clone_or_fetch` name to use local bare remotes. |
| `_stub_observability` (autouse) | function | Stubs `setup_observability` / `shutdown_observability` on every call site (CLI lifespan, API lifespan, direct calls) to no-ops so no test pollutes global observability state. |
| `_disable_real_model_requests` (autouse) | function | Globally disables real AI calls as a safety switch; cases opt into mocked AI via `agent.override(model=TestModel())`. |
| `pytest_collection_modifyitems` | — | Auto-tags each test with `unit` / `component` / `e2e` based on its directory (spec 15 §1.3). |

The uvloop event-loop policy is also installed here to work around an aiosqlite
hang under the default asyncio loop.

### 5.2 `tests/component/conftest.py`

| Fixture | Purpose |
|---|---|
| `recording_channel` | `RecordingChannel` test double that records every notification payload it receives. |
| `app_client` | Yields `(app, client)` with lifespan wired up + DB initialized. Observability is already stubbed by the root autouse fixture. Auth is disabled. A temp TOML is written so `create_app(config_path)` can read `state_home` from it. |
| `auth_client` | Like `app_client` but with auth **enabled** + a seeded admin user. |
| `authed_client` | `auth_client` already logged in as admin (known password). |
| `client` | Convenience: just the httpx client from `app_client`. |
| `db_with_reports` | Seeds the DB with two `Report` rows for list/detail tests. |

### 5.3 `tests/e2e/conftest.py`

| Fixture / helper | Purpose |
|---|---|
| `repo_env` / `changelog_env` / `proposal_env` | Atomic fixtures sliced per integration; each encapsulates that integration's mock setup + config seeding (spec 15 §2.4.4). |
| `gh_mock` | `aioresponses` context scoped to the GitHub API mock (gidgethub only). |
| `smtp_server` | Starts a local `aiosmtpd` SMTP server; yields `(host, port, messages)`. |
| `override_agent(result_type, *, response_text=)` | Context manager overriding the cached AI agent with a `TestModel`. |
| `seed_config(state_home, section, cfg)` | Async context manager: open DB → `set_config` → close DB, for pre-run seeding. |
| `db_view(state_home)` | Async context manager: open DB → yield → close DB, for post-run assertions. |

## 6. e2e tests — direct `core.run()` calls (spec 15)

E2e tests exercise the full pipeline by calling `cli.core.run()` directly — no
subprocess, no `CliRunner`, no monkeypatching of internal helpers. This is the
key design fix called out by spec 15.

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

### 6.1 Lifespan ownership

`core.run()` owns its own lifespan: it calls `init_db(state_home)` at start and
`close_db()` at exit. Any post-run DB query (for assertions) must therefore
re-initialize the DB. The `seed_config` and `db_view` async context managers
(in `tests/e2e/conftest.py`, spec 15 §2.4.3) wrap the pre-run seeding and
post-run query boilerplate so cases never write raw `init_db`/`close_db`/`try/finally`.

### 6.2 What is mocked vs real (e2e)

| External service | Strategy | Rationale |
|---|---|---|
| GitHub API (gidgethub) | `aioresponses` | Mocks `aiohttp.ClientSession._request`, covers all aiohttp callers including gidgethub; real gidgethub parsing/pagination runs. **Only** mock for GitHub API paths (repo release/owner discovery, proposal RFC PR title). |
| Local git (`git` subprocess) | Real git via `patch_clone_local` + local bare git repo fixture | Spec 07 invokes `git` via asyncio subprocess; the fixture replaces only the remote URL with a local `file://` path, all downstream git operations run for real. |
| Miniflux (feed integration) | **Real Miniflux + Postgres via Docker Compose** | The feed integration's value is talking to real Miniflux; a mock cannot catch JSON drift. `tests/e2e/feed/docker-compose.yml` brings up the stack; `tests/e2e/feed/conftest.py` waits for healthcheck and creates an API key. |
| AI providers | Pydantic AI `TestModel` / `FunctionModel` + `agent.override` | Real agent run-loop executes; only the LLM backend is replaced. |
| SMTP | `aiosmtpd` local server | Fully controllable, real SMTP protocol. |
| HTTP server (changelog fetch / proposal RFC PR / markpost / feishu / webhook) | `pytest-httpserver` | Real local HTTP server; covers every non-gidgethub HTTP egress. `aioresponses` cannot be autouse because it would also intercept httpserver traffic (spec 15 §3.2). |
| Bugsink / observability | Stubbed via `_stub_observability` autouse (root conftest) | Error-collector only; trivial to verify separately. |
| SQLite / filesystem / Jinja templates | Real | Fully controllable in-process; never mock. |

## 7. Component tests — FastAPI routes via httpx ASGITransport (spec 15)

FastAPI route tests (formerly the `tests/api/` layer, now in `tests/component/`)
drive the real app in-process:

```python
async with LifespanManager(app):
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        resp = await client.get("/api/v1/reports")
```

- Replaces the legacy sync `TestClient` (which runs the async lifespan in a
  separate thread/loop and breaks tortoise-orm's contextvar-bound connection).
- `asgi-lifespan.LifespanManager` drives the FastAPI lifespan so `init_db` runs
  before any request.

### 7.1 Error-handler testing caveat

Starlette's `@app.exception_handler(Exception)` routes to
`ServerErrorMiddleware` (not `ExceptionMiddleware`). `ServerErrorMiddleware`
always re-raises after handling, and `httpx.ASGITransport` defaults to
`raise_app_exceptions=True`. To test 500 responses, construct the transport
with `raise_app_exceptions=False`:

```python
transport = ASGITransport(app=app, raise_app_exceptions=False)
```

## 8. Config tests — direct `CoreConfig` construction (spec 02)

Tests construct `CoreConfig` directly with only the fields they care about;
everything else defaults (spec 02 zero-config):

```python
cfg = CoreConfig(
    state_home=tmp_state_home,
    github=GitHubConfig(gh_token=SecretStr("test-token")),
    analysis=AnalysisConfig(provider="anthropic", api_key=SecretStr("test-key")),
)
```

`tests/unit/test_config.py` and `tests/component/test_config.py` cover config
loading, section-level schema validation, secret masking, and DB-backed
upsert/reload.

## 9. Unit tests — narrow and pure

Unit tests live in `tests/unit/` and target a single module or class. They
inject fakes for collaborators and perform no IO. The unit layer covers:

- `cli/core.py` orchestration is covered by e2e (direct `core.run` calls), not
  by unit tests.
- `tests/unit/test_config.py` uses direct `CoreConfig` construction.
- Notification / scrub / text / timezone / markdown / i18n / git_url / changelog
  parsers / proposal sources all have narrow unit tests.
- Per-integration pure functions (parsers, `normalize`, `should_notify`, status
  enums, template selection) live here per spec 15 §1.2 — see each
  integration's spec (`specs/integrations/*.md`) for the full acceptance list.

## 10. CI (CI spec)

All Python tests run in a single CI job (`python-tests` in `ci.yml`) using the
**same command as local**: `uv run pytest`. The job brings up the Miniflux +
Postgres stack via `docker compose -f tests/e2e/feed/docker-compose.yml` before
running, and tears it down afterwards. Coverage (injected via `addopts`) flows
to codecov.

Browser e2e (`web/e2e/`) runs in a separate workflow (`e2e.yml`) that fires only
when `src/`, `web/`, `docker/`, or `web/e2e/` change.

Drift checks (OpenAPI / i18n / migrations / TS types) are a separate CI concern
(`drift-checks` job); see the CI spec for orchestration.

## 11. Frontend tests (spec 13)

- **Vitest + Testing Library + msw** for component-level tests (`web/`).
- **Playwright** for browser e2e covering real user interaction flows
  (`web/e2e/`).
- **`openapi-typescript`** generates types from the OpenAPI schema, so frontend
  API calls are type-checked at compile time.
