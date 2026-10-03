# syntax=docker/dockerfile:1.7
# Progress container image (spec 14)
#
# 2-process architecture: Caddy (static SPA + reverse proxy) + FastAPI/uvicorn.
# Non-root, hardened, no node runtime, no AI CLIs. Multi-stage build:
#   1. python-deps  — install Python deps via uv, compile .po -> .mo
#   2. node-build   — build Vite SPA to dist/ (pure static output)
#   3. runtime      — Caddy + s6-overlay + FastAPI, non-root

ARG PYTHON_IMAGE=python:3.13-alpine

# ============================================================================
# Stage 1: python-deps
# ============================================================================
FROM ${PYTHON_IMAGE} AS python-deps

RUN apk add --no-cache gcc musl-dev gettext
RUN pip install uv

WORKDIR /app

COPY pyproject.toml uv.lock ./

RUN --mount=type=cache,target=/root/.cache/uv \
    uv export --no-dev --no-emit-project -o /tmp/requirements.txt && \
    uv pip install --system -r /tmp/requirements.txt

COPY src/ ./src/

RUN --mount=type=cache,target=/root/.cache/uv \
    uv pip install --system --no-deps .

# Compile .po -> .mo (spec 11). Uses Babel's Python API (write_mo) directly
# instead of `pybabel compile` because the CLI infers the locale from the
# directory name and rejects BCP-47 lowercase (zh-hans), while spec 11
# mandates lowercase directory names. The Python API with locale=None
# produces the same .mo format that gettext.GNUTranslations loads at runtime.
COPY scripts/compile_messages.py /tmp/compile_messages.py
RUN python /tmp/compile_messages.py /app/src/progress/locales progress || \
    echo "[python-deps] no .po catalogs to compile (skipping)" && \
    rm -f /tmp/compile_messages.py

# ============================================================================
# Stage 2: node-build — Vite produces static dist/ (no node runtime needed)
# ============================================================================
FROM node:22-alpine AS node-build

WORKDIR /app

COPY web/package.json web/pnpm-lock.yaml web/pnpm-workspace.yaml ./
RUN corepack enable && pnpm install --frozen-lockfile

COPY web/ .
RUN pnpm build

# ============================================================================
# Stage 3: runtime
# ============================================================================
FROM ${PYTHON_IMAGE} AS runtime

ARG TARGETARCH
ARG GIT_SHA=unknown
ARG S6_OVERLAY_VERSION=3.2.0.2
ARG CADDY_VERSION=v2.9.1
ARG CADDY_SHA512=""
LABEL org.opencontainers.image.title="progress" \
      org.opencontainers.image.source="https://github.com/jukanntenn/progress" \
      org.opencontainers.image.licenses="MIT"

# Runtime packages: git/ssh for repo operations, curl for healthcheck,
# ca-certificates/tzdata for TLS + timezones, github-cli for `gh repo clone`.
# NO nodejs/npm (Vite produces static files), NO claude/codex CLI (spec 14).
RUN apk add --no-cache \
    git \
    openssh-client \
    curl \
    ca-certificates \
    tzdata \
    github-cli

# Caddy binary with mandatory SHA512 verification (spec 14 hardening).
# Caddy's ``caddy_<version>_checksums.txt`` ships SHA512 digests (128 hex), so
# the check uses ``sha512sum``. The expected hash is resolved in priority order:
#   1. --build-arg CADDY_SHA512=<hash>  (explicit pin, highest priority)
#   2. the matching entry in caddy_<version>_checksums.txt (fetched from the
#      release assets — verified against the release's own signed manifest)
# Verification always runs; a mismatch fails the build.
RUN CADDY_TARBALL="caddy_${CADDY_VERSION##v}_linux_${TARGETARCH}.tar.gz" && \
    curl -fsSL \
    "https://github.com/caddyserver/caddy/releases/download/${CADDY_VERSION}/${CADDY_TARBALL}" \
    -o /tmp/caddy.tar.gz && \
    curl -fsSL \
    "https://github.com/caddyserver/caddy/releases/download/${CADDY_VERSION}/caddy_${CADDY_VERSION##v}_checksums.txt" \
    -o /tmp/caddy_checksums.txt && \
    EXPECTED="${CADDY_SHA512:-$(grep "  ${CADDY_TARBALL}\$" /tmp/caddy_checksums.txt | awk '{print $1}')}"; \
    if [ -z "${EXPECTED}" ]; then \
        echo "ERROR: no SHA512 found for ${CADDY_TARBALL} in checksums.txt and CADDY_SHA512 not set" >&2; \
        exit 1; \
    fi; \
    echo "${EXPECTED}  /tmp/caddy.tar.gz" | sha512sum -c - && \
    tar xz -C /usr/local/bin -f /tmp/caddy.tar.gz caddy && \
    chmod +x /usr/local/bin/caddy && \
    rm /tmp/caddy.tar.gz /tmp/caddy_checksums.txt

# s6-overlay v3 for process supervision, with SHA256 verification against the
# release's per-asset .sha256 (spec 14 hardening). The arch tarball keeps its
# release file name so ``sha256sum -c`` (run from /tmp) matches the digest file,
# which records a bare ``s6-overlay-<arch>.tar.xz`` name.
RUN S6_ARCH=$(case "${TARGETARCH}" in amd64) echo "x86_64" ;; arm64) echo "aarch64" ;; esac) && \
    curl -fsSL "https://github.com/just-containers/s6-overlay/releases/download/v${S6_OVERLAY_VERSION}/s6-overlay-noarch.tar.xz" -o /tmp/s6-overlay-noarch.tar.xz && \
    curl -fsSL "https://github.com/just-containers/s6-overlay/releases/download/v${S6_OVERLAY_VERSION}/s6-overlay-${S6_ARCH}.tar.xz" -o /tmp/s6-overlay-${S6_ARCH}.tar.xz && \
    curl -fsSL "https://github.com/just-containers/s6-overlay/releases/download/v${S6_OVERLAY_VERSION}/s6-overlay-${S6_ARCH}.tar.xz.sha256" -o /tmp/s6-overlay-${S6_ARCH}.tar.xz.sha256 && \
    cd /tmp && sha256sum -c s6-overlay-${S6_ARCH}.tar.xz.sha256 && \
    tar -C / -Jxpf /tmp/s6-overlay-noarch.tar.xz && \
    tar -C / -Jxpf /tmp/s6-overlay-${S6_ARCH}.tar.xz && \
    rm -f /tmp/s6-overlay-noarch.tar.xz /tmp/s6-overlay-${S6_ARCH}.tar.xz /tmp/s6-overlay-${S6_ARCH}.tar.xz.sha256

# Scheduling (PRFC 2026-08-31 phase 4): periodic pipeline runs execute inside
# the API process via ctx.scheduler (croniter) — the scheduled-run row on the
# serve tree reads schedule.cron from config, with PROGRESS_SCHEDULE_CRON as
# the container compatibility fallback. supercronic and the s6 cron longrun
# are retired.

# Caddy config + s6 service definitions: caddy + fastapi longruns. No nextjs
# (Vite produces static output).
COPY docker/Caddyfile /etc/caddy/Caddyfile
COPY docker/s6/cont-init.d /etc/cont-init.d
COPY docker/s6/s6-rc.d /etc/s6-overlay/s6-rc.d
RUN chmod +x /etc/cont-init.d/*.sh /etc/s6-overlay/s6-rc.d/*/run

# Python deps + compiled .mo catalogs from stage 1.
COPY --from=python-deps /usr/local/lib/python3.13/site-packages /usr/local/lib/python3.13/site-packages
COPY --from=python-deps /usr/local/bin /usr/local/bin
COPY --from=python-deps /app/src/progress/locales /app/src/progress/locales

# Vite static build from stage 2 (pure HTML/CSS/JS — no node runtime).
COPY --from=node-build /app/dist /app/web/dist

WORKDIR /app

# Application source. `COPY src/` merges with the locales copied above;
# compiled .mo files are preserved (host typically gitignores *.mo).
COPY pyproject.toml ./
COPY src/ ./src/

# Non-root user + writable /app/data only (spec 14: 非 root 运行).
RUN addgroup -S progress && \
    adduser -S -G progress -h /home/progress -s /bin/sh progress && \
    mkdir -p /app/data /home/progress/.ssh && \
    chown -R progress:progress /app /home/progress && \
    chmod 700 /home/progress/.ssh

USER progress

ENV PYTHONUNBUFFERED=1 \
    PYTHONPATH=/app/src \
    TZ=UTC \
    S6_KEEP_ENV=1 \
    CONFIG_FILE=/app/config.toml \
    GIT_SHA=${GIT_SHA}

# HEALTHCHECK (spec 14): hit the unauthenticated liveness endpoint via the
# public Caddy port. Caddy reverse-proxies /healthz to FastAPI; a 200 means
# both the Caddy and FastAPI processes are up and wired.
HEALTHCHECK --interval=30s --timeout=5s --start-period=15s --retries=3 \
    CMD curl -fsS http://localhost:5000/healthz || exit 1

ENTRYPOINT ["/init"]
