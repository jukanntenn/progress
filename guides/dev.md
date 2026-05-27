# Development Guide

## Development Server

Run backend and frontend in separate terminals:

```bash
# Terminal 1: Backend (FastAPI)
uv run progress serve --reload

# Terminal 2: Frontend (Next.js)
cd web
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

## Development Environment Manager

Use the `dev.py` script to manage all services:

```bash
# Start all services
python devops/dev.py start

# Stop all services
python devops/dev.py stop
```

## VS Code Tasks

Use `Ctrl+Shift+P` > "Tasks: Run Task" to start services:

- **Start Backend**: Starts the FastAPI backend with hot reload
- **Start Frontend**: Starts the Next.js frontend with Turbopack
- **Start All**: Starts both services in parallel

## Production Deployment

Use Docker Compose for production. The development servers are for local development only.

**Security Warning**: Hot reload is enabled by default in `progress serve`. Never use it in production.

### Docker Build

```bash
# Build both images
python docker/build.py

# Build only backend
python docker/build.py --image backend

# Build only frontend
python docker/build.py --image frontend

# Build and push to registry
python docker/build.py --push
```

### Docker Compose

```bash
# Start all services
docker compose up -d

# View logs
docker compose logs -f

# Stop all services
docker compose down
```

### Ansible Deployment

```bash
# Deploy to production
ansible-playbook -i devops/ansible/hosts.yml devops/ansible/main.yml --vault-password-file ~/.ansible-vault/progress.pwd
```
