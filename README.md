# Progress

[简体中文](./README_zh.md) | English

Progress is a GitHub project tracking tool that traces multi-repo code changes, runs AI analysis, and generates reports to help users track open-source project progress.

## Features

- **Multi-repo Monitoring** - Monitor multiple GitHub repositories simultaneously and track code changes
- **Release Tracking** - Automatically track GitHub releases and analyze changes between versions
- **AI-Powered Analysis** - Use Claude Code CLI to analyze code changes and generate Markdown analysis reports
- **Notifications** - Support for Feishu and email notifications to deliver analysis reports timely
- **Web Service** - Built-in web interface for browsing aggregated reports and RSS feed support
- **Docker Deployment** - Containerized deployment with Docker, ready to run in as fast as one minute

## Requirements

### Docker Deployment

- [Docker Engine](https://docs.docker.com/engine/install/) required

### Host Machine Deployment

- Python 3.12 or higher
- [uv package manager](https://github.com/astral-sh/uv) (recommended) or pip
- [GitHub CLI](https://cli.github.com/)
- [Claude Code CLI](https://claude.com/product/claude-code)

## Quick Start

### Running in Docker

1. Prepare the configuration file:

```bash
cp config.example.toml config.toml
```

Edit the configuration file and fill in the required items (see [Configuration](#configuration) for details).

2. Create a data directory for persistent storage:

```bash
mkdir -p data
```

3. Prepare the Claude Code configuration file. Copy your local Claude Code configuration to the project directory:

```bash
cp ~/.claude/settings.json ./claude_settings.json
```

Minimal `claude_settings.json` example:

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

4. Start the container using Docker Compose (recommended).

Create a `docker-compose.yml` file:

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
      - PROGRESS_SCHEDULE_CRON=0 8 * * * # Run daily at 8:00 AM
    restart: always
```

Start the container:

```bash
docker-compose up -d
```

5. Or run directly with Docker command:

```bash
docker run --rm \
  -v $(pwd)/config.toml:/app/config.toml:ro \
  -v $(pwd)/claude_settings.json:/root/.claude/settings.json:ro \
  -v $(pwd)/data:/app/data \
  jukanntenn/progress:latest
```

6. View container logs to confirm the program is running properly:

```bash
docker-compose logs -f
```

Or using Docker command:

```bash
docker logs -f progress
```

7. Verify the scheduled task configuration is correct by checking container logs to ensure the program runs as expected.

### Running on Host Machine

1. Clone the project to local:

```bash
git clone https://github.com/your-username/progress.git
cd progress
```

2. Install Python dependencies:

Using uv (recommended):

```bash
uv sync
```

Or using pip:

```bash
pip install -r requirements.txt
```

3. Create configuration file:

```bash
cp config.example.toml config.toml
```

4. Edit the configuration file and fill in the required items (see [Configuration](#configuration) for details):

```bash
vim config.toml
```

Ensure Claude Code CLI is installed and configured properly so the program can invoke it.

5. Run the program:

```bash
uv run progress -c config.toml
```

Or using pip installation:

```bash
python -m progress.cli -c config.toml
```

On first run, the program will automatically clone configured repositories to the local data directory, detect code changes, generate diffs, perform AI analysis, generate reports, and push them via configured notification methods.

6. For continuous tracking, run the program regularly. See [Scheduled Task Configuration](#scheduled-task-configuration).

## Configuration

Configuration is managed through the `config.toml` file. Copy `config.example.toml` as a starting template.

### Configuration Priority

The priority of configuration items from high to low is: **Environment Variables > Configuration File > Default Values**

Environment variables can override any value in the configuration file.

### Configuration File

#### Basic Configuration Structure

```toml
# Timezone configuration (optional, default: UTC)
timezone = "UTC"

# Application language (optional, default: en)
# Controls the language of user interface text
language = "en"

[markpost]
# Markpost publish URL (required)
url = "https://markpost.example.com/p/your-post-key"
# HTTP request timeout (seconds, default: 30)
timeout = 30
# Maximum batch size for uploads (bytes, default: 1048576)
# Reports larger than this will be split into multiple batches
max_batch_size = 1048576

[notification]

[[notification.channels]]
type = "feishu"
enabled = true
# Feishu webhook URL (required)
webhook_url = "https://open.feishu.cn/open-apis/bot/v2/hook/xxx"
# HTTP request timeout (seconds, default: 30)
timeout = 30

[[notification.channels]]
type = "email"
enabled = false
# Email notification configuration
host = "smtp.example.com"
port = 587
user = "user@example.com"
password = "password"
from_addr = "progress@example.com"  # Sender address (default: progress@example.com)
recipient = ["recipient@example.com"]  # Recipient list
starttls = false  # STARTTLS (default: false)
ssl = false  # SSL (default: false)

[github]
# GitHub CLI token (required)
gh_token = "ghp_xxxxxxxxxxxxxxxxxxxx"
# Global protocol configuration (optional, default: https)
protocol = "https"
# Global proxy configuration (optional)
# Supports HTTP/HTTPS/SOCKS5 proxies, for example:
# proxy = "http://127.0.0.1:7890"
# proxy = "socks5://127.0.0.1:1080"
proxy = ""
# Git command timeout (seconds, default: 300)
git_timeout = 300
# GitHub CLI command timeout (seconds, default: 300)
gh_timeout = 300

[analysis]
# Maximum diff length (characters, default: 100000)
max_diff_length = 100000
# Concurrency level (optional, default: 1 for serial execution)
concurrency = 1
# Claude Code analysis timeout (seconds, default: 600)
timeout = 600
# AI analysis output language (optional, default: en)
# Supports any language code (e.g., zh, en, ja, ko, fr, de, es, pt, ru, ar, etc.)
# This is independent from the top-level language setting
language = "zh"

[web]
# Enable or disable web service (optional, default: false)
# When enabled, a web server will start alongside the scheduled tasks
enabled = false
# Web service host address (optional, default: 0.0.0.0)
# Use 0.0.0.0 to listen on all interfaces
host = "0.0.0.0"
# Web service port (optional, default: 5000)
port = 5000
# Debug mode (optional, default: false)
# WARNING: Debug mode should NEVER be enabled in production
# For development, use 'progress serve' which auto-enables debug mode
debug = false
# Auto-reload (optional, default: true)
# Controls whether the dev server auto-reloads on file changes
reload = true

# Repository configuration (at least one required)
[[repos]]
# GitHub repository format: owner/repo (recommended format, concise and clear)
url = "vitejs/vite"
# Monitored branch (optional, default: main)
branch = "main"
# Whether enabled (optional, default: true)
enabled = true
# Repository-level protocol configuration (optional, overrides global configuration)
# Default: https
# protocol = "ssh"

[[repos]]
url = "facebook/react"
# Branch not specified, defaults to main

[[repos]]
# Supports full HTTPS URL format
url = "https://github.com/vitejs/vite.git"

[[repos]]
# Supports SSH URL format (for scenarios with SSH key configured)
url = "git@github.com:vitejs/vite.git"

[[repos]]
url = "vue/core"
# Repository-level protocol configuration, overrides global configuration
protocol = "ssh"

[[repos]]
url = "mycompany/private-repo"
branch = "develop"
enabled = false  # Temporarily disabled

# Owner monitoring configuration (optional)
[[owners]]
type = "organization"  # "user" or "organization"
name = "bytedance"
enabled = true

[[owners]]
type = "user"
name = "torvalds"
enabled = true
```

#### Configuration Item Description

**Required Configuration Items:**

- `markpost.url` - Markpost publish URL (get it from [Markpost](https://markpost.cc/))
- `notification.feishu.webhook_url` - Feishu webhook URL (see [Custom Bot Usage Guide](https://open.feishu.cn/document/client-docs/bot-v3/add-custom-bot))
- `github.gh_token` - GitHub CLI token (see [Managing Personal Access Tokens](https://docs.github.com/en/authentication/keeping-your-account-and-data-secure/managing-your-personal-access-tokens))
- `repos` - At least one repository must be configured

**Optional Configuration Items:**

- `timezone` - Timezone configuration, default UTC
- `language` - Application language, default en
- `markpost.timeout` - Markpost HTTP request timeout, default 30 seconds
- `markpost.max_batch_size` - Maximum batch size for uploads in bytes, default 1048576 (1MB). Reports larger than this will be split into multiple batches for uploading
- `notification.feishu.timeout` - Feishu HTTP request timeout, default 30 seconds
- `notification.email.*` - Email notification configuration (entire section optional)
- `github.protocol` - Git protocol, default https
- `github.proxy` - Proxy configuration, default empty
- `github.git_timeout` - Git command timeout, default 300 seconds
- `github.gh_timeout` - GitHub CLI command timeout, default 300 seconds
- `analysis.max_diff_length` - Maximum diff length, default 100000 characters
- `analysis.concurrency` - Concurrent analysis count, default 1
- `analysis.timeout` - Analysis timeout, default 600 seconds
- `analysis.language` - AI analysis output language, default en
- `web.enabled` - Enable or disable web service, default false
- `web.host` - Web service host address, default 0.0.0.0
- `web.port` - Web service port, default 5000
- `web.debug` - Debug mode (development only), default false
- `web.reload` - Auto-reload on file changes (development only), default true
- `repos[].branch` - Repository branch, default main
- `repos[].enabled` - Whether enabled, default true
- `repos[].protocol` - Repository-level protocol configuration, default https
- `owners` - Owner monitoring configuration (optional)
- `owners[].type` - Owner type, "user" or "organization"
- `owners[].name` - Owner name (cannot be empty)
- `owners[].enabled` - Whether enabled, default true

### Environment Variables

You can use environment variables to override any configuration value using the `PROGRESS__` prefix.

#### Naming Convention

Format: `PROGRESS__<SECTION>__<KEY>`

- `PROGRESS__` is a fixed prefix
- `<SECTION>` is the configuration section name
- `<KEY>` is the configuration item name
- Use double underscore `__` to separate nested levels

#### Environment Variable Examples

```bash
# Override GitHub token
export PROGRESS__GITHUB__GH_TOKEN="ghp_your_token_here"

# Override Feishu webhook URL
export PROGRESS__NOTIFICATION__FEISHU__WEBHOOK_URL="https://open.feishu.cn/..."

# Override Markpost URL
export PROGRESS__MARKPOST__URL="https://markpost.cc/your-post-key"

# Override proxy configuration
export PROGRESS__GITHUB__PROXY="http://127.0.0.1:7890"

# Override analysis language
export PROGRESS__ANALYSIS__LANGUAGE="en"

# Override timezone
export PROGRESS__TIMEZONE="Asia/Shanghai"
```

#### Using Environment Variables in Docker Deployment

When deploying with Docker, it's especially convenient to configure sensitive information through environment variables:

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
      # Override sensitive configuration via environment variables
      - PROGRESS__GITHUB__GH_TOKEN=${GH_TOKEN}
      - PROGRESS__NOTIFICATION__FEISHU__WEBHOOK_URL=${FEISHU_WEBHOOK}
      - PROGRESS__MARKPOST__URL=${MARKPOST_URL}
      - PROGRESS_SCHEDULE_CRON=0 8 * * *
    restart: always
```

Use with `.env` file:

```bash
# .env
GH_TOKEN=ghp_xxxxxxxxxxxxxxxxxxxx
FEISHU_WEBHOOK=https://open.feishu.cn/open-apis/bot/v2/hook/xxx
MARKPOST_URL=https://markpost.cc/your-post-key
```

### Minimal Configuration Example

A minimal `config.toml` with only required configuration items:

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

All other configuration items will use default values.

## Scheduled Task Configuration

### Host Machine Scheduled Tasks

When running on the host machine, you need to use the system's built-in scheduling tool to configure scheduled tasks. Crontab example:

Edit crontab:

```bash
crontab -e
```

Add scheduled task configuration:

```bash
# Run every day at 8:00 AM
0 8 * * * cd /path/to/progress && uv run progress -c config.toml
```

Crontab time format explanation:

```text
┌───────────── Minute (0 - 59)
│ ┌───────────── Hour (0 - 23)
│ │ ┌───────────── Day of month (1 - 31)
│ │ │ ┌───────────── Month (1 - 12)
│ │ │ │ ┌───────────── Day of week (0 - 7, Sunday is 0 or 7)
│ │ │ │ │
* * * * *
```

### Docker Scheduled Tasks

When running in a Docker container, configure scheduled tasks through environment variables.

Edit `docker-compose.yml` and add the `PROGRESS_SCHEDULE_CRON` environment variable:

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
      # Configure scheduled task (runs daily at 8:00 AM)
      - PROGRESS_SCHEDULE_CRON=0 8 * * *
    restart: always
```

After configuration is complete, restart the container for the changes to take effect:

```bash
docker-compose down
docker-compose up -d
```

## Web Service

Progress includes a built-in web service that allows you to browse aggregated reports and subscribe via RSS.

### Enabling Web Service

To enable the web service, add the `[web]` section to your `config.toml`:

```toml
[web]
enabled = true
host = "0.0.0.0"
port = 5000
```

### Accessing the Web Interface

Once enabled, the web service will automatically start when the container launches. You can access:

- **Report List**: `http://your-host:5000/` - Browse all aggregated reports with pagination (50 reports per page)
- **Report Detail**: `http://your-host:5000/report/<id>` - View full content of a specific report
- **RSS Feed**: `http://your-host:5000/rss` - Subscribe to RSS feed for the latest reports

### Docker Compose Configuration

When using Docker, you'll need to expose the web service port:

```yaml
services:
  progress:
    image: jukanntenn/progress:latest
    container_name: progress
    volumes:
      - ./config.toml:/app/config.toml:ro
      - ./claude_settings.json:/root/.claude/settings.json:ro
      - ./data:/app/data
    ports:
      - "5000:5000"  # Expose web service port
    environment:
      - PROGRESS_SCHEDULE_CRON=0 8 * * *
    restart: always
```

### Using RSS

You can subscribe to the RSS feed using any RSS reader:

1. Copy the RSS URL: `http://your-host:5000/rss`
2. Add it to your favorite RSS reader (e.g., Feedly, Inoreader, NetNewsWire)
3. Receive updates when new aggregated reports are generated

The RSS feed includes the 50 most recent reports.

## Development Server

Progress includes a built-in development server with hot reload support for convenient web interface development.

### Starting the Development Server

To start the development server:

```bash
# Start dev server with hot reload (default: 0.0.0.0:5000)
uv run progress serve

# Custom host/port
uv run progress serve --host 127.0.0.1 --port 8000

# Disable debug mode
uv run progress serve --no-debug

# With custom config file
uv run progress -c custom.toml serve
```

### Development Server Features

- **Hot Reload**: Automatically restarts the server when you modify Python files
- **Debug Mode**: Enabled by default with interactive debugger and detailed error pages
- **Config Override**: Override host, port, and debug settings via command-line options

### Production Deployment

For production deployments, continue using Docker with gunicorn as documented in the [Web Service](#web-service) section. The development server (`progress serve`) is intended for local development only.

### Security Note

The development server enables debug mode by default, which should NEVER be used in production. The production Docker deployment uses gunicorn and is not affected by these development settings.


