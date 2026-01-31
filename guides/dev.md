# Development Guide

## Development Server

Start the Flask development server with hot reload enabled:

```bash
uv run progress serve
```

### Command Options

- `--host/-h`: Override host from config (default: from config file)
- `--port/-p`: Override port from config (default: from config file)
- `--debug/--no-debug`: Enable/disable debug mode (default: enabled)

### Examples

```bash
# Custom host and port
uv run progress serve --host 127.0.0.1 --port 8000

# Disable debug mode
uv run progress serve --no-debug

# With custom config
uv run progress -c custom.toml serve
```

## Production Deployment

Use Docker with gunicorn for production. The development server is for local development only.

**Security Warning**: Debug mode is enabled by default in `progress serve`. Never use debug mode in production.
