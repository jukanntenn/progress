# Deployment Guide

## Docker Quick Start

### Docker Compose (Recommended)

1. Create a project directory and download the example config:

   ```bash
   mkdir -p ~/docker/progress && cd ~/docker/progress
   curl -fsSL https://raw.githubusercontent.com/jukanntenn/progress/refs/heads/main/config.example.toml -o config.toml
   ```

2. Edit `config.toml` — the following values **must** be changed before the first run:

   ```toml
   [github]
   gh_token = "ghp_your_github_token"          # required

   [analysis]
   provider = "claude_code"                    # "claude_code" | "codex" | "truncate"

   [[repos]]
   url = "owner/repo"                          # at least one repository
   ```

3. Provide AI provider credentials. For Claude Code, copy your local Claude Code settings into the project:

   ```bash
   cp ~/.claude/settings.json ./claude_settings.json
   ```

   Minimal `claude_settings.json`:

   ```json
   {
     "env": {
       "ANTHROPIC_BASE_URL": "https://api.anthropic.com",
       "ANTHROPIC_AUTH_TOKEN": "xxxxxxxx",
       "API_TIMEOUT_MS": "3000000"
     }
   }
   ```

   For Codex instead, mount `codex_config.toml` → `/root/.codex/config.toml` and `codex_auth.json` → `/root/.codex/auth.json` (see [AI Providers](#ai-providers)).

4. Create `docker-compose.yml`:

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
         - PROGRESS_SCHEDULE_CRON=0 8 * * *     # daily at 08:00
       healthcheck:
         test: ["CMD", "curl", "-fsS", "http://127.0.0.1:5000/api/v1/reports"]
         interval: 30s
         timeout: 5s
         retries: 3
         start_period: 30s
       restart: always
   ```

5. Start the container:

   ```bash
   docker compose up -d
   docker compose logs -f
   ```

   Open the web UI at `http://<your-host>:5000`.

### Single Container

For quick evaluation only — use Docker Compose for long-term deployments.

```bash
docker run -d \
  --name progress \
  -p 5000:5000 \
  -e PROGRESS_SCHEDULE_CRON="0 8 * * *" \
  -v "$PWD/config.toml:/app/config.toml:ro" \
  -v "$PWD/claude_settings.json:/root/.claude/settings.json:ro" \
  -v "$PWD/data:/app/data" \
  jukanntenn/progress:latest
```

## Container Architecture

Progress runs as a single container with four internal services managed by [s6-overlay](https://github.com/just-containers/s6-overlay):

- **Caddy** — reverse proxy on port `5000` (external entry point)
- **FastAPI** — backend API on `127.0.0.1:8000` (internal)
- **Next.js** — frontend server on `127.0.0.1:3000` (internal)
- **Cron** — [supercronic](https://github.com/aptible/supercronic) scheduler for `PROGRESS_SCHEDULE_CRON`

```
                    ┌───────────────────────────────────────────────┐
                    │           progress container (:5000)          │
                    │                                               │
  External ────────►│  Caddy (0.0.0.0:5000)                        │
  :5000             │    ├ /api/v1/*  ──► FastAPI (127.0.0.1:8000)  │
                    │    └ rest        ──► Next.js  (127.0.0.1:3000)│
                    │                                               │
                    │  supercronic ──► progress check (on schedule) │
                    │                                               │
                    │  s6-overlay manages: caddy, fastapi, nextjs,  │
                    │                      cron                     │
                    └───────────────────────────────────────────────┘
```

Caddy handles TLS termination, logging, and request routing (see `docker/Caddyfile`). s6-overlay starts FastAPI and Next.js before Caddy and restarts crashed processes.

## Scheduled Runs

The pipeline runs on the schedule defined by `PROGRESS_SCHEDULE_CRON`:

```bash
PROGRESS_SCHEDULE_CRON="0 8 * * *"     # daily at 08:00
```

- **When set:** Progress runs the pipeline **once on startup**, then on the cron schedule.
- **When unset:** the cron service idles — no scheduled runs. Trigger a run manually with:

  ```bash
  docker compose exec progress progress check
  ```

The cron expression follows standard 5-field syntax:

```text
┌───────────── Minute (0 - 59)
│ ┌───────────── Hour (0 - 23)
│ │ ┌───────────── Day of month (1 - 31)
│ │ │ ┌───────────── Month (1 - 12)
│ │ │ │ ┌───────────── Day of week (0 - 7, Sunday = 0 or 7)
│ │ │ │ │
* * * * *
```

## AI Providers

Progress needs an AI provider to generate analysis. Set `[analysis].provider` in `config.toml` and mount the matching credentials.

### Claude Code (`provider = "claude_code"`)

Mount your Claude Code settings file:

```yaml
volumes:
  - ./claude_settings.json:/root/.claude/settings.json:ro
```

### Codex (`provider = "codex"`)

Mount the Codex CLI config and auth files:

```yaml
volumes:
  - ./codex_config.toml:/root/.codex/config.toml:ro
  - ./codex_auth.json:/root/.codex/auth.json:ro
```

### Truncate (`provider = "truncate"`)

No AI call — diffs are truncated to `analysis.truncate_chars`. Intended for testing and CI environments without AI access.

## Configuration

Application configuration lives in the **database**. `config.toml` is a one-time seed plus the provider of infrastructure settings. After the first run:

- Edit ongoing settings through the web UI (`/config`) or the `/api/v1/config` API.
- Re-seed from the file with `docker compose exec progress progress config import --force`.
- Move config between file and DB with `progress config import` (file → DB) and `progress config export` (DB → file).

Override infrastructure values via environment variables (`PROGRESS_` prefix, `__` for nested keys):

```yaml
environment:
  - PROGRESS_TIMEZONE=Asia/Shanghai
  - PROGRESS_GITHUB__GH_TOKEN=${GH_TOKEN}
  - PROGRESS_MARKPOST__URL=${MARKPOST_URL}
  - PROGRESS_OBSERVABILITY__BUGSINK__DSN=${BUGSINK_DSN}
```

See [guides/config.md](../guides/config.md) for the full model.

## Data & Database

Progress stores everything under a single data directory (`/app/data` in the container):

- `data/progress.db` — SQLite database (reports, repository state, the config blob)
- `data/repos/` — cloned tracked repositories
- `data/progress.log` — application log
- `data/telemetry/` — OpenTelemetry traces/metrics (when enabled)

SQLite is the only database backend. It requires zero configuration — just keep the `data/` volume persistent:

```yaml
volumes:
  - ./data:/app/data
```

## Reverse Proxy

To deploy behind an external reverse proxy, forward traffic to port `5000`:

```caddyfile
progress.example.com {
    reverse_proxy localhost:5000
}
```

If you serve Progress under a public URL, set `web.base_url` so oversized reports can link back to the full report in the Web UI:

```bash
PROGRESS_WEB__BASE_URL="https://progress.example.com"
```

## Building the Image

```bash
python3 docker/build.py                    # build for the local platform (load)
python3 docker/build.py --push             # build and push multi-platform to registry
python3 docker/build.py --platform amd64   # build a specific platform
python3 docker/build.py --tags v1.0.0      # additional tags (replaces default "latest")
python3 docker/build.py --no-cache         # disable the build cache
```

Run `python3 docker/build.py --help` for the full list of options. The build uses Docker buildx and requires QEMU binfmt registered for cross-platform builds.

## Ansible Automation

An automated deployment playbook lives in `devops/ansible/`. Variables are encrypted with `ansible-vault` for internal use — external users should replace `devops/ansible/vars/` and `host_vars/` with their own values.

```bash
ansible-playbook -i devops/ansible/hosts.yml devops/ansible/main.yml \
  --vault-password-file ~/.ansible-vault/progress.pwd
```
