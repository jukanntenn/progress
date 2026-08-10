# Deployment Guide

Progress ships as a single hardened container: a static Vite SPA served by Caddy, a FastAPI backend, and a supercronic scheduler, all supervised by s6-overlay. This guide covers the Docker deployment and the one-time migration from the legacy (pre-redesign) build.

## Docker Quick Start

### Docker Compose (Recommended)

1. Pull or build the image (see [Building the Image](#building-the-image)).

2. Create a minimal `config.toml` (Ansible-class). It carries only the data root — all other settings live in the database and are edited via the Web UI:

   ```toml
   state_home = "/app/data"
   ```

3. Create `docker-compose.yml`:

   ```yaml
   services:
     progress:
      image: progress:latest
      container_name: progress
      ports:
        - "5000:5000"
      read_only: true
      tmpfs:
        - /tmp
      cap_drop:
        - ALL
      security_opt:
        - no-new-privileges:true
      volumes:
        - ./config.toml:/app/config.toml:ro
        - ./data:/app/data
      environment:
        # supercronic reads this to schedule periodic pipeline runs.
        # Empty/unset => the cron service idles (no scheduled runs).
        - PROGRESS_SCHEDULE_CRON=0 8 * * *     # daily at 08:00
      healthcheck:
        test: ["CMD", "curl", "-fsS", "http://127.0.0.1:5000/healthz"]
        interval: 30s
        timeout: 5s
        retries: 3
        start_period: 30s
      restart: always
   ```

   The `data/` directory must be writable by the container's non-root `progress` user — ensure the host directory is owned or chmod'd accordingly (`chown 1000:1000 ./data` or `chmod 777 ./data`).

4. Start the container:

   ```bash
   docker compose up -d
   docker compose logs -f
   ```

   The first startup takes ~15s (DB schema creation + migrations + observability init); subsequent restarts are faster. Open the web UI at `http://<your-host>:5000`.

### Single Container

For quick evaluation only — use Docker Compose for long-term deployments.

```bash
mkdir -p data && chown 1000:1000 data
docker run -d \
  --name progress \
  -p 5000:5000 \
  -e PROGRESS_SCHEDULE_CRON="0 8 * * *" \
  -v "$PWD/config.toml:/app/config.toml:ro" \
  -v "$PWD/data:/app/data" \
  progress:latest
```

## Container Architecture

Progress runs as a single non-root container with three internal services managed by [s6-overlay](https://github.com/just-containers/s6-overlay):

- **Caddy** — reverse proxy + static SPA server on port `5000` (external entry point)
- **FastAPI** — backend API on `127.0.0.1:8000` (internal)
- **Cron** — [supercronic](https://github.com/aptible/supercronic) scheduler running `progress run` per `PROGRESS_SCHEDULE_CRON`

```text
                    ┌───────────────────────────────────────────────┐
                    │           progress container (:5000)          │
                    │                                               │
  External ────────►│  Caddy (0.0.0.0:5000)                        │
  :5000             │    ├ /api/v1/*   ──► FastAPI (127.0.0.1:8000) │
                    │    ├ /healthz    ──► FastAPI                  │
                    │    ├ /readyz     ──► FastAPI                  │
                    │    └ rest        ──► Vite SPA (static dist/)  │
                    │                                               │
                    │  supercronic ──► progress run (on schedule)   │
                    │                                               │
                    │  s6-overlay manages: caddy, fastapi, cron     │
                    └───────────────────────────────────────────────┘
```

Caddy handles TLS termination, security headers, and request routing (see `docker/Caddyfile`). The `/healthz` and `/readyz` probes are reverse-proxied to FastAPI (not served as SPA fallback) so the Docker `HEALTHCHECK` reflects real backend health — `/readyz` additionally pings the database.

## Scheduled Runs

The pipeline runs on the schedule defined by `PROGRESS_SCHEDULE_CRON`:

```bash
PROGRESS_SCHEDULE_CRON="0 8 * * *"     # daily at 08:00
```

- **When set:** supercronic runs `progress run -c /app/config.toml` on the cron schedule. The service does **not** run once on startup (no duplicate runs during parallel operation with the legacy build).
- **When unset:** the cron service idles (`sleep infinity`). Trigger a run manually:

  ```bash
  docker compose exec progress progress run -c /app/config.toml
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

## AI Analysis

Progress uses [Pydantic AI](https://ai.pydantic.dev/) for diff analysis. Configure it through the Web UI (`/config` → `core.analysis`) or the config API after first boot — it is **not** set via `config.toml` or environment variables:

- `provider` + `model` — a Pydantic AI model string, e.g. `model = "anthropic:claude-sonnet-4"`.
- `api_key` — provider API key (stored as a `SecretStr`).
- `base_url` — optional, for OpenAI-compatible self-hosted endpoints.
- `language` — output language for analysis results.
- `concurrency` — per-integration analysis parallelism.

When `provider`/`api_key` are empty, AI analysis is disabled and diffs fall back to truncation. There is no bundled CLI provider (the legacy `claude_code`/`codex` CLI providers were removed in the redesign).

## Configuration

Application configuration lives in the **database** `config` table, split into sections (`core`, `repo`, `changelog`, `proposal`, `feed`). `config.toml` is Ansible-class and carries **only** `state_home`; everything else is edited at runtime:

- Edit ongoing settings through the web UI (`/config`) or the API (`PUT /api/v1/config/{section}`). The Web UI renders the config form from the server's JSON Schema via RJSF; secret fields are masked with `type="password"` inputs in the browser. Writes are validated with the section's Pydantic model — invalid payloads return 422 and leave the DB untouched.
- On container startup, after DB migrations, `migrate_config_data()` repairs known-bad structures from the legacy editor (e.g. `core.observability.bugsink` stored as a list, `recipient` containing non-string entries) so the runtime can load the config without falling back to defaults. It is idempotent: healthy data is never touched.
- For a first deploy or testing, place a `config.db.toml` seed file next to `config.toml`; it is imported into the DB on startup (DB values win over the seed). In production, ensure no `config.db.toml` exists — the DB is the single source of truth.

Environment-variable overrides (`PROGRESS_` prefix, `__` for nested keys) still apply, but only for keys the DB does not already set. For a production deploy, prefer editing via the Web UI over env vars. Note: `core.observability.otel.*` is not a config field (OTel export paths derive from `state_home`) — do **not** set `PROGRESS_OBSERVABILITY__OTEL__*` env vars, they will fail `CoreConfig` validation and prevent startup.

## Data & Database

Progress stores everything under a single data directory (`/app/data` in the container, `state_home`):

- `progress.db` — SQLite database (reports, repository/owner/changelog/proposal state, the `config` table)
- `repos/` — cloned tracked repositories
- `logs/` — application logs
- `observability/` — OpenTelemetry traces/metrics JSONL

SQLite (WAL mode) is the only database backend. Keep the `data/` volume persistent:

```yaml
volumes:
  - ./data:/app/data
```

## Migrating from the Legacy Build

The redesign changed the DB schema (peewee → tortoise-orm) and the config storage model (single `app_config` blob → per-section `config` rows). A one-shot migration script carries over all state tables and configuration losslessly:

```bash
# On the new server, with the legacy DB copied to ./old/progress.db:
uv run python scripts/migrate_from_legacy.py \
  --old ./old/progress.db \
  --new ./data/progress.db
```

The script refuses to overwrite a new DB that already contains data. It migrates:

- **State tables** verbatim (repositories, reports, batches, owners, changelog/proposal trackers, proposals) — renaming `batch`→`batches` and `proposal_trackers`→`proposal_tracker_states`.
- **Configuration** from the legacy `app_config.data` JSON blob into the `core` / `repo` / `changelog` / `proposal` sections, dropping fields not in the new schema (e.g. feishu `timeout`) and leaving `analysis` empty (fill via Web UI). Secrets (gh_token, webhook URLs) are preserved in plaintext, matching how the config table stores them.

The `repo` section is populated from the `repositories`/`github_owners` tables so the tracker's reconcile pass does not garbage-collect the migrated checkpoints on first run. Run the migration **before** the first scheduled `progress run`.

## Reverse Proxy

To deploy behind an external reverse proxy, forward traffic to port `5000`:

```caddyfile
progress.example.com {
    reverse_proxy localhost:5000
}
```

If you serve Progress under a public URL, set `core.web.base_url` (via the Web UI or config API) so oversized reports can link back to the full report.

## Building the Image

```bash
uv run python docker/build.py                                      # build for the local platform (load)
uv run python docker/build.py --push --registry ghcr               # build + push multi-platform (alias)
uv run python docker/build.py --push --registry ghcr.io/youruser   # build + push with explicit host
uv run python docker/build.py --platform amd64                     # build a specific platform
uv run python docker/build.py --tags v1.0.0                        # additional tags (replaces default "latest")
uv run python docker/build.py --no-cache                           # disable the build cache
```

Registry targets: aliases `ghcr` → `ghcr.io`, `dockerhub`/`docker` → `docker.io`;
or any host like `registry.local:5000` (owner auto-derived from git config when possible).
Run `uv run python docker/build.py --help` for the full list of options. The build uses Docker buildx and requires QEMU binfmt registered for cross-platform builds. Third-party binaries (Caddy, s6-overlay, supercronic) are downloaded with mandatory SHA checksum verification.

## Ansible Automation

An automated deployment playbook lives in `devops/ansible/`. It renders `config.toml` and `docker-compose.yml` from templates, pulls the image, and (re)starts the container. Variables are encrypted with `ansible-vault` for internal use — external users should replace `devops/ansible/vars/` and `host_vars/` with their own values.

```bash
ansible-playbook -i devops/ansible/hosts.yml devops/ansible/main.yml \
  --vault-password-file ~/.ansible-vault/progress.pwd
```

Internal production on `fn` pulls the image from the in-network registry at `192.168.5.50:5000` under the **`:main`** tag (the dogfooding `:next` tag is retired). The release flow is **manual** — no git tag is cut and `release.yml` is not involved; cutting a `v*` tag would publish to GHCR instead, which is a separate path. To ship a new build to `fn`:

```bash
# 1. build + push :main to the in-network registry (run on a host that can reach 192.168.5.50:5000)
uv run python docker/build.py --push --tags main                   # host platform only (faster)
uv run python docker/build.py --push --tags main --all-platforms   # amd64 + arm64

# 2. deploy — playbook pulls :main (pull: always) and recreates the container
ansible-playbook -i devops/ansible/hosts.yml devops/ansible/main.yml \
  --vault-password-file ~/.ansible-vault/progress.pwd
```

After each upgrade, verify the DB auto-migration succeeded — startup migrations never crash on schema errors (they log a `migration_failed` metric and degrade), so check `data/observability/metrics.jsonl` and `data/logs/progress.log` rather than relying on the container being up.

The inventory (`hosts.yml`) targets the new server (`fn`); the legacy server (`oect`) is retained until the new build is verified and the old one decommissioned.
