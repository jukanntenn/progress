# progress architecture

English | [中文](architecture.zh.md)

Read this before changing the source tree. It is the ordered map of the codebase — components, their boundaries, and where new behavior goes; decision rationale lives in the linked RFCs.

## What this package is

progress is a GitHub project tracking tool: it traces multi-repo code changes, runs AI analysis over them, and generates progress reports (Web UI, RSS, notifications) for the open-source projects a user follows. Operators run the pipeline on a schedule through the `progress` CLI and read results through the FastAPI-served SPA.

## Components

| Component | Responsibility | Public surface |
|---|---|---|
| `src/progress/config/` | Layered config sources + DB seed merge | `progress.config.CoreConfig` |
| `src/progress/db/` | Tortoise models, shared migrations | `init_db` / `close_db` |
| `src/progress/integrations/` | Business plugins, one package each (repo, changelog, proposal, feed, v2ex) | `@register("<name>")` |
| `src/progress/kernel/` | Cordis-semantics plugin kernel (fibers, events, patches) | `boot` / `Entry` / `Context` |
| `src/progress/runtime/` | The app's own plugins + composition | `compose_serve` / `compose_base` |
| `src/progress/observability/` | OTel + structlog + Bugsink wiring | `setup_observability` |
| `src/progress/utils/` | Pure helpers (http, templating, markdown, i18n) | — |
| `src/progress/cli/` | Typer entry: run/serve/users/plugin + reports, notifications, AI | `progress` command |
| `src/progress/api/` | FastAPI entry package (routes, deps, middleware) | `create_app` |
| `web/` | React 19 + Vite SPA consuming the OpenAPI schema | HTTP `/api` |
| `docker/`, `devops/` | 2-process container; ansible deployment | — |

## Where new behavior goes

A new integration lands as a self-contained package under `src/progress/integrations/<name>/` behind `@register`; a new config item starts in `src/progress/config/schema.py` (then regenerate the OpenAPI contract); a new model in `src/progress/db/models/` with its migration; a new HTTP route in `src/progress/api/routes/`; a report template or notification channel in `src/progress/cli/reports/` or `cli/notifications/channels/`. Agent workflow instructions go to `.agents/skills/`, decision rationale to `.agents/rfcs/` under the [RFC rules](../.agents/rfcs/README.md). The placement rules for prose live in the [documentation standard](AGENTS.md) and the pairing contract in the [bilingual documentation contract](i18n/README.md).

The contributor entry points are in [development.md](development.md).
