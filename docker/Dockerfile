FROM python:3.13-alpine AS python-deps

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

RUN if [ -d "/app/src/progress/locales" ]; then \
        find /app/src/progress/locales -name "*.po" | while read po_file; do \
            mo_file="${po_file%.po}.mo"; \
            mkdir -p "$(dirname "$mo_file")"; \
            msgfmt -o "$mo_file" "$po_file"; \
        done; \
    fi


FROM node:22-alpine AS node-deps

WORKDIR /app

COPY web/package.json web/pnpm-lock.yaml web/pnpm-workspace.yaml ./
RUN corepack enable && pnpm install --frozen-lockfile


FROM node:22-alpine AS node-build

WORKDIR /app

COPY --from=node-deps /app/node_modules ./node_modules
COPY web/ .

ENV NEXT_TELEMETRY_DISABLED=1

RUN corepack enable && npx next build


FROM python:3.13-alpine AS runtime

ARG TARGETARCH
ARG S6_OVERLAY_VERSION=3.2.0.2
ARG CADDY_VERSION=v2.9.1
ARG SUPERCRONIC_VERSION=v0.2.33

RUN apk add --no-cache \
    git \
    openssh-client \
    curl \
    ca-certificates \
    tzdata \
    nodejs \
    npm \
    bash \
    github-cli

RUN curl -fsSL \
    "https://github.com/aptible/supercronic/releases/download/${SUPERCRONIC_VERSION}/supercronic-linux-${TARGETARCH}" \
    -o /usr/local/bin/supercronic \
    && chmod +x /usr/local/bin/supercronic

ADD "https://github.com/just-containers/s6-overlay/releases/download/v${S6_OVERLAY_VERSION}/s6-overlay-noarch.tar.xz" /tmp/s6-overlay-noarch.tar.xz
RUN S6_ARCH=$(case "${TARGETARCH}" in amd64) echo "x86_64" ;; arm64) echo "aarch64" ;; esac) && \
    curl -fsSL "https://github.com/just-containers/s6-overlay/releases/download/v${S6_OVERLAY_VERSION}/s6-overlay-${S6_ARCH}.tar.xz" -o /tmp/s6-overlay-arch.tar.xz && \
    tar -C / -Jxpf /tmp/s6-overlay-noarch.tar.xz && \
    tar -C / -Jxpf /tmp/s6-overlay-arch.tar.xz && \
    rm -f /tmp/s6-overlay-*.tar.xz

RUN curl -fsSL \
    "https://github.com/caddyserver/caddy/releases/download/${CADDY_VERSION}/caddy_${CADDY_VERSION##v}_linux_${TARGETARCH}.tar.gz" \
    | tar xz -C /usr/local/bin caddy && \
    chmod +x /usr/local/bin/caddy

ARG HTTP_PROXY=""
RUN curl -fsSL ${HTTP_PROXY:+--proxy "$HTTP_PROXY"} https://claude.ai/install.sh | bash -s -- 2.1.153
RUN npm install -g @openai/codex@0.129.0

COPY docker/Caddyfile /etc/caddy/Caddyfile
COPY docker/s6/cont-init.d /etc/cont-init.d
COPY docker/s6/s6-rc.d /etc/s6-overlay/s6-rc.d
RUN chmod +x /etc/cont-init.d/*.sh

COPY --from=python-deps /usr/local/lib/python3.13/site-packages /usr/local/lib/python3.13/site-packages
COPY --from=python-deps /usr/local/bin /usr/local/bin
COPY --from=python-deps /app/src/progress/locales /app/src/progress/locales

COPY --from=node-build /app/.next/standalone /app/web
COPY --from=node-build /app/.next/static /app/web/.next/static
COPY --from=node-build /app/public /app/web/public

WORKDIR /app

COPY pyproject.toml ./
COPY src/ ./src/

RUN mkdir -p /app/data

ENV PYTHONUNBUFFERED=1
ENV PYTHONPATH=/app/src
ENV S6_KEEP_ENV=1

ENTRYPOINT ["/init"]
