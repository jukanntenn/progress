# Progress Container Architecture

This document explains the tools and integration choices used in Progress's containerized deployment.

## Architecture Overview

Progress runs as a single Docker container with four processes managed by **s6-overlay**:

```
Container (port 5000)
├── Caddy (reverse proxy, port 5000)
│   ├── /api/v1/* → FastAPI (127.0.0.1:8000)
│   └── /*        → Next.js (127.0.0.1:3000)
├── FastAPI (backend API, CLI, scheduler)
├── Next.js (frontend UI, standalone server)
└── Supercronic (optional scheduled tasks)
```

Caddy is the sole entry point, listening on port 5000. It routes API requests directly to FastAPI and everything else to Next.js. This avoids routing API/RSS traffic through the Node.js runtime.

In development, there is no Caddy — the frontend and backend run as separate processes, with Next.js `rewrites` proxying `/api/*` to the backend.

---

## FastAPI

### Integration

The FastAPI application is defined as a factory function `create_app()` in `src/progress/api/__init__.py`. It creates a `FastAPI` instance, initializes the database, and registers route modules (reports, config, rss) under the `/api/v1` prefix.

The `fastapi` CLI (from `fastapi[standard]`) discovers the app via the `[tool.fastapi]` entrypoint in `pyproject.toml`, which points to `progress.main:app` — a module-level `FastAPI` instance created by calling `create_app()`.

**Development**: `fastapi dev` starts the server with hot reload. Default port is 8000 (overridden via `--port`). The CLI reads the entrypoint from `pyproject.toml` and auto-detects the app.

**Production**: `fastapi run --host 127.0.0.1 --port 8000` runs the server without hot reload, binding to localhost only (Caddy proxies to it). Single worker is used because the application uses SQLite, which doesn't support concurrent writes from multiple processes.

### Key Decisions

- `fastapi[standard]` is used instead of managing `uvicorn` directly — the `fastapi` CLI wraps uvicorn and handles production defaults.
- The `[web]` config section was removed — host/port are now determined by the deployment environment (s6-overlay service scripts for production, CLI flags for development), not user configuration.
- The legacy `web_dist` SPA fallback (serving a pre-built frontend from FastAPI) was removed — frontend serving is Next.js's responsibility.

### Quick Reference

| Command | Purpose |
|---------|---------|
| `fastapi dev` | Dev server with hot reload |
| `fastapi run --host 127.0.0.1 --port 8000` | Production server |
| `PYTHONPATH=src CONFIG_FILE=config.toml` | Required env vars for dev |
| `[tool.fastapi] entrypoint = "progress.main:app"` | pyproject.toml app discovery config |

---

## Caddy

### Integration

Caddy serves as the reverse proxy in the container, listening on port 5000. Its configuration is a simple Caddyfile at `docker/Caddyfile`:

```
:5000 {
    handle /api/v1/* {
        reverse_proxy 127.0.0.1:8000
    }
    handle {
        reverse_proxy 127.0.0.1:3000
    }
}
```

Only two routing rules: API routes go to FastAPI, everything else to Next.js. Static assets, image optimization, and SSR are all handled by Next.js — Caddy doesn't serve files from disk. This avoids complexity with Next.js's internal filesystem layout (`_next/image`, `_next/static` path mapping) while still achieving the main goal: API/RSS requests skip the Node.js runtime entirely.

### Installation

Caddy is installed in the Dockerfile by downloading the prebuilt binary from GitHub releases:

```dockerfile
ARG CADDY_VERSION=v2.9.1
RUN curl -fsSL \
    "https://github.com/caddyserver/caddy/releases/download/${CADDY_VERSION}/caddy_${CADDY_VERSION##v}_linux_${TARGETARCH}.tar.gz" \
    | tar xz -C /usr/local/bin caddy
```

No custom Caddy modules are needed — the standard build handles HTTP reverse proxying.

### Key Decisions

- Prebuilt binary instead of `xcaddy` build — no custom modules required.
- No static file serving from disk — let Next.js handle its own assets. The complexity isn't worth the marginal gain.
- Console log format for container-friendly output to stderr.

### Quick Reference

| Path | Description |
|------|-------------|
| `docker/Caddyfile` | Caddy configuration |
| `caddy validate --config /etc/caddy/Caddyfile` | Validate config |
| `caddy fmt --check /etc/caddy/Caddyfile` | Check formatting |

---

## s6-overlay

### Integration

s6-overlay manages all processes in the container. Four services are defined under `docker/s6/s6-rc.d/`:

| Service | Type | Purpose |
|---------|------|---------|
| `fastapi` | longrun | FastAPI backend (`fastapi run`) |
| `nextjs` | longrun | Next.js frontend (`node server.js`) |
| `caddy` | longrun | Caddy reverse proxy |
| `cron` | longrun | Supercronic scheduler (optional) |

Service dependencies: `caddy` depends on both `fastapi` and `nextjs`, ensuring it starts after the backend services are ready. The `cron` service is independent.

The `cron` service is gated by the `PROGRESS_SCHEDULE_CRON` environment variable. If not set, the run script executes `sleep infinity` — s6 considers it "up" but it does nothing. If set, it generates a crontab and runs supercronic.

Initialization scripts in `cont-init.d/` handle:
- **Timezone setup**: reads `timezone` from `config.toml` and sets system timezone
- **SSH configuration**: configures git to auto-accept new SSH host keys

### Installation

s6-overlay is installed in the Dockerfile from GitHub release tarballs:

```dockerfile
ARG S6_OVERLAY_VERSION=3.2.0.2
ADD "https://github.com/just-containers/s6-overlay/releases/download/v${S6_OVERLAY_VERSION}/s6-overlay-noarch.tar.xz" /tmp
ADD "https://github.com/just-containers/s6-overlay/releases/download/v${S6_OVERLAY_VERSION}/s6-overlay-${TARGETARCH}.tar.xz" /tmp
RUN tar -C / -Jxpf /tmp/s6-overlay-noarch.tar.xz && \
    tar -C / -Jxpf /tmp/s6-overlay-${TARGETARCH}.tar.xz
```

The `noarch` tarball provides scripts and configuration. The architecture-specific tarball provides the s6 binaries. Both are extracted to `/`.

### Directory Structure

```
docker/s6/
├── cont-init.d/              # Container initialization scripts
│   ├── 01-timezone.sh
│   └── 02-ssh.sh
└── s6-rc.d/                  # Service definitions
    ├── user/
    │   ├── type              # "bundle"
    │   └── contents.d/       # Enabled services (one file per service)
    ├── fastapi/
    │   ├── type              # "longrun"
    │   └── run               # Startup script
    ├── nextjs/
    │   ├── type              # "longrun"
    │   └── run               # Startup script
    ├── caddy/
    │   ├── type              # "longrun"
    │   ├── run               # Startup script
    │   └── dependencies.d/   # Depends on fastapi, nextjs
    └── cron/
        ├── type              # "longrun"
        └── run               # Startup script (gated by env var)
```

### Key Decisions

- Shell scripts instead of execline — more maintainable for this project's team.
- `S6_KEEP_ENV=1` ensures environment variables from docker-compose are available to all services.
- The cron service uses `sleep infinity` when disabled rather than dynamic service enabling, keeping the configuration static.

### Quick Reference

| Path | Description |
|------|-------------|
| `/init` | Container entrypoint (s6-overlay init) |
| `/etc/s6-overlay/s6-rc.d/` | Service definitions |
| `s6-rc -d <service>` | Stop a service |
| `s6-rc -u <service>` | Start a service |
| `s6-svstat /run/s6-rc/servicedirs/<service>` | Check service status |

---

## Docker

### Integration

The Dockerfile uses a multi-stage build to minimize the final image size and maximize layer caching:

| Stage | Base | Purpose | Cache invalidation trigger |
|-------|------|---------|---------------------------|
| `python-deps` | python:3.13-alpine | Install Python deps + compile locales | `pyproject.toml` or `uv.lock` change |
| `node-deps` | node:22-alpine | Install Node deps | `package.json` or lockfile change |
| `node-build` | node:22-alpine | Build Next.js standalone | any `web/` source change |
| `runtime` | python:3.13-alpine | Final image with all tools | source code change |

Cache ordering ensures that dependency installation (rarely changes) is cached separately from source code changes (frequent). The `runtime` stage copies compiled outputs from previous stages and installs runtime tools (git, github-cli, caddy, supercronic, s6-overlay).

All stages use Alpine Linux for minimal size. The runtime needs both Python and Node.js (Next.js standalone requires Node to run).

The build script (`docker/build.py`) supports multi-architecture builds via Docker buildx, with platform-aware cache management for registry pushes.

### Key Decisions

- Alpine-based for all stages — smallest base images.
- Python deps installed via `uv pip install --system` — avoids virtual environment overhead in the container.
- Next.js standalone output (`output: "standalone"`) — produces a minimal Node.js server without the full `node_modules`.
- Supercronic (not system cron) for scheduling — single static binary, no daemon overhead.
- s6-overlay for process management — proper signal handling, dependency ordering, and service lifecycle.

### Quick Reference

| Command | Description |
|---------|-------------|
| `python docker/build.py` | Build image locally |
| `python docker/build.py --push` | Build and push to registry |
| `python docker/build.py --platform amd64` | Build for specific platform |
| `python docker/build.py --no-cache` | Build without cache |
| `python docker/build.py --verbose` | Show full build output |
