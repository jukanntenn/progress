FROM node:22-alpine AS frontend

WORKDIR /app/src/progress/web

RUN corepack enable

COPY src/progress/web/package.json src/progress/web/pnpm-lock.yaml src/progress/web/pnpm-workspace.yaml ./
RUN pnpm install --frozen-lockfile

COPY src/progress/web/ ./
RUN pnpm build

FROM python:3.13-alpine AS builder

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

FROM python:3.13-alpine

ARG TARGETARCH

RUN apk add --no-cache \
    git \
    openssh-client \
    curl \
    ca-certificates \
    nodejs \
    npm \
    github-cli

ENV SUPERCRONIC_VERSION=v0.2.33

RUN curl -fsSL \
    "https://github.com/aptible/supercronic/releases/download/${SUPERCRONIC_VERSION}/supercronic-linux-${TARGETARCH}" \
    -o /usr/local/bin/supercronic \
    && chmod +x /usr/local/bin/supercronic

RUN npm install -g @anthropic-ai/claude-code

COPY --from=builder /usr/local/lib/python3.13/site-packages /usr/local/lib/python3.13/site-packages
COPY --from=builder /usr/local/bin /usr/local/bin
COPY --from=builder /app/src/progress/locales /app/src/progress/locales
COPY --from=frontend /app/src/progress/web/dist /app/src/progress/web/dist

WORKDIR /app

COPY pyproject.toml ./
COPY src/ ./src/

RUN mkdir -p /app/data

COPY docker/entrypoint.sh /usr/local/bin/entrypoint.sh
RUN chmod +x /usr/local/bin/entrypoint.sh

ENV PYTHONUNBUFFERED=1
ENV PYTHONPATH=/app/src

ENTRYPOINT ["/usr/local/bin/entrypoint.sh"]
