# 多架构支持: AMD64, ARM64
FROM python:3.13-slim AS builder

# 设置构建参数
ARG BUILDPLATFORM
ARG TARGETPLATFORM
ARG TARGETARCH

# 安装构建依赖
RUN apt-get update && apt-get install -y --no-install-recommends \
    gcc \
    curl \
    && rm -rf /var/lib/apt/lists/*

# 安装 uv (快速的 Python 包管理器)
RUN curl -LsSf https://astral.sh/uv/install.sh | sh && \
    export PATH="/root/.local/bin:$PATH" && \
    uv --version

# 设置工作目录
WORKDIR /app

# 复制项目文件
COPY pyproject.toml ./
COPY src/ ./src/

# 设置 PATH 并安装依赖
ENV PATH="/root/.local/bin:$PATH"
RUN uv pip install --system -e .

# 最终镜像
FROM python:3.13-slim

# 安装运行时依赖
RUN apt-get update && apt-get install -y --no-install-recommends \
    git \
    curl \
    ca-certificates \
    npm \
    cron \
    && rm -rf /var/lib/apt/lists/*

# 安装 Claude Code CLI
RUN npm install -g @anthropic-ai/claude-code

# 安装 GitHub CLI
RUN curl -fsSL https://cli.github.com/packages/githubcli-archive-keyring.gpg | dd of=/usr/share/keyrings/githubcli-archive-keyring.gpg \
    && echo "deb [arch=$(dpkg --print-architecture) signed-by=/usr/share/keyrings/githubcli-archive-keyring.gpg] https://cli.github.com/packages stable main" | tee /etc/apt/sources.list.d/github-cli.list \
    && apt-get update \
    && apt-get install -y gh \
    && rm -rf /var/lib/apt/lists/*

# 从 builder 阶段复制安装好的包
COPY --from=builder /usr/local/lib/python3.13/site-packages /usr/local/lib/python3.13/site-packages
COPY --from=builder /usr/local/bin /usr/local/bin

# 设置工作目录
WORKDIR /app

# 复制项目文件
COPY pyproject.toml ./
COPY src/ ./src/

# 创建数据目录
RUN mkdir -p /app/data

# 复制调度脚本
COPY docker-entrypoint.sh /usr/local/bin/docker-entrypoint.sh
RUN chmod +x /usr/local/bin/docker-entrypoint.sh

# 设置环境变量
ENV PYTHONUNBUFFERED=1
ENV PYTHONPATH=/app/src

# 默认命令：如果调度启用则运行调度脚本，否则直接执行
ENTRYPOINT ["/usr/local/bin/docker-entrypoint.sh"]
