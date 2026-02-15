# Development Guide

## Development Server

Run backend and frontend in separate terminals:

```bash
# Terminal 1: Backend (FastAPI)
uv run progress serve --reload

# Terminal 2: Frontend (Vite)
cd src/progress/web
pnpm dev
```

### Command Options

- `--host/-h`: Override host from config (default: from config file)
- `--port/-p`: Override port from config (default: from config file)
- `--reload/--no-reload`: Enable/disable hot reload (default: enabled)

### Examples

```bash
# Custom host and port
uv run progress serve --host 127.0.0.1 --port 8000

# Disable hot reload
uv run progress serve --no-reload

# With custom config
uv run progress -c custom.toml serve
```

## Production Deployment

Use Docker with uvicorn for production. The development servers are for local development only.

**Security Warning**: Hot reload is enabled by default in `progress serve`. Never use it in production.
