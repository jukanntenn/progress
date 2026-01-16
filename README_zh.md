# Progress

简体中文 | [English](./README.md)

Progress 是一个 GitHub 项目跟踪工具，能够追踪多个仓库的代码变更，运行 AI 分析，并生成报告，帮助用户跟踪开源项目的进展。

## 功能特性

- **多仓库监控** - 可同时监控多个 GitHub 仓库，跟踪代码变更
- **AI 智能分析** - 使用 Claude Code CLI 分析代码变更，生成 Markdown 分析报告
- **通知功能** - 支持飞书和邮件通知，及时推送分析报告
- **Docker 部署** - Docker 容器化部署，最快一分钟拉起

## 环境要求

### Docker 运行

- 需安装 [Docker Engine](https://docs.docker.com/engine/install/)

### 宿主机运行

- Python 3.12 或更高版本
- [uv 包管理器](https://github.com/astral-sh/uv)（推荐）或 pip
- [GitHub CLI](https://cli.github.com/)
- [Claude Code CLI](https://claude.com/product/claude-code)

## 快速开始

### 在 Docker 容器中运行

1. 准备配置文件：

```bash
cp config.example.toml config.toml
```

编辑配置文件，填写必要的配置项（详见[配置说明](#配置说明)）。

2. 创建数据目录用于持久化存储：

```bash
mkdir -p data
```

3. 准备 Claude Code 配置文件。将本地的 Claude Code 配置复制到项目目录：

```bash
cp ~/.claude/settings.json ./claude_settings.json
```

`claude_settings.json` 最小化配置示例：

```json
{
  "env": {
    "ANTHROPIC_BASE_URL": "https://open.bigmodel.cn/api/anthropic",
    "ANTHROPIC_AUTH_TOKEN": "xxxxxxxx",
    "API_TIMEOUT_MS": "3000000",
    "CLAUDE_CODE_DISABLE_NONESSENTIAL_TRAFFIC": "1"
  },
  "alwaysThinkingEnabled": true
}
```

4. 使用 Docker Compose 启动容器（推荐）。

创建 `docker-compose.yml` 文件：

```yaml
services:
  progress:
    image: jukanntenn/progress:latest
    container_name: progress
    volumes:
      - ./config.toml:/app/config.toml:ro
      - ./claude_settings.json:/root/.claude/settings.json:ro
      - ./data:/app/data
    environment:
      - PROGRESS_SCHEDULE_CRON=0 8 * * * # 每天 8:00 运行
    restart: always
```

启动容器：

```bash
docker-compose up -d
```

5. 或使用 Docker 命令直接运行：

```bash
docker run --rm \
  -v $(pwd)/config.toml:/app/config.toml:ro \
  -v $(pwd)/claude_settings.json:/root/.claude/settings.json:ro \
  -v $(pwd)/data:/app/data \
  jukanntenn/progress:latest
```

6. 查看容器日志，确认程序正常运行：

```bash
docker-compose logs -f
```

或使用 Docker 命令：

```bash
docker logs -f progress
```

7. 验证定时任务配置是否正确，查看容器日志确认程序按预期时间运行。

### 在宿主机上运行

1. 克隆项目到本地：

```bash
git clone https://github.com/your-username/progress.git
cd progress
```

2. 安装 Python 依赖：

使用 uv（推荐）：

```bash
uv sync
```

或使用 pip：

```bash
pip install -r requirements.txt
```

3. 创建配置文件：

```bash
cp config.example.toml config.toml
```

4. 编辑配置文件，填写必要的配置项（详见[配置说明](#配置说明)）：

```bash
vim config.toml
```

确保已安装并配置好 Claude Code CLI，保证程序可以正常调用。

5. 运行程序：

```bash
uv run progress -c config.toml
```

或使用 pip 安装的方式：

```bash
python -m progress.cli -c config.toml
```

首次运行时，程序会自动克隆配置的仓库到本地数据目录，检测代码变更，生成 diff 并进行 AI 分析，最后生成报告并通过配置的通知方式推送。

6. 持续跟踪需定期运行程序，详见[定时任务配置](#定时任务配置)。

## 配置说明

配置通过 `config.toml` 文件管理，复制 `config.example.toml` 作为起始模板。

### 配置项优先级

配置项的优先级从高到低为：**环境变量 > 配置文件 > 默认值**

环境变量可以覆盖配置文件中的任意值。

### 配置文件

#### 基本配置结构

```toml
# 时区配置（可选，默认：UTC）
timezone = "UTC"

# 应用程序语言（可选，默认：en）
# 控制用户界面文本的语言
language = "en"

[markpost]
# Markpost 发布 URL（必需）
url = "https://markpost.example.com/p/your-post-key"
# HTTP 请求超时时间（秒，默认：30）
timeout = 30

[notification]
[notification.feishu]
# 飞书 webhook URL（必需）
webhook_url = "https://open.feishu.cn/open-apis/bot/v2/hook/xxx"
# HTTP 请求超时时间（秒，默认：30）
timeout = 30

[notification.email]
# 邮件通知配置（可选）
host = "smtp.example.com"
port = 587
user = "user@example.com"
password = "password"
from_addr = "progress@example.com"  # 发件地址（默认：progress@example.com）
recipient = ["recipient@example.com"]  # 收件人列表
starttls = false  # STARTTLS（默认：false）
ssl = false  # SSL（默认：false）

[github]
# GitHub CLI token（必需）
gh_token = "ghp_xxxxxxxxxxxxxxxxxxxx"
# 全局协议配置（可选，默认：https）
protocol = "https"
# 全局代理配置（可选）
# 支持 HTTP/HTTPS/SOCKS5 代理，例如：
# proxy = "http://127.0.0.1:7890"
# proxy = "socks5://127.0.0.1:1080"
proxy = ""
# Git 命令超时时间（秒，默认：300）
git_timeout = 300
# GitHub CLI 命令超时时间（秒，默认：300）
gh_timeout = 300

[analysis]
# 最大 diff 长度（字符数，默认：100000）
max_diff_length = 100000
# 并发数（可选，默认：1 为串行）
concurrency = 1
# Claude Code 分析超时时间（秒，默认：600）
timeout = 600
# AI 分析输出语言（可选，默认：en）
# 支持任何语言代码（如：zh、en、ja、ko、fr、de、es、pt、ru、ar 等）
# 与顶层 language 配置相互独立
language = "zh"

# 仓库配置（至少配置一个）
[[repos]]
# GitHub 仓库格式：owner/repo（推荐格式，简洁明了）
url = "vitejs/vite"
# 监控分支（可选，默认：main）
branch = "main"
# 是否启用（可选，默认：true）
enabled = true
# 仓库级协议配置（可选，覆盖全局配置）
# protocol = "ssh"

[[repos]]
url = "facebook/react"
# 未指定分支，默认为 main

[[repos]]
# 支持完整 HTTPS URL 格式
url = "https://github.com/vitejs/vite.git"

[[repos]]
# 支持 SSH URL 格式（适用于配置了 SSH key 的场景）
url = "git@github.com:vitejs/vite.git"

[[repos]]
url = "vue/core"
# 仓库级协议配置，覆盖全局配置
protocol = "ssh"

[[repos]]
url = "mycompany/private-repo"
branch = "develop"
enabled = false  # 暂时禁用
```

#### 配置项说明

**必需配置项：**

- `markpost.url` - Markpost 发布 URL（访问 [Markpost](https://markpost.cc/) 获取）
- `notification.feishu.webhook_url` - 飞书 webhook URL（参见 [自定义机器人使用指南](https://open.feishu.cn/document/client-docs/bot-v3/add-custom-bot)）
- `github.gh_token` - GitHub CLI token（参见 [管理个人访问令牌](https://docs.github.com/zh/authentication/keeping-your-account-and-data-secure/managing-your-personal-access-tokens)）
- `repos` - 至少配置一个仓库

**可选配置项：**

- `timezone` - 时区配置，默认 UTC
- `language` - 应用程序语言，默认 en
- `markpost.timeout` - Markpost HTTP 请求超时时间，默认 30 秒
- `notification.feishu.timeout` - 飞书 HTTP 请求超时时间，默认 30 秒
- `notification.email.*` - 邮件通知配置（整个 section 可选）
- `github.protocol` - Git 协议，默认 https
- `github.proxy` - 代理配置，默认为空
- `github.git_timeout` - Git 命令超时时间，默认 300 秒
- `github.gh_timeout` - GitHub CLI 命令超时时间，默认 300 秒
- `analysis.max_diff_length` - 最大 diff 长度，默认 100000 字符
- `analysis.concurrency` - 并发分析数，默认 1
- `analysis.timeout` - 分析超时时间，默认 600 秒
- `analysis.language` - AI 分析输出语言，默认 en
- `repos[].branch` - 仓库分支，默认 main
- `repos[].enabled` - 是否启用，默认 true
- `repos[].protocol` - 仓库级协议配置

### 环境变量

可以使用环境变量覆盖任意配置值，使用 `PROGRESS__` 前缀。

#### 命名规则

格式：`PROGRESS__<SECTION>__<KEY>`

- `PROGRESS__` 是固定前缀
- `<SECTION>` 是配置节的名称
- `<KEY>` 是配置项的名称
- 使用双下划线 `__` 分隔嵌套层级

#### 环境变量示例

```bash
# 覆盖 GitHub token
export PROGRESS__GITHUB__GH_TOKEN="ghp_your_token_here"

# 覆盖飞书 webhook URL
export PROGRESS__NOTIFICATION__FEISHU__WEBHOOK_URL="https://open.feishu.cn/..."

# 覆盖 Markpost URL
export PROGRESS__MARKPOST__URL="https://markpost.cc/your-post-key"

# 覆盖代理配置
export PROGRESS__GITHUB__PROXY="http://127.0.0.1:7890"

# 覆盖分析语言
export PROGRESS__ANALYSIS__LANGUAGE="en"

# 覆盖时区
export PROGRESS__TIMEZONE="Asia/Shanghai"
```

#### Docker 部署使用环境变量

在 Docker 部署时，通过环境变量配置敏感信息尤其方便：

```yaml
# docker-compose.yml
services:
  progress:
    image: jukanntenn/progress:latest
    container_name: progress
    volumes:
      - ./config.toml:/app/config.toml:ro
      - ./claude_settings.json:/root/.claude/settings.json:ro
      - ./data:/app/data
    environment:
      # 通过环境变量覆盖敏感配置
      - PROGRESS__GITHUB__GH_TOKEN=${GH_TOKEN}
      - PROGRESS__NOTIFICATION__FEISHU__WEBHOOK_URL=${FEISHU_WEBHOOK}
      - PROGRESS__MARKPOST__URL=${MARKPOST_URL}
      - PROGRESS_SCHEDULE_CRON=0 8 * * *
    restart: always
```

配合 `.env` 文件使用：

```bash
# .env
GH_TOKEN=ghp_xxxxxxxxxxxxxxxxxxxx
FEISHU_WEBHOOK=https://open.feishu.cn/open-apis/bot/v2/hook/xxx
MARKPOST_URL=https://markpost.cc/your-post-key
```

### 最小化配置示例

只包含必需配置项的最小化 `config.toml`：

```toml
[markpost]
url = "https://markpost.cc/your-post-key"

[notification.feishu]
webhook_url = "https://open.feishu.cn/open-apis/bot/v2/hook/xxx"

[github]
gh_token = "ghp_xxxxxxxxxxxxxxxxxxxx"

[[repos]]
url = "vitejs/vite"
```

所有其他配置项将使用默认值。

## 定时任务配置

### 宿主机定时任务

在宿主机上运行时，需要使用系统自带的调度工具配置定时任务。crontab 示例：

编辑 crontab：

```bash
crontab -e
```

添加定时任务配置：

```bash
# 每天早上 8 点运行
0 8 * * * cd /path/to/progress && uv run progress -c config.toml
```

Crontab 时间格式说明：

```text
┌───────────── 分钟 (0 - 59)
│ ┌───────────── 小时 (0 - 23)
│ │ ┌───────────── 日期 (1 - 31)
│ │ │ ┌───────────── 月份 (1 - 12)
│ │ │ │ ┌───────────── 星期 (0 - 7，周日为 0 或 7)
│ │ │ │ │
* * * * *
```

### Docker 定时任务

在 Docker 容器中运行时，通过环境变量配置定时任务。

编辑 `docker-compose.yml`，添加 `PROGRESS_SCHEDULE_CRON` 环境变量：

```yaml
services:
  progress:
    image: jukanntenn/progress:latest
    container_name: progress
    volumes:
      - ./config.toml:/app/config.toml:ro
      - ./claude_settings.json:/root/.claude/settings.json:ro
      - ./data:/app/data
    environment:
      # 配置定时任务（每天 8:00 运行）
      - PROGRESS_SCHEDULE_CRON=0 8 * * *
    restart: always
```

配置完成后重启容器使配置生效：

```bash
docker-compose down
docker-compose up -d
```
