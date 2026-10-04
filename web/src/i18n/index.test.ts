import { describe, expect, it, beforeEach, vi } from 'vitest'

import en from './en.json'
import zhHans from './zh-hans.json'

// These tests target ``changeLocale`` (the helper the language switcher and the
// config page both use to sync the SPA locale) and the boot-time
// ``syncLocaleFromServer``. Each test resets the module registry + localStorage
// so the module's import-time side effects re-run in a clean state.

// BCP-47 canonical form. i18next normalizes "zh-Hans"/"zh-hans" to "zh-Hans"
// via Intl.getCanonicalLocales; the resource key must match or lookup misses
// and falls back to English (the long-standing root cause of zh-Hans not
// rendering).
const ZH_HANS = 'zh-Hans'

describe('locale catalogs', () => {
  it('en.json is non-empty', () => {
    expect(Object.keys(en).length).toBeGreaterThan(0)
  })

  it('zh-hans.json is non-empty (T11 regression guard)', () => {
    expect(Object.keys(zhHans).length).toBeGreaterThan(0)
  })
})

describe('changeLocale', () => {
  beforeEach(() => {
    localStorage.clear()
    vi.resetModules()
  })

  it('writes the canonical locale to localStorage so it survives a reload', async () => {
    const { changeLocale } = await import('./index')
    changeLocale('zh-Hans')
    expect(localStorage.getItem('progress.locale')).toBe(ZH_HANS)
  })

  it('migrates legacy lowercase zh-hans to the canonical form', async () => {
    const { changeLocale } = await import('./index')
    changeLocale('zh-hans')
    expect(localStorage.getItem('progress.locale')).toBe(ZH_HANS)
  })

  it('sets document.documentElement.lang for accessibility', async () => {
    const { changeLocale } = await import('./index')
    changeLocale('zh-Hans')
    expect(document.documentElement.lang).toBe(ZH_HANS)
  })

  it('overwrites a previously stored locale', async () => {
    localStorage.setItem('progress.locale', 'zh-Hans')
    const { changeLocale } = await import('./index')
    changeLocale('en')
    expect(localStorage.getItem('progress.locale')).toBe('en')
  })
})

describe('zh-Hans rendering (regression: the recurring "still English" bug)', () => {
  beforeEach(() => {
    localStorage.clear()
    vi.resetModules()
  })

  it('translates keys to Chinese after initializing with the canonical locale', async () => {
    const mod = await import('./index')
    // Allow the async init promise to settle.
    await new Promise((r) => setTimeout(r, 10))
    mod.default.changeLanguage(ZH_HANS)
    // auth.signIn is "Sign in" in en.json and "登录" in zh-hans.json.
    // If the resource key casing were wrong, this would return the English
    // string (the exact bug that recurred for months).
    expect(mod.default.t('auth.signIn')).toBe(zhHans.auth.signIn)
    expect(mod.default.t('auth.signIn')).not.toBe(en.auth.signIn)
  })
})

describe('syncLocaleFromServer', () => {
  beforeEach(() => {
    localStorage.clear()
    vi.resetModules()
    vi.restoreAllMocks()
  })

  it('adopts the server-configured language when no local choice exists', async () => {
    const fetchSpy = vi
      .spyOn(globalThis, 'fetch')
      .mockResolvedValue(new Response(JSON.stringify({ language: 'zh-Hans' }), { status: 200 }))
    await import('./index')
    // syncLocaleFromServer is fire-and-forget on import; allow it to settle.
    await new Promise((r) => setTimeout(r, 20))
    expect(fetchSpy).toHaveBeenCalledWith('/api/v1/config/language')
    expect(document.documentElement.lang).toBe(ZH_HANS)
    fetchSpy.mockRestore()
  })

  it('normalizes a lowercase server value to the canonical form', async () => {
    vi.spyOn(globalThis, 'fetch').mockResolvedValue(
      new Response(JSON.stringify({ language: 'zh-hans' }), { status: 200 }),
    )
    const mod = await import('./index')
    await new Promise((r) => setTimeout(r, 20))
    expect(mod.default.language).toBe(ZH_HANS)
  })

  it('does not override an explicit local choice', async () => {
    localStorage.setItem('progress.locale', 'en')
    const fetchSpy = vi
      .spyOn(globalThis, 'fetch')
      .mockResolvedValue(new Response(JSON.stringify({ language: 'zh-Hans' }), { status: 200 }))
    await import('./index')
    await new Promise((r) => setTimeout(r, 20))
    // localStorage choice wins; no fetch should even be attempted.
    expect(fetchSpy).not.toHaveBeenCalled()
    expect(localStorage.getItem('progress.locale')).toBe('en')
    fetchSpy.mockRestore()
  })
})
