import { test as base, expect, type APIRequestContext } from '@playwright/test'
import { waitForBackend } from './helpers'

// `backendReady` is auto-use: it waits for /healthz once before each test, so
// every test in the suite can assume the container is up without declaring it.
// eslint-disable-next-line @typescript-eslint/no-invalid-void-type -- Playwright fixture value type; `void` is the documented idiom for a side-effect-only fixture.
export const test = base.extend<{ backendReady: void }>({
  backendReady: [
    async ({ request }, use) => {
      await waitForBackend(request as unknown as APIRequestContext)
      await use()
    },
    { auto: true },
  ],
})

export { expect }
