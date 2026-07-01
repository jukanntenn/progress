# Development Guide

## Prerequisites

| Tool                    | Version  | Description                                     | Install                                                        |
| ----------------------- | -------- | ----------------------------------------------- | -------------------------------------------------------------- |
| Python                  | 3.12+    | Backend language                                | [python.org/downloads](https://www.python.org/downloads/)      |
| uv                      | 0.9+     | Python package / project manager                | [docs.astral.sh/uv](https://docs.astral.sh/uv/getting-started/installation/) |
| Node.js                 | 22+      | Frontend runtime                                | [nodejs.org](https://nodejs.org/)                              |
| pnpm                    | 11+      | Frontend package manager                        | [pnpm.io/installation](https://pnpm.io/installation)           |
| pre-commit              | latest   | Git pre-commit hooks (ruff, uv-lock)            | [pre-commit.com#install](https://pre-commit.com/#install)      |
| GitHub CLI (`gh`)       | latest   | Initial repository clone                        | [cli.github.com](https://cli.github.com/)                      |
| Claude Code CLI         | latest   | AI analysis provider (`provider = "claude_code"`) | [claude.com/product/claude-code](https://claude.com/product/claude-code) |
| Codex CLI (optional)    | latest   | Alternative AI provider (`provider = "codex"`)  | [developers.openai.com/codex](https://developers.openai.com/codex/) |

## Quick Start

### Option 1 — `dev.py` (recommended)

Starts the FastAPI backend and the Next.js frontend together, installing frontend dependencies on first run:

```bash
python3 devops/dev.py start   # start all services
python3 devops/dev.py stop    # stop all services
```

- **Backend API:** [http://localhost:5000/api/v1](http://localhost:5000/api/v1)
- **Frontend:** [http://localhost:3000](http://localhost:3000)

Logs are written to `devops/backend.log` and `devops/frontend.log`.

### Option 2 — VS Code / Cursor / compatible IDEs

The project ships `.vscode/tasks.json` with three tasks:

- **Start All** — runs backend and frontend in parallel
- **Start Backend** — launches `fastapi dev` with `PYTHONPATH=src` and `CONFIG_FILE=config.toml`
- **Start Frontend** — launches `pnpm dev` in `web/`

Open the Command Palette (`Ctrl+Shift+P`) → **Tasks: Run Task** → pick a task.

### Option 3 — Manual

**Backend** (FastAPI with hot reload):

```bash
PYTHONPATH=src CONFIG_FILE=config.toml uv run fastapi dev --port 5000
```

**Frontend** (Next.js with Turbopack):

```bash
cd web
pnpm dev
```

The dev server starts at [http://localhost:3000](http://localhost:3000).

> The frontend proxies `/api/*` to `BACKEND_URL`, which defaults to `http://127.0.0.1:5000` (see the rewrite in `web/next.config.ts`). That is why the backend above is started on port `5000`. To use a different backend port, create `web/.env.local` (gitignored) with `BACKEND_URL=http://127.0.0.1:8000`.

## Install Dependencies

`python3 devops/dev.py start` auto-installs frontend dependencies on first run. To install manually:

**Backend:**

```bash
uv sync                   # includes dev/test extras
```

**Frontend:**

```bash
cd web
pnpm install
```

## Lint

**Backend** (via pre-commit / ruff):

```bash
uv run ruff check .       # linter
uv run ruff format .      # formatter
pre-commit run --all-files
```

**Frontend:**

```bash
cd web
pnpm lint                 # ESLint
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
pnpm test           # Vitest, single run (CI)
pnpm test:watch     # Vitest in watch mode
pnpm test:coverage  # with coverage
```

See [guides/testing.md](../guides/testing.md) for conventions.

## Configuration

A working `config.toml` (next to the repo root) is required to start the backend. Copy the example and edit the required fields:

```bash
cp config.example.toml config.toml
```

- **Infrastructure** (`data_dir`, `workspace_dir`, db path): resolved every startup as **Environment Variables > config file > defaults**.
- **Application config**: the **database** is the source of truth. The file seeds it on first run; thereafter edit via the web UI (`/config`) or `progress config import` / `export`.

See [guides/config.md](../guides/config.md) for the full model and [docs/deployment.md](deployment.md) for runtime/Docker configuration.

### Environment Variables

Format: `PROGRESS_<SECTION>__<KEY>` — `PROGRESS_` prefix, `__` separates nested levels.

```bash
PROGRESS_TIMEZONE="Asia/Shanghai"
PROGRESS_LANGUAGE="en"
PROGRESS_GITHUB__GH_TOKEN="ghp_your_token_here"
PROGRESS_ANALYSIS__PROVIDER="claude_code"
PROGRESS_DATA_DIR="/app/data"
```

List/array values are not well supported via env vars — use `config.toml` or the web UI for those.

## CLI

Progress exposes a Click CLI (`uv run progress ...`):

```bash
uv run progress -c config.toml                    # run the full pipeline (default command)
uv run progress check                             # repository + proposal + changelog checks
uv run progress check --trackers-only             # proposal/changelog only, skip repos
uv run progress track-proposals                   # proposal trackers only
uv run progress config import                     # seed the DB blob from config.toml (file → DB)
uv run progress config import --force             # overwrite an already-seeded blob
uv run progress config export -o config.toml      # dump the DB blob to a file (DB → file)
```

## Internationalization

Generate and compile gettext messages:

```bash
scripts/makemessages.sh      # extract strings → locales/*.pot
scripts/compilemessages.sh   # compile *.po → *.mo
```

See [guides/i18n.md](../guides/i18n.md) for details.

## Observability

OpenTelemetry traces/metrics export to local JSON-Lines files, and crashes are forwarded to a Bugsink (Sentry-compatible) server. Configure under `[observability.otel]` and `[observability.bugsink]` in `config.toml`.

See [guides/observability.md](../guides/observability.md) for setup.
