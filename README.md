English | [简体中文](README_zh.md)

<div align="center">

# Progress

**Trace multi-repo code changes, run AI analysis, and deliver progress reports for the open-source projects you follow.**

[![Python](https://img.shields.io/badge/Python-3.12+-3776AB?logo=python&logoColor=white)](https://www.python.org/)
[![Docker](https://img.shields.io/badge/Docker-Ready-2496ED?logo=docker)](https://www.docker.com/)
[![FastAPI](https://img.shields.io/badge/FastAPI-0.115+-009688?logo=fastapi)](https://fastapi.tiangolo.com/)
[![Next.js](https://img.shields.io/badge/Next.js-16-000000?logo=next.js)](https://nextjs.org/)

</div>

---

## Features

- 📊 **Multi-repo Monitoring** — Track commits and releases across many GitHub repositories at once
- 🤖 **AI-Powered Analysis** — Turn raw diffs into concise Markdown change reports via Claude Code or OpenAI Codex
- 📝 **Proposal Tracking** — Watch EIP / ERC / PEP / RFC / DEP proposals and notify on status changes
- 📋 **Changelog Tracking** — Detect new versions from arbitrary changelog URLs
- 📬 **Notifications** — Deliver reports to Feishu, email, or any webhook
- 🌐 **Web Dashboard** — Browse aggregated reports, edit live config, and subscribe via RSS
- 🐳 **Single-Container Deploy** — One Docker image (Caddy + FastAPI + Next.js), ready in a minute

## How It Works

1. **Clone & diff** — Progress fetches each configured repository and computes the diff since the last run
2. **Analyze** — The diff is sent to an AI provider (Claude Code or Codex), which produces a human-readable summary
3. **Publish** — Reports are stored in the database, optionally uploaded to [Markpost](https://github.com/jukanntenn/markpost), and pushed to your notification channels
4. **Schedule** — A cron expression triggers the whole pipeline on the cadence you choose

## Quick Start

For the full guide, see [docs/deployment.md](docs/deployment.md).

1. Prepare the configuration, AI credentials, and data directory:

   ```bash
   cp config.example.toml config.toml
   cp ~/.claude/settings.json ./claude_settings.json   # Claude Code credentials
   mkdir -p data
   ```

2. Edit `config.toml` — at minimum set `github.gh_token` and add a `[[repos]]` entry (see [Configuration](#configuration)).

3. Create `docker-compose.yml`:

   ```yaml
   services:
     progress:
       image: jukanntenn/progress:latest
       container_name: progress
       ports:
         - "5000:5000"
       volumes:
         - ./config.toml:/app/config.toml:ro
         - ./claude_settings.json:/root/.claude/settings.json:ro
         - ./data:/app/data
       environment:
         - PROGRESS_SCHEDULE_CRON=0 8 * * *   # daily at 08:00
       restart: always
   ```

4. Start the container, then open the web UI at `http://<your-host>:5000`:

   ```bash
   docker compose up -d
   docker compose logs -f
   ```

   When `PROGRESS_SCHEDULE_CRON` is set, Progress runs the pipeline once on startup and then on the given cron schedule. Leave it unset to drive runs manually with `docker compose exec progress progress check`.

## Configuration

Application configuration lives in the **database**. `config.toml` is a one-time **seed** plus the provider of infrastructure settings (`data_dir`, db path, schedule). After the first run, the database is the source of truth — edit ongoing settings through the **web UI** (`/config` page) or the API, and run `progress config import` to re-seed from the file.

See [guides/config.md](guides/config.md) for the full model. A minimal seed:

```toml
language = "en"

[github]
gh_token = "ghp_xxxxxxxxxxxxxxxxxxxx"   # required

[analysis]
provider = "claude_code"                # "claude_code" | "codex" | "truncate"

[[repos]]
url = "vitejs/vite"                     # "owner/repo", HTTPS, or SSH URL

[[repos]]
url = "facebook/react"
```

Override any value through environment variables using the `PROGRESS_` prefix (nested keys separated by `__`):

```bash
PROGRESS_TIMEZONE="Asia/Shanghai"
PROGRESS_GITHUB__GH_TOKEN="ghp_xxx"
PROGRESS_ANALYSIS__PROVIDER="codex"
PROGRESS_DATA_DIR="/app/data"
```

## Web Service

The container exposes a web UI and JSON API on port `5000`:

| Path                  | Description                                      |
| --------------------- | ------------------------------------------------ |
| `/`                   | Aggregated report browser (paginated)            |
| `/report/<id>`        | Full content of a single report                  |
| `/config`             | Live configuration editor (writes to the DB)     |
| `/api/v1/reports`     | Report list and detail (JSON)                    |
| `/api/v1/rss`         | RSS feed of the latest reports                   |
| `/api/v1/config`      | Read / write the live configuration (JSON)       |

## Development

See [docs/development.md](docs/development.md).
