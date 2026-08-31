# AGENTS.md — web/

The Vite SPA (spec 13) and the Playwright e2e workspace. Supplements the root [AGENTS.md](../AGENTS.md); never repeats it.

## Commands

```bash
cd web && pnpm install   # install frontend deps
pnpm dev                 # Vite dev server on :5173, proxies /api to the backend on :8000
pnpm lint                # ESLint
pnpm format              # Prettier
pnpm typecheck           # tsc --noEmit
pnpm test                # Vitest
```

End-to-end (Playwright, needs Docker):

```bash
docker compose -f docker/docker-compose.local.yml up -d --build --wait
cd web/e2e && pnpm install && pnpm exec playwright install chromium && pnpm test
docker compose -f docker/docker-compose.local.yml down -v
```

## Stack

React 19, TypeScript, Vite, Tailwind CSS v4, @base-ui/react + class-variance-authority, @tanstack/react-query v5 + openapi-react-query + openapi-fetch, i18next + react-i18next (en / zh-hans), react-router, pnpm.

## Conventions

- `web/openapi.json` and `web/src/api/schema.ts` are generated artifacts — never hand-edit; the regeneration boundary is a root-level Always-do (see the root AGENTS.md).
- `web/prek.toml` is a prek workspace project: eslint + prettier run with CWD = `web/` and web-relative paths, keeping the root group names (`format` / `lint`).
- UI text lives in the i18n catalogs; integration names come from the backend JSON schema, not hardcoded translations.
- e2e lives in `web/e2e/` (own package.json); see [web/e2e/HANDBOOK.md](e2e/HANDBOOK.md).

## Editing these instructions

`CLAUDE.md` beside this file is a byte-identical copy with no primary: edit either file; [scripts/sync_agent_instructions.py](../scripts/sync_agent_instructions.py) copies the newer side over the older. The word ceiling lives in [scripts/doc_budgets.manifest.json](../scripts/doc_budgets.manifest.json).
