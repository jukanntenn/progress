# Progress

Progress is a GitHub project tracking tool that traces multi-repo code changes, runs AI analysis, and generates reports to help users track open-source project progress.

## Project Structure

Keep this section up to date with the project structure. Use it as a reference to find files and directories.

```text
progress/
├── pyproject.toml          # uv single source of truth (deps + project config)
├── uv.lock                 # uv lockfile
├── prek.toml               # pre-commit hooks (backend ruff/ty + builtin); frontend in web/prek.toml (workspace)
├── babel.cfg               # Babel extraction config (i18n, spec 11)
├── config.example.toml     # Example Ansible-class config (spec 02)
├── README.md / README_zh.md
├── AGENTS.md               # This file (workspace instructions)
├── CLAUDE.md               # Mirrors AGENTS.md verbatim
│
├── src/progress/           # ── Python backend (src-layout, spec 01)──
│   ├── __init__.py         # __version__ + __all__
│   ├── __main__.py         # `python -m progress` support
│   ├── errors.py           # Structured exception hierarchy
│   │
│   ├── config/             # Shared: config system (spec 02)
│   │   ├── __init__.py     # public facade (exports CoreConfig)
│   │   ├── root.py         # CoreConfig (top-level aggregate root)
│   │   ├── loader.py       # layered sources loading + DB seed merge
│   │   └── schema.py       # get_config_json_schema() (lru_cache)
│   │
│   ├── db/                 # Shared: data layer (spec 03)
│   │   ├── __init__.py     # init_db/close_db + get_config/set_config/get_all_config
│   │   ├── base.py         # BaseModel (abstract, auto-refresh updated_at)
│   │   ├── tortoise_config.py  # build_tortoise_config + TORTOISE_ORM (CLI/runtime shared)
│   │   ├── migrations/     # core migrations (Report/Batch/Config)
│   │   └── models/         # core state models (report/batch/config)
│   │
│   ├── integrations/       # Shared: business plugins (spec 06, Django-app style)
│   │   ├── __init__.py
│   │   ├── base.py         # Integration Protocol + Components + RunResult
│   │   ├── registry.py     # @register + entry_points discovery
│   │   ├── repo/           # repo integration (self-contained)
│   │   │   ├── __init__.py # @register("repo")
│   │   │   ├── config.py models.py tracker.py
│   │   │   ├── migrations/ templates/ locales/ prompts/
│   │   ├── changelog/      # changelog integration (same self-contained layout)
│   │   ├── proposal/       # proposal integration (same self-contained layout)
│   │   └── feed/           # feed integration (Miniflux RSS; same self-contained layout)
│   │
│   ├── observability/      # Shared: OTel + structlog + Bugsink (spec 04)
│   │   ├── __init__.py     # setup_observability / shutdown_observability
│   │   ├── logging.py      # structlog + TimedRotatingFileHandler
│   │   ├── telemetry.py    # OTel provider/sampler/exporter + auto-instrument
│   │   ├── scrub.py        # unified secret redaction
│   │   ├── metrics.py      # @observed decorator + record_business_event
│   │   └── config.py       # BugsinkConfig (Web-class)
│   │
│   ├── utils/              # Shared: pure helpers (spec 01)
│   │   ├── __init__.py
│   │   ├── http.py         # aiohttp session_factory + tenacity retry_async + HTTP_TIMEOUT
│   │   ├── templating.py   # Jinja2 engine factory (select_autoescape)
│   │   ├── markdown.py     # markdown-it-py + nh3 sanitize
│   │   ├── timezone.py / text.py / i18n.py
│   │
│   ├── cli/                # CLI entry package (spec 05; symmetric with api/)
│   │   ├── __init__.py     # empty (package marker only — import-free to avoid circular import)
│   │   ├── main.py         # typer app + command definitions (thin, CLI entry module)
│   │   ├── core.py         # run() business orchestration (thick, e2e-callable)
│   │   ├── lifespan.py     # @asynccontextmanager CLI process lifespan
│   │   ├── outcome.py      # RunOutcome + exit_code (0/1/2)
│   │   ├── reports/        # report pipeline (spec 09) + templates/reports/ + prompts/
│   │   ├── notifications/  # Channel/Renderer/Dispatcher (spec 10) + channels/ + templates/report/
│   │   ├── ai/             # Pydantic AI agent (spec 08)
│   │   └── git/            # gidgethub GitHub client + asyncio-subprocess local git (spec 07)
│   │
│   └── api/                # FastAPI entry package (spec 12; symmetric with cli/)
│       ├── __init__.py     # create_app + lifespan + middleware registration
│       ├── main.py         # app = create_app() (ASGI entry)
│       ├── routes/         # {config,reports,integrations,rss,system}.py + _limiter.py
│       ├── deps.py / middleware.py / errors.py / schemas.py / markdown.py
│       └── locales/
│
├── web/                    # Frontend (top-level Vite SPA, spec 13) + web/e2e/ (Playwright)
│   └── prek.toml           # web/ workspace project: eslint + prettier (native CWD, no shim)
│
├── tests/                  # unit/component/e2e test layers (spec 15)
│   ├── unit/               # pure-function / single-class tests (fakes, no IO)
│   ├── component/          # mocked external services + real SQLite/git + FastAPI ASGI
│   ├── e2e/                # real external services, direct core.run() calls
│   │   ├── feed/ repo/ proposal/ changelog/  # per-integration e2e
│   │   └── test_all_integrations_*.py
│   └── conftest.py
├── docker/                 # 2-process (Caddy + uvicorn) container (spec 14)
│   ├── Dockerfile docker-compose.yml docker-compose.local.yml Caddyfile build.py
│   └── s6/                 # s6-overlay service definitions
├── devops/                 # ansible/ deployment
├── scripts/                # migration.py + export_openapi.py + check_translations.py + check_drift.py + makemessages.py + compile_messages.py
├── docs/                   # single docs tree (spec 01)
├── specs/redesign/         # authoritative redesign specs (00-17)
└── data/                   # runtime products (gitignored): progress.db, logs/, repos/, observability/
```

## Commands

Install dependencies:

```bash
uv sync --extra dev          # backend (includes ruff/ty/pytest/deptry)
cd web && pnpm install       # frontend
prek install                 # git pre-commit hooks (once per clone)
```

Run application:

```bash
uv run progress run -c config.toml    # run the full pipeline
uv run progress serve -c config.toml  # serve the API
```

Serve API (dev, hot reload, no config.toml needed):

```bash
uv run fastapi dev                    # backend on :8000 (VS Code task sets PROGRESS_STATE_HOME)
cd web && pnpm dev                    # frontend on :5173 (proxies /api to :8000)
```

Lint / format / type-check:

```bash
uv run ruff check                     # backend linter
uv run ruff format                    # backend formatter
uv run ty check                       # backend type checker
uv run deptry .                       # dependency hygiene (unused / undeclared)
prek run --all-files                  # everything (ruff + ty + eslint + prettier + hygiene)
./scripts/check_drift.py              # all 7 drift checks CI runs (deptry / import-linter / OpenAPI / TS types / i18n .pot + catalog / migrations)
uv run python scripts/check_drift.py  # (equivalent — preferred form in docs)
```

Frontend:

```bash
cd web && pnpm lint      # ESLint
cd web && pnpm format    # Prettier
cd web && pnpm typecheck # tsc --noEmit
```

Tests:

```bash
uv run pytest -v                          # backend (all layers)
cd web && pnpm test                       # frontend (Vitest)
```

End-to-end (Playwright, needs Docker):

```bash
docker compose -f docker/docker-compose.local.yml up -d --build --wait
cd web/e2e && pnpm install && pnpm exec playwright install chromium && pnpm test
docker compose -f docker/docker-compose.local.yml down -v
```

Database migrations:

```bash
uv run python scripts/migration.py make <name>   # generate (semantic name required)
uv run python scripts/migration.py apply          # apply pending
uv run python scripts/migration.py sql <app> <id> # preview SQL
uv run python scripts/migration.py down <app>     # rollback
uv run python scripts/migration.py drift          # drift check (CI gate)
```

Generate DB migrations (low-level, prefer the wrapper above):

```bash
uv run tortoise -c progress.db.tortoise_config.TORTOISE_ORM makemigrations
```

## Tech Stack

- Programming Language: Python 3.12+
- Concurrency: asyncio (the whole runtime is async; CLI entry uses asyncio.run)
- Package and Project Manager: uv 0.9+
- CLI Framework: Typer 0.26+
- Web Framework: FastAPI 0.115+ (async routes + lifespan)
- ORM: tortoise-orm 1.1.7+ (async; aiosqlite driver, SQLite backend)
- Async HTTP: aiohttp 3.10.x (pinned <3.11 so the `aioresponses` test mock — used for the gidgethub/GitHub API path in e2e, spec 15 §3.1 — stays compatible)
- Async SMTP: aiosmtplib 3.0+
- Async file I/O: aiofiles 24.1+
- Frontend: React 19 + TypeScript + Vite + Tailwind CSS v4 (top-level SPA, spec 13)
- Frontend UI: @base-ui/react + class-variance-authority
- Frontend Data Fetching: @tanstack/react-query v5 + openapi-react-query + openapi-fetch
- Frontend i18n: i18next + react-i18next (en / zh-hans)
- Frontend Routing: react-router
- Frontend Package Manager: pnpm
- RSS Generation: feedgen
- Markdown Rendering: markdown-it-py (CommonMark compliant with GitHub style)
- Containerized development and deployment: Docker
- Git Operations: GitPython 3.1.46+ (sync; bridged to async via asyncio.to_thread)
- GitHub API: gidgethub (async) + PyGithub 2.8.1+ (sync; bridged via asyncio.to_thread)
- Miniflux Client: miniflux 1.1.6+ (sync; bridged to async via asgiref.sync_to_async, spec feed §9)
- Async↔Sync Bridge: asgiref 3.8.0+ (sync_to_async, thread_sensitive for requests.Session safety)
- GitHub CLI: GitHub CLI (gh) - only for initial repository clone

## Standards

MUST FOLLOW THESE RULES, NO EXCEPTIONS

- All imports must be placed at the beginning of the file
- DO NOT write comments (Except for existing comments) – use self-documenting code instead. When necessary, only add meaningful comments explaining why (not what) something is done
- Prefer using dbhub MCP instead of bash commands for database-related operations
- Prefer using Context7 MCP when need library/API documentation, code generation, setup or configuration steps without having to explicitly ask
- Prior to running any external tool (e.g., gh, claude) within the code, it is recommended to verify its usage by using the help parameter (e.g., `gh repo clone --help`)
- English shall be used for comments, documentation, log messages and exception information in code except for those intended to be targeted to other languages (e.g., Chinese documentation / prompt files)
- For adding or modifying configuration items, refer to `docs/config.md`
- For development server usage, refer to `docs/development.md`
- For writing test code, refer to `docs/testing.md`
- For i18n, refer to the `src/progress/locales/` catalogs and `scripts/makemessages.py` / `scripts/compile_messages.py`
- For database migrations, refer to `docs/migrations.md`
- For AI agent hooks, refer to `docs/agent-hooks.md`

## Boundaries

### Always do

- Follow every rule in **Standards** above.
- After editing a pydantic config model: regenerate the OpenAPI contract so the frontend stays in sync — `uv run python scripts/export_openapi.py` (then commit `web/openapi.json`).
- After editing a tortoise model: generate a migration — `uv run python scripts/migration.py make <name>`.
- After editing i18n strings: regenerate and compile catalogs — `uv run python scripts/makemessages.py` then `uv run python scripts/compile_messages.py`.

### Ask first

- Editing the authoritative redesign specs under `specs/redesign/00-17` (they are the design contract).
- Editing an already-applied migration history file (rewriting history breaks deployed DBs).
- Deleting a test case.
- Editing `docker/Dockerfile` or `docker/Caddyfile` (affects the production image).

### Never do

- Commit secrets, `config.toml`, `*.db`, `.env`, or any `data/` runtime artifact (all gitignored; do not work around it).
- Edit anything under `.venv/`.
- Bypass pre-commit hooks (`git commit --no-verify`).
- Weaken or remove observability/security-related code without providing a replacement.

## Testing

Tests are layered (spec 15); each layer has a marker and lives in its own directory:

- `tests/unit/` — pure functions / single class, injected fakes, no IO.
- `tests/component/` — mocked external services + real SQLite/git; includes FastAPI route tests (httpx ASGITransport).
- `tests/e2e/` — end-to-end against real external services (direct `core.run()` calls); feed e2e needs real Miniflux + Postgres via Docker Compose.
- `web/e2e/` — Playwright browser e2e against the real production container (separate Node/pnpm suite).

Local and CI use the **identical** command: `uv run pytest` (coverage is always on via `addopts`). Markers are auto-applied by directory in `conftest.py`. The feed e2e suite needs Docker (real Miniflux + Postgres); CI brings the stack up before running. See `docs/testing.md` for conventions and `docs/development.md` for the run commands.

## Database Migrations

tortoise-orm's built-in CLI (not aerich) manages schema migrations. Use the `scripts/migration.py` wrapper (see Commands). Each app owns its `migrations/` directory; `init_db` applies pending migrations on startup. CI runs `scripts/migration.py drift` to reject a model change without a matching migration. See `docs/migrations.md` for the full workflow.

## CI / CD

GitHub Actions workflows under `.github/workflows/`:

- `ci.yml` — lint (ruff), type-check (ty), tests (unit/component/e2e, feed e2e included via Docker compose), frontend (lint/typecheck/test/build), drift checks (`scripts/check_drift.py` — deptry / import-linter / OpenAPI / TS types / i18n .pot + catalog / migrations), Docker build smoke. Runs on every push to `main` and every PR.
- `codeql.yml` — security analysis (Python).
- `release.yml` — multi-arch Docker image to GHCR on `v*` tags + GitHub Release.
- `e2e.yml` — Playwright browser e2e against the production container; fires only when `src/`, `web/src/`, `docker/`, or `web/e2e/` change (docs-only edits do not trigger it).

## User & password management

The auth subsystem is always active (`src/progress/api/auth.py`). On first boot
with `auth.enabled=true` and an empty users table, an initial superuser is
created from `cfg.auth.initial_admin_username` / `initial_admin_password`; a
random password is printed to the logs once.

Manage users from the CLI (`progress users ...`, see `src/progress/cli/users.py`):

    uv run progress users list
    uv run progress users create <name> [--superuser] [-p <password>]
    uv run progress users reset-password <name> [-p <password>]   # random if -p omitted
    uv run progress users deactivate <name>

Self-service password change is in the Web UI (Settings page, top-right user
menu) and via `POST /api/v1/auth/change-password` (requires current password).

## Proposal Tracking

- Proposal tracking is one of the built-in `integrations` (spec 06). Configure the kinds to track via the `proposal` config section (see `config.example.toml` and spec 02).
- The `run` command dispatches every registered integration including proposal.
