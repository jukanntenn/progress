import { test, expect } from '../lib/fixtures'
import { BASE_URL, loginAsAdmin } from '../lib/helpers'
import type { APIRequestContext } from '@playwright/test'

test.describe('smoke', () => {
  test('healthz returns ok', async ({ request }) => {
    const resp = await request.get(`${BASE_URL}/healthz`)
    expect(resp.status()).toBe(200)
    expect(await resp.json()).toEqual({ status: 'ok' })
  })

  test('readyz returns ok (DB reachable)', async ({ request }) => {
    const resp = await request.get(`${BASE_URL}/readyz`)
    expect(resp.ok()).toBeTruthy()
  })

  test('version endpoint is reachable (auth required)', async ({ request }) => {
    const token = await loginAsAdmin(request as unknown as APIRequestContext)
    const resp = await request.get(`${BASE_URL}/api/v1/version`, {
      headers: { Authorization: `Bearer ${token}` },
    })
    expect(resp.ok()).toBeTruthy()
    const body = await resp.json()
    expect(body).toHaveProperty('version')
  })

  test('root path redirects to /login when unauthenticated', async ({ page }) => {
    await page.goto('/')
    await expect(page).toHaveURL(/\/login/)
  })

  test('SPA loads with no console errors', async ({ page }) => {
    const errors: string[] = []
    page.on('pageerror', (err) => errors.push(err.message))
    await page.goto('/reports')
    // Unauthenticated visit redirects to /login (no error expected).
    await expect(page).toHaveURL(/\/login|\/reports/)
    await page.waitForLoadState('networkidle')
    expect(errors, errors.join('\n')).toEqual([])
  })
})
