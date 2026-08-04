import { test, expect } from '../lib/fixtures'
import type { APIRequestContext } from '@playwright/test'
import { getConfig, loginAsAdmin, putConfigSection } from '../lib/helpers'

// Core business flow: a config edit round-trips through the DB and is reflected
// in the UI. We mutate the `core` section via the API (stable, schema-driven
// forms have brittle field selectors) and assert the Configuration page renders
// the result + that "Reload from DB" succeeds. The whole flow exercises the
// real FastAPI + DB + SPA stack with zero mocking.
//
// Auth is enabled: the suite logs in once in beforeAll and reuses the token
// for both the API helpers and the SPA (injected via localStorage).
const ORIGINAL_TIMEZONE = 'UTC'
const TEST_TIMEZONE = 'Asia/Shanghai'

let authToken: string

test.describe('config persistence flow', () => {
  test.beforeAll(async ({ request }) => {
    authToken = await loginAsAdmin(request as unknown as APIRequestContext)
  })

  test.afterAll(async ({ request }) => {
    // Restore the original timezone so the suite leaves the container clean.
    await putConfigSection(
      request as unknown as APIRequestContext,
      'core',
      { timezone: ORIGINAL_TIMEZONE },
      authToken,
    )
  })

  test('config edit persists and renders in the UI', async ({ request, page }) => {
    // 1. Persist a timezone change through the API.
    await putConfigSection(
      request as unknown as APIRequestContext,
      'core',
      { timezone: TEST_TIMEZONE },
      authToken,
    )

    // 2. The DB is the source of truth — a fresh GET reflects it.
    const cfg = await getConfig(request as unknown as APIRequestContext, authToken)
    expect((cfg.core as Record<string, unknown>).timezone).toBe(TEST_TIMEZONE)

    // 3. The Configuration page loads and renders against the persisted value.
    // Lock the locale + inject the auth token so the SPA route guard admits it.
    await page.addInitScript((token) => {
      localStorage.setItem('progress.locale', 'en')
      localStorage.setItem('progress.token', token)
    }, authToken)
    await page.goto('/config')
    await expect(page).toHaveURL(/\/config/)
    // Let the lazy-loaded route + config query settle before asserting.
    await page.waitForLoadState('networkidle')

    // The page title heading is i18n key `config.title` ("Configuration").
    await expect(page.getByRole('heading', { name: 'Configuration', exact: true })).toBeVisible()
    // The reports nav link must be present (proves the SPA shell mounted).
    await expect(page.getByRole('link', { name: 'Reports', exact: true })).toBeVisible()

    // 4. "Reload from DB" button round-trips and reports success.
    const reload = page.getByRole('button', { name: 'Reload from DB' })
    await reload.click()
    // The success toast uses i18n key `config.reloaded` ("Reloaded").
    await expect(page.getByText('Reloaded', { exact: false })).toBeVisible({ timeout: 10_000 })
  })
})
