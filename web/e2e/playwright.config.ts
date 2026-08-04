import { defineConfig, devices } from '@playwright/test'

// Playwright connects to an already-running container brought up via
// `docker compose -f docker/docker-compose.local.yml up -d`. It does NOT start
// any service itself (no `webServer`). See HANDBOOK.md.
const baseURL = process.env.BASE_URL || 'http://localhost:5000'

export default defineConfig({
  testDir: './tests',
  timeout: 120_000,
  expect: { timeout: 15_000 },
  // Serial, single worker: the suite shares one container/DB and mutates the
  // config section, so parallelism would race.
  fullyParallel: false,
  workers: 1,
  retries: 0,
  reporter: [['list']],
  use: {
    baseURL,
    actionTimeout: 15_000,
    navigationTimeout: 30_000,
    trace: 'on-first-retry',
    locale: 'en-US',
  },
  projects: [
    {
      name: 'chromium',
      use: { ...devices['Desktop Chrome'] },
    },
  ],
})
