# Web E2E Tests (Playwright)

End-to-end browser tests that drive the real production container (Caddy +
FastAPI, single image) with zero mocking. Playwright runs on the host; the
container is brought up with the project's local acceptance compose file.

```
┌──────────────┐     ┌──────────────────────────┐
│  Playwright  │────▶│   App Container          │
│  (host)      │HTTP │   Caddy :5000            │
└──────────────┘     │   → FastAPI :8000        │
                     │   → SQLite (/app/data)   │
                     └──────────────────────────┘
```

## Why a separate package

`web/` runs Vitest component tests with jsdom + MSW. Playwright here drives the
full stack through a real browser against the production image, so it lives in
its own package (`web/e2e/`) with its own `@playwright/test` dependency. This
keeps the two concerns — unit/component vs. end-to-end — and their dependency
footprints isolated.

## Prerequisites

- Docker running on the host
- `pnpm` (or `npm`) for installing Playwright in `web/e2e/`

## Quick start

```bash
# 1. Build & start the container (config + data via env vars + named volume).
docker compose -f docker/docker-compose.local.yml up -d --build --wait

# 2. Sanity check.
curl -fsS http://localhost:5000/healthz      # {"status":"ok"}

# 3. Install Playwright + browsers (first time only).
cd web/e2e
pnpm install
pnpm exec playwright install --with-deps chromium

# 4. Run the suite.
pnpm test

# 5. Tear down (wipes the data volume).
cd ../..
docker compose -f docker/docker-compose.local.yml down -v
```

## Running a single test

```bash
cd web/e2e
pnpm exec playwright test tests/smoke.spec.ts -g "healthz"
```

## Layout

```
web/e2e/
├── package.json          # @playwright/test only
├── playwright.config.ts  # baseURL=http://localhost:5000, workers:1, no webServer
├── lib/
│   ├── fixtures.ts       # auto-use `backendReady` (waits on /healthz)
│   └── helpers.ts        # waitForBackend, getConfig, putConfigSection, seedReport, deleteReports
├── tests/
│   ├── smoke.spec.ts              # healthz/readyz/version, SPA redirect, no console errors
│   ├── config-flow.spec.ts        # config edit → DB → UI render → reload
│   └── reports-and-config.spec.ts # report detail render (headings/TOC/<details>), Test Notifications button, dirty-guard dialog
└── HANDBOOK.md           # this file
```

## Conventions

- **Serial, single worker.** The suite shares one container and one DB; the
  config-flow test mutates the `core` section, so tests must not run in
  parallel. `playwright.config.ts` enforces `workers: 1`.
- **Clean up after yourself.** `config-flow.spec.ts` restores the timezone in
  `afterAll`. New tests that mutate state must do the same.
- **Seeding report rows.** The reports API is read-only (no POST), so tests
  that need a rendered report insert one directly into the container's DB via
  `seedReport()` / `deleteReports()` (`lib/helpers.ts`). These shell out to
  `docker compose exec` and run the app's own `init_db`/`Report.create` helpers
  in-process (so WAL pragmas stay consistent with the live connection). Always
  `deleteReports([...])` the ids you created in `afterAll`.
- **Lock the locale.** The SPA defaults its locale from `navigator.language`;
  tests that assert on English text set `localStorage.progress.locale = "en"`
  via `page.addInitScript` first.
- **Prefer `getByRole`.** Selectors target role + accessible name (i18n
  strings) rather than CSS classes, which change.

## CI

`.github/workflows/e2e.yml` brings the compose stack up, installs Playwright,
runs the suite, and tears down on every PR that touches `src/`, `web/src/`,
`docker/`, or `web/e2e/`. Documentation-only changes do not trigger it.

## Troubleshooting

- **Port 5000 already in use** — another container or process holds it. Stop it
  or edit the port mapping in `docker/docker-compose.local.yml`.
- **`/healthz` never returns 200** — the container is still starting (migrations
  - lifespan). `--wait` and the healthcheck handle this; bump `start_period` if
    your machine is slow.
- **Flaky SPA assertion** — the lazy-loaded routes mount after navigation; add
  `await page.waitForLoadState("networkidle")` before asserting.
