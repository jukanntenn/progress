# Development Guide

## Prerequisites

| Tool              | Version | Description                                     | Install                                                                                             |
| ----------------- | ------- | ----------------------------------------------- | --------------------------------------------------------------------------------------------------- |
| Python            | 3.12+   | Backend language                                | [python.org/downloads](https://www.python.org/downloads/)                                           |
| uv                | 0.9+    | Python package / project manager                | [docs.astral.sh/uv](https://docs.astral.sh/uv/getting-started/installation/)                        |
| Node.js           | 22+     | Frontend runtime                                | [nodejs.org](https://nodejs.org/)                                                                   |
| pnpm              | 11+     | Frontend package manager                        | [pnpm.io/installation](https://pnpm.io/installation/)                                               |
| prek              | latest  | Git pre-commit hooks (ruff/ty/eslint)           | `uv tool install prek` ([j178/prek](https://github.com/j178/prek))                                  |
| GitHub CLI (`gh`) | latest  | Initial repository clone                        | [cli.github.com](https://cli.github.com/)                                                           |

## Quick Start

### Install dependencies

```bash
uv sync --extra dev   # backend (includes dev/test tooling)
cd web && pnpm install && cd ..   # frontend
prek install          # git pre-commit hooks (once per clone)
```

### Option 1 — VS Code tasks (recommended)

The project ships `.vscode/tasks.json`. Open the Command Palette
(`Ctrl+Shift+P`) → **Tasks: Run Task** → pick one:

- **Start All** — runs backend and frontend in parallel
- **Start Backend** — `uv run fastapi dev` on port 8000 (hot reload)
- **Start Frontend** — `pnpm dev` in `web/` (Vite HMR) on port 5173

### Option 2 — Manual

**Backend** (FastAPI with hot reload):

```bash
uv run fastapi dev
```

**Frontend** (Vite HMR):

```bash
cd web
pnpm dev
```

The Vite dev server runs on [http://localhost:5173](http://localhost:5173) and
proxies `/api/*`, `/healthz`, `/readyz` to the backend at
`http://127.0.0.1:8000` (see `web/vite.config.ts`).

> No `config.toml` is needed for local dev. The backend reads `state_home` from
> the `PROGRESS_STATE_HOME` env var (default `"data"` relative to the cwd). The
> VS Code tasks set `PROGRESS_STATE_HOME` to `${workspaceFolder}/data`.

### Debug (VS Code)

`.vscode/launch.json` provides **FastAPI (debug)** — F5 to start uvicorn under
debugpy with breakpoints and `--reload`. There is also an **Attach** config for
connecting to a debugpy session on port 5678.

## Lint & Format

```bash
uv run ruff check .       # backend linter
uv run ruff format .      # backend formatter
uv run ty check           # backend type checker
prek run --all-files      # everything (ruff + ty + eslint + prettier + hygiene)
```

Frontend:

```bash
cd web
pnpm lint                 # ESLint
pnpm format               # Prettier
pnpm typecheck            # tsc --noEmit
```

## Run Tests

**Backend:**

```bash
uv run pytest -v                          # all tests
uv run pytest tests/test_repo.py -v       # single file
```

**Frontend:**

```bash
cd web
pnpm test                 # Vitest, single run (CI)
pnpm test:watch           # Vitest in watch mode
```

**End-to-end (Playwright, requires Docker):**

```bash
docker compose -f docker/docker-compose.local.yml up -d --build --wait
cd web/e2e && pnpm install && pnpm exec playwright install chromium && pnpm test
docker compose -f docker/docker-compose.local.yml down -v
```

See [docs/testing.md](testing.md) for test-layer conventions.

## Configuration

Local dev needs **no** `config.toml`. `state_home` is taken from the
`PROGRESS_STATE_HOME` env var (set by the VS Code tasks, defaults to `"data"`).

Application config (language, credentials, business tuning) lives in the
**database** `config` table — edit it via the web UI (`/config`) or
`PUT /api/v1/config/{section}`. A `config.db.toml` seed file next to your config
is re-imported on every startup if present.

Env-var overrides use the `PROGRESS_` prefix with `__` for nesting:

```bash
PROGRESS_STATE_HOME="/app/data"
PROGRESS_TIMEZONE="Asia/Shanghai"
PROGRESS_LANGUAGE="en"
PROGRESS_GITHUB__GH_TOKEN="ghp_your_token_here"
```

See [docs/config.md](config.md) for the full model and
[docs/deployment.md](deployment.md) for runtime/Docker configuration.

## Database Migrations

See [docs/migrations.md](migrations.md). The wrapper `scripts/migration.py`
covers generate/apply/preview/rollback/drift-check.

## Drift Checks

`scripts/check_drift.py` is the single source of truth for every drift /
regression check that CI runs. Run it locally before pushing to catch what CI
will catch — local and CI invoke the same script, so the two paths can never
drift apart.

```bash
uv run python scripts/check_drift.py
```

It runs the seven checks from CI's `drift-checks` job, each with a banner and
`[OK]` / `[FAIL]` summary:

1. **deptry** — declared-but-unused / used-but-undeclared dependencies.
2. **import-linter** — forbidden cross-layer imports ([tool.importlinter]).
3. **OpenAPI drift** — `web/openapi.json` matches what FastAPI produces.
4. **Frontend type drift** — `web/src/api/schema.ts` matches `openapi.json`.
5. **i18n .pot drift** — `src/progress/locales/progress.pot` matches freshly
   extracted strings (POT-Creation-Date is stripped — non-deterministic).
6. **i18n catalog lint** — no fuzzy / empty / obsolete `.po` entries.
7. **Migration drift** — every model change has a matching migration file.

Prerequisites: `uv sync --extra dev` and `pnpm --dir web install` (the latter
for the frontend type-drift check). A clean working tree is **not** required —
the checks diff against `HEAD`, so uncommitted source changes surface as drift
(intentional; commit or stash first if you want to isolate a single check).

The OpenAPI and `.pot` checks leave their freshly regenerated artifacts on
disk after running (mirroring CI). Re-commit them if the regeneration is the
intended update, otherwise `git checkout -- <path>` to discard.

## CLI

```bash
uv run progress run -c config.toml       # run the full pipeline
uv run progress serve -c config.toml     # serve the API
```

## Internationalization

```bash
uv run python scripts/makemessages.py      # extract strings → locales/*.pot + update .po
uv run python scripts/compile_messages.py  # compile *.po → *.mo
```

See [docs/i18n.md](i18n.md) for details.

## Observability

OpenTelemetry traces/metrics export to local JSON-Lines files, and crashes are
forwarded to a Bugsink (Sentry-compatible) server. Configure under
`[observability]` in the DB config table.

See [docs/observability.md](observability.md) for setup.
