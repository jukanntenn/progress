English | [简体中文](README_zh.md)

<div align="center">

# Progress

**Trace multi-repo code changes, run AI analysis, and deliver progress reports for the open-source projects you follow.**

[![CI](https://github.com/jukanntenn/progress/actions/workflows/ci.yml/badge.svg?branch=main)](https://github.com/jukanntenn/progress/actions/workflows/ci.yml)
[![Python](https://img.shields.io/badge/Python-3.12+-3776AB?logo=python&logoColor=white)](https://www.python.org/)
[![Docker](https://img.shields.io/badge/Docker-Ready-2496ED?logo=docker)](https://www.docker.com/)
[![FastAPI](https://img.shields.io/badge/FastAPI-0.115+-009688?logo=fastapi)](https://fastapi.tiangolo.com/)
[![Vite](https://img.shields.io/badge/Vite-React%2019-646CFF?logo=vite&logoColor=white)](https://vite.dev/)

</div>

---

## Features

- 📊 **Multi-repo Monitoring** — Track commits and releases across many GitHub repositories at once
- 🤖 **AI-Powered Analysis** — Turn raw diffs into concise Markdown change reports via any [Pydantic AI](https://ai.pydantic.dev/) provider (Anthropic, OpenAI, OpenAI-compatible endpoints)
- 📝 **Proposal Tracking** — Watch EIP / ERC / PEP / RFC / DEP proposals and notify on status changes
- 📋 **Changelog Tracking** — Detect new versions from arbitrary changelog URLs
- 📰 **Feed Integration** — Ingest starred/owned RSS feeds from a Miniflux instance and analyze new entries
- 📬 **Notifications** — Deliver reports to Feishu, email, or the console
- 🌐 **Web Dashboard** — Browse aggregated reports, edit live config through the UI, and subscribe via RSS
- 🔭 **Observability** — Structured logging, OpenTelemetry traces, and error capture via [Bugsink](https://www.bugsink.com/)
- 🌍 **Internationalization** — Babel-extracted message catalogs (English + 简体中文)
- 🐳 **Single-Container Deploy** — One hardened image (Caddy + FastAPI + Vite SPA, supervised by s6-overlay with a supercronic scheduler), ready in a minute

## How It Works

1. **Clone & diff** — Progress fetches each configured repository and computes the diff since the last run
2. **Analyze** — The diff is sent to an AI provider (e.g. `anthropic:claude-sonnet-4`), which produces a human-readable summary
3. **Publish** — Reports are stored in the database, optionally uploaded to [Markpost](https://github.com/jukanntenn/markpost), and pushed to your notification channels
4. **Schedule** — A cron expression triggers the whole pipeline on the cadence you choose

## Quick Start

For the full guide, see [docs/deployment.md](docs/deployment.md).

1. Prepare the configuration and data directory:

   ```bash
   cp config.example.db.toml config.db.toml   # DB seed (credentials, repos, channels)
   cp config.example.toml      config.toml     # infrastructure (state_home)
   mkdir -p data
   chown 100:101 data                          # image runs as uid 100 / gid 101
   ```

2. Edit `config.db.toml` — at minimum set `[core.github].gh_token`, `[core.analysis]`, and add a `[[repo.repos]]` entry (see [Configuration](#configuration)).

3. Create `docker-compose.yml`:

   ```yaml
   services:
     progress:
       image: ghcr.io/jukanntenn/progress:latest
       container_name: progress
       ports:
         - "5000:5000"
       user: "100:101"
       read_only: true
       tmpfs:
         - /tmp
         - /run:rw,exec,mode=0755,uid=100,gid=101
         - /home/progress
       cap_drop: ["ALL"]
       security_opt: ["no-new-privileges:true"]
       volumes:
         - ./config.toml:/app/config.toml:ro
         - ./data:/app/data
       environment:
         - TZ=UTC
         - S6_READ_ONLY_ROOT=1
         - PROGRESS_SCHEDULE_CRON=0 8 * * *   # daily at 08:00
       restart: unless-stopped
   ```

4. Start the container, then open the web UI at `http://<your-host>:5000`:

   ```bash
   docker compose up -d
   docker compose logs -f
   ```

   When `PROGRESS_SCHEDULE_CRON` is set, Progress runs the pipeline once on startup and then on the given cron schedule. Leave it unset to drive runs manually with `docker compose exec progress progress run`.

## Configuration

Progress uses a **two-file** config model:

- **`config.toml`** (Ansible-class) — infrastructure only, currently just `state_home` (where `progress.db`, logs, and cloned repos live). See `config.example.toml`.
- **`config.db.toml`** (DB seed) — application config that is imported into the database on startup. Copy `config.example.db.toml` to seed it. After the first run the **database is the source of truth** — edit ongoing settings through the **web UI** (`/config` page) or the API (`PUT /api/v1/config/{section}`), or edit `config.db.toml` and restart to re-seed.

Priority: **DB > seed (`config.db.toml`) > code defaults**; env-var overrides (`PROGRESS_` prefix) apply on top during seeding. Missing credentials (`gh_token`, `api_key`) degrade gracefully — the affected integration is disabled with a warning rather than crashing (zero-config).

See [docs/config.md](docs/config.md) for the full model. A minimal `config.db.toml` seed:

```toml
[core]
language = "en"
timezone = "UTC"

[core.github]
gh_token = "ghp_xxxxxxxxxxxxxxxxxxxx"        # empty -> GitHub tracking disabled

[core.analysis]
provider = "anthropic"                        # any Pydantic AI provider
model = "claude-sonnet-4"
api_key = "sk-xxxxxxxxxxxxxxxx"               # empty -> AI analysis disabled

[[core.notification.channels]]
type = "console"                              # console | email | feishu
enabled = true

[repo]
first_run_lookback_commits = 3

[[repo.repos]]
url = "vitejs/vite"                           # "owner/repo", HTTPS, or SSH URL
branch = "main"
enabled = true
```

Override any value through environment variables using the `PROGRESS_` prefix (nested keys separated by `__`):

```bash
PROGRESS_CORE__TIMEZONE="Asia/Shanghai"
PROGRESS_CORE__GITHUB__GH_TOKEN="ghp_xxx"
PROGRESS_CORE__ANALYSIS__PROVIDER="openai"
PROGRESS_STATE_HOME="/app/data"
```

## Web Service

The container exposes a web UI and JSON API on port `5000`:

| Path                          | Description                                            |
| ----------------------------- | ------------------------------------------------------ |
| `/healthz`, `/readyz`         | Liveness / readiness probes (k8s-style)                |
| `/reports`                    | Aggregated report browser (root `/` redirects here)    |
| `/reports/:id`                | Full content of a single report                        |
| `/integrations`               | Per-integration status overview                        |
| `/config`                     | Live configuration editor (writes to the DB)           |
| `/api/v1/version`             | Build/version info (JSON)                              |
| `/api/v1/reports`             | Report list and detail (JSON)                          |
| `/api/v1/integrations`        | Integration status (JSON)                              |
| `/api/v1/config`              | Read the live configuration (JSON)                     |
| `/api/v1/config/schema`       | JSON Schema of the config model                        |
| `PUT /api/v1/config/{section}`| Update one config section                              |
| `/api/v1/rss`                 | RSS feed of the latest reports                         |

## Development

See [docs/development.md](docs/development.md). Requirements: Python 3.12+ with [uv](https://github.com/astral-sh/uv), Node 22+ with [pnpm](https://pnpm.io/) 11+ for the frontend.

Quality gates (run the same checks locally as CI does):

```bash
uv sync --extra dev
uv run ruff check && uv run ruff format --check
uv run ty check
uv run pytest -m "not e2e or (e2e and not feed)"

cd web && pnpm install && pnpm lint && pnpm typecheck && pnpm test && pnpm build
```

Further reading in [`docs/`](docs/): [config.md](docs/config.md), [deployment.md](docs/deployment.md), [development.md](docs/development.md), [observability.md](docs/observability.md), [testing.md](docs/testing.md).
