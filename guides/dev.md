# Development Guide

## Development Server

Run backend and frontend in separate terminals:

```bash
# Terminal 1: Backend (FastAPI)
PYTHONPATH=src CONFIG_FILE=config.toml uv run fastapi dev

# Terminal 2: Frontend (Next.js)
cd web
pnpm dev
```

The frontend proxies `/api/*` requests to the backend via Next.js rewrites configured in `next.config.ts`.

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

Production uses a single Docker container with Caddy, FastAPI, and Next.js managed by s6-overlay.

### Docker Build

```bash
# Build image
python docker/build.py

# Build and push to registry
python docker/build.py --push

# Build for specific platform
python docker/build.py --platform amd64

# No cache
python docker/build.py --no-cache
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
