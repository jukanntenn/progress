FROM python:3.13-slim AS builder

ARG BUILDPLATFORM
ARG TARGETPLATFORM
ARG TARGETARCH

RUN apt-get update && apt-get install -y --no-install-recommends \
    gcc \
    curl \
    gettext \
    && rm -rf /var/lib/apt/lists/*

RUN curl -LsSf https://astral.sh/uv/install.sh | sh && \
    export PATH="/root/.local/bin:$PATH" && \
    uv --version

WORKDIR /app

COPY pyproject.toml ./
COPY src/ ./src/

ENV PATH="/root/.local/bin:$PATH"
RUN uv pip install --system -e .

# Compile i18n translation files
RUN if [ -d "/app/src/progress/locales" ]; then \
        find /app/src/progress/locales -name "*.po" | while read po_file; do \
            mo_file="${po_file%.po}.mo"; \
            mkdir -p "$(dirname "$mo_file")"; \
            msgfmt -o "$mo_file" "$po_file" || echo "Failed to compile $po_file"; \
        done; \
        echo "i18n files compiled"; \
    else \
        echo "No locales directory found, skipping i18n compilation"; \
    fi

FROM python:3.13-slim

ARG TARGETARCH

RUN apt-get update && apt-get install -y --no-install-recommends \
    git \
    openssh-client \
    curl \
    ca-certificates \
    npm \
    && rm -rf /var/lib/apt/lists/*

ENV SUPERCRONIC_VERSION=v0.2.33

RUN SUPERCRONIC_URL=https://github.com/aptible/supercronic/releases/download/${SUPERCRONIC_VERSION}/supercronic-linux-${TARGETARCH} \
    && curl -fsSL "$SUPERCRONIC_URL" -o /usr/local/bin/supercronic \
    && chmod +x /usr/local/bin/supercronic \
    && supercronic -version || echo "Supercronic installed for ${TARGETARCH}"

RUN npm install -g @anthropic-ai/claude-code

RUN curl -fsSL https://cli.github.com/packages/githubcli-archive-keyring.gpg | dd of=/usr/share/keyrings/githubcli-archive-keyring.gpg \
    && echo "deb [arch=$(dpkg --print-architecture) signed-by=/usr/share/keyrings/githubcli-archive-keyring.gpg] https://cli.github.com/packages stable main" | tee /etc/apt/sources.list.d/github-cli.list \
    && apt-get update \
    && apt-get install -y gh \
    && rm -rf /var/lib/apt/lists/*

COPY --from=builder /usr/local/lib/python3.13/site-packages /usr/local/lib/python3.13/site-packages
COPY --from=builder /usr/local/bin /usr/local/bin
COPY --from=builder /root/.local/bin /root/.local/bin
COPY --from=builder /app/src/progress/locales /app/src/progress/locales

WORKDIR /app

COPY pyproject.toml ./
COPY src/ ./src/

RUN mkdir -p /app/data

COPY docker/entrypoint.sh /usr/local/bin/entrypoint.sh
RUN chmod +x /usr/local/bin/entrypoint.sh

ENV PYTHONUNBUFFERED=1
ENV PYTHONPATH=/app/src

ENTRYPOINT ["/usr/local/bin/entrypoint.sh"]
