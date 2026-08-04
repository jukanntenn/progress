import { test, expect } from '../lib/fixtures'
import { BASE_URL, ADMIN_USERNAME, ADMIN_PASSWORD, loginAsAdmin } from '../lib/helpers'

test.describe('auth', () => {
  test('public endpoints work without auth', async ({ request }) => {
    const healthz = await request.get(`${BASE_URL}/healthz`)
    expect(healthz.status()).toBe(200)
    const readyz = await request.get(`${BASE_URL}/readyz`)
    expect(readyz.ok()).toBeTruthy()
    const rss = await request.get(`${BASE_URL}/api/v1/rss`)
    expect(rss.ok()).toBeTruthy()
  })

  test('protected endpoints reject requests without a token', async ({ request }) => {
    for (const path of ['/api/v1/reports', '/api/v1/config', '/api/v1/integrations']) {
      const resp = await request.get(`${BASE_URL}${path}`)
      expect(resp.status(), `${path} should be 401`).toBe(401)
    }
  })

  test('login with correct credentials returns a token', async ({ request }) => {
    const resp = await request.post(`${BASE_URL}/api/v1/auth/login`, {
      data: { username: ADMIN_USERNAME, password: ADMIN_PASSWORD },
    })
    expect(resp.ok()).toBeTruthy()
    const body = await resp.json()
    expect(body.token_type).toBe('bearer')
    expect(body.access_token.length).toBeGreaterThan(0)
  })

  test('login with wrong password is rejected', async ({ request }) => {
    const resp = await request.post(`${BASE_URL}/api/v1/auth/login`, {
      data: { username: ADMIN_USERNAME, password: 'definitely-wrong' },
    })
    expect(resp.status()).toBe(401)
  })

  test('authenticated requests reach protected endpoints', async ({ request }) => {
    const token = await loginAsAdmin(
      request as unknown as import('@playwright/test').APIRequestContext,
    )
    const resp = await request.get(`${BASE_URL}/api/v1/config`, {
      headers: { Authorization: `Bearer ${token}` },
    })
    expect(resp.ok()).toBeTruthy()
  })

  test('/auth/me returns the admin profile', async ({ request }) => {
    const token = await loginAsAdmin(
      request as unknown as import('@playwright/test').APIRequestContext,
    )
    const resp = await request.get(`${BASE_URL}/api/v1/auth/me`, {
      headers: { Authorization: `Bearer ${token}` },
    })
    expect(resp.ok()).toBeTruthy()
    const body = await resp.json()
    expect(body.username).toBe(ADMIN_USERNAME)
    expect(body.is_superuser).toBe(true)
  })

  test('SPA login flow redirects unauthenticated visits to /login', async ({ page }) => {
    await page.goto('/')
    await expect(page).toHaveURL(/\/login/)
  })

  test('SPA login flow grants access after submitting credentials', async ({ page }) => {
    await page.goto('/')
    await expect(page).toHaveURL(/\/login/)
    await page.getByLabel(/username/i).fill(ADMIN_USERNAME)
    await page.locator('#password').fill(ADMIN_PASSWORD)
    await page.getByRole('button', { name: /sign in/i }).click()
    await expect(page).toHaveURL(/\/reports/)
  })
})
