import { test, expect } from '../lib/fixtures'
import type { APIRequestContext } from '@playwright/test'
import { deleteReports, loginAsAdmin, putConfigSection, seedReport } from '../lib/helpers'

// Feature 4 (heading downgrade render), Feature 6 (test-notification button),
// Feature 7 (report-detail rendering: headings, TOC, <details>, sanitize).
//
// The reports API is read-only, so a report is seeded directly into the
// container DB via `docker compose exec` (see seedReport) before the UI tests.
// All seeded rows are cleaned up in afterAll so the container is left pristine.
//
// Auth is enabled, so each test logs in via the API and injects the token into
// localStorage before navigation so the SPA route guard admits the request.

let authToken: string

test.beforeAll(async ({ request }) => {
  authToken = await loginAsAdmin(request as unknown as APIRequestContext)
})

function authInit(token: string) {
  localStorage.setItem('progress.locale', 'en')
  localStorage.setItem('progress.token', token)
}

test.describe('report detail rendering', () => {
  let reportId: number

  test.beforeAll(() => {
    reportId = seedReport({ title: 'Report Detail E2E' }).id
  })

  test.afterAll(() => {
    if (reportId) deleteReports([reportId])
  })

  test('renders downgraded headings, TOC, and <details> block', async ({ page }) => {
    await page.addInitScript(authInit, authToken)
    await page.goto(`/reports/${reportId}`)
    await page.waitForLoadState('networkidle')

    // The h2/h3 headings from SAMPLE_REPORT_CONTENT render (rehype-slug adds ids).
    await expect(page.getByRole('heading', { name: 'Overview', level: 2 })).toBeVisible()
    await expect(page.getByRole('heading', { name: 'Highlights', level: 3 })).toBeVisible()
    await expect(page.getByRole('heading', { name: 'Details', level: 2 })).toBeVisible()
    await expect(page.getByRole('heading', { name: 'Conclusion', level: 2 })).toBeVisible()

    // The fenced code block renders and the `#` line inside it is NOT a heading.
    await expect(page.getByText('# this is a comment, not a heading')).toBeVisible()
    await expect(
      page.getByRole('heading', { name: 'this is a comment, not a heading' }),
    ).toHaveCount(0)

    // The <details>/<summary> block survives sanitization (Feature 7 sanitize
    // allowlist) and renders collapsed by default. <summary> has no role, so
    // target it by its visible text.
    const summary = page.locator('summary', { hasText: 'Commit: fix rendering bug' })
    await expect(summary).toBeVisible()
    // Initially the disclosure is closed (no `open` attribute).
    await expect(page.locator('details').first()).not.toHaveAttribute('open')
    // Opening the disclosure reveals the commit body.
    await summary.click()
    await expect(page.locator('details').first()).toHaveAttribute('open')
    await expect(page.getByText('The commit body explaining the fix.')).toBeVisible()

    // Desktop viewport (lg+) shows the right-side TOC nav with anchor buttons.
    await expect(page.locator('nav').filter({ hasText: 'Overview' })).toBeVisible()
    const tocButtons = page.locator('nav button', {
      hasText: /Overview|Highlights|Details|Conclusion/,
    })
    await expect(tocButtons).toHaveCount(4)

    // TOC anchor clicks scroll to the matching heading (anchor id matches slug).
    await page.locator('nav button', { hasText: 'Conclusion' }).click()
    await expect(page).toHaveURL(new RegExp(`/reports/${reportId}`))
    // The Conclusion heading is now in view.
    await expect(page.getByRole('heading', { name: 'Conclusion', level: 2 })).toBeVisible()
  })

  test('report list shows the seeded report with a detail link', async ({ page }) => {
    await page.addInitScript(authInit, authToken)
    await page.goto('/reports')
    await page.waitForLoadState('networkidle')

    const link = page.getByRole('link', { name: /Report Detail E2E/ })
    await expect(link).toBeVisible()
    // The list row also shows the report_type badge.
    await expect(page.locator('span', { hasText: 'repo_update' }).first()).toBeVisible()
  })
})

test.describe('config console: test notification + dirty guard', () => {
  // The test-notification endpoint is rate-limited to 3/min. The suite is serial
  // and single-worker (playwright.config.ts), so the budget is shared. These
  // tests stay well under the limit (one POST each).

  test('Test Notifications button fires the test notification', async ({ page }) => {
    await page.addInitScript(authInit, authToken)
    await page.goto('/config')
    await page.waitForLoadState('networkidle')
    await expect(page.getByRole('heading', { name: 'Settings', exact: true })).toBeVisible()

    const button = page.getByRole('button', { name: /Test Notifications/i })
    await button.click()

    // The response summary is one of {ok, no_channels, partial_failure}; the
    // i18n toasts are testSuccess / testNoChannels / testPartialFailure. The
    // default container ships a console channel, so summary is usually "ok".
    // Toasts render with role="alert" (see ToastProvider) and auto-dismiss.
    const toast = page.locator("[role='alert']")
    await expect(
      toast.filter({
        hasText:
          /Test notifications sent successfully|No enabled notification channels|Some channels failed/i,
      }),
    ).toBeVisible({ timeout: 15_000 })
  })

  test('editing a config field shows unsaved marker and blocks navigation', async ({
    page,
    request,
  }) => {
    // Pin the timezone to a known value so the edit below is deterministic and
    // the restore in afterEach leaves the container clean for other suites.
    await putConfigSection(
      request as unknown as APIRequestContext,
      'core',
      { timezone: 'UTC' },
      authToken,
    )

    await page.addInitScript(authInit, authToken)
    await page.goto('/config')
    await page.waitForLoadState('networkidle')
    await expect(page.getByRole('heading', { name: 'Settings', exact: true })).toBeVisible()

    // Initially the Core section shows "No changes" (draft == saved).
    await expect(page.getByText('No changes').first()).toBeVisible()

    // The Language field renders as a text input (RJSF schema-driven form);
    // #root_language is the stable RJSF-generated id (label text varies with locale).
    const langInput = page.locator('#root_language')
    await langInput.fill('zh-Hans')

    // The dirty indicator ("Unsaved changes") now appears for that section.
    await expect(page.getByText('Unsaved changes').first()).toBeVisible({ timeout: 5_000 })

    // Navigating away while dirty pops the leave-confirmation dialog (Feature 7).
    await page.getByRole('link', { name: 'Reports', exact: true }).click()
    await expect(page.getByRole('heading', { name: 'Leave this page?' })).toBeVisible()
    await expect(page.getByRole('button', { name: 'Leave', exact: true })).toBeVisible()

    // Cancel keeps the user on /config with the dirty state intact.
    await page.getByRole('button', { name: 'Cancel', exact: true }).click()
    await expect(page).toHaveURL(/\/config/)
    await expect(page.getByText('Unsaved changes').first()).toBeVisible()
  })
})
