# Container Build & Deployment Optimization Plan

## Decisions

| # | Topic | Decision |
|---|-------|----------|
| 1 | FastAPI server management | Remove uvicorn, use `fastapi dev` / `fastapi run` CLI commands |
| 2 | `progress serve` command | Remove entirely. Users call `fastapi dev/run` directly |
| 3 | Internal port layout | Caddy `:5000`, FastAPI `127.0.0.1:8000`, Next.js `127.0.0.1:3000` |
| 4 | Caddy routing | `/api/v1/*` → FastAPI, everything else → Next.js |
| 5 | Container modes (s6-overlay) | Always: Caddy + FastAPI + Next.js. Optional: supercronic (gated by `PROGRESS_SCHEDULE_CRON` env var) |
| 6 | Dockerfile stages | 4 stages: python-deps, node-deps (pnpm), node-build, runtime (all Alpine-based) |
| 7 | Dev environment proxy | Add `rewrites` to `next.config.ts`, delete `proxy.ts`. Update `devops/dev.py` to start both services |
| 8 | Affected config/tooling | `.vscode/tasks.json`, `devops/dev.py`, ansible templates, `guides/dev.md` — all updated |
| 9 | Caddy installation | Download prebuilt binary from GitHub releases |
| 10 | Supercronic | Keep as-is, managed as s6-overlay service |
| 11 | `[web]` config section | Remove from config entirely |
| 12 | `web_dist` SPA fallback | Remove from `create_app` (legacy code) |
| 13 | FastAPI workers | Single worker (SQLite concurrency constraint) |
| 14 | Wiki document | Combined document in `wiki/`: integration details + quick-reference |

## Task List

### Phase 1: Backend code changes — DONE
- [x] Update `pyproject.toml`: change `fastapi>=0.115.0` to `fastapi[standard]>=0.115.0`, remove `uvicorn[standard]` dependency
- [x] Remove `progress serve` command from `src/progress/cli.py`
- [x] Remove `[web]` config section from `src/progress/config.py`
- [x] Remove `web_dist` SPA fallback from `src/progress/api/__init__.py`
- [x] Remove `web` section from config editor schema in `src/progress/api/routes/config.py`
- [x] Delete `run_web.py`

### Phase 2: Frontend changes — DONE
- [x] Add `rewrites` to `web/next.config.ts` for dev proxy
- [x] Delete `web/src/proxy.ts`

### Phase 3: Docker & s6-overlay — DONE
- [x] Create `docker/Caddyfile` with routing rules
- [x] Create s6-overlay service definitions under `docker/s6/` (caddy, fastapi, nextjs, cron)
- [x] Rewrite `docker/Dockerfile` as unified multi-stage build
- [x] Delete `docker/Dockerfile.frontend`
- [x] Delete `docker/entrypoint.sh`

### Phase 4: Build & deployment tooling — DONE
- [x] Update `docker/build.py` for single image build
- [x] Update `docker/docker-compose.yml` for single service
- [x] Update `devops/dev.py` to start both backend and frontend
- [x] Update `.vscode/tasks.json` to use `fastapi dev`
- [x] Update `devops/ansible/templates/docker-compose.yml.j2` for single service
- [x] Update `devops/ansible/templates/config.toml.j2` (remove [web] section)
- [x] Update `guides/dev.md` documentation
- [x] Update `CLAUDE.md` and `AGENTS.md`
- [x] Update `README.md` and `README_zh.md`
- [x] Update `config.example.toml`, `config-simple.toml`, `test-config.toml`
- [x] Update `specs/docker/build-specification.md`

### Phase 5: Documentation — DONE
- [x] Create `wiki/container-architecture.md` — combined integration guide + quick-reference
