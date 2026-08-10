import i18n from 'i18next'
import { initReactI18next } from 'react-i18next'
import en from './en.json'
import zhHans from './zh-hans.json'

// BCP-47 canonical form. i18next funnels every language code through
// Intl.getCanonicalLocales, which produces "zh-Hans" (capital H) regardless of
// the input casing. The resource key MUST match this canonical form or the
// case-sensitive resource lookup misses and silently falls back to English.
export const ZH_HANS = 'zh-Hans'

// Single source of truth for supported locales. Both the resource map and the
// LanguageSwitcher derive from this list, so a new locale is added in exactly
// one place and the canonical casing can never drift again (the recurring
// "selecting Chinese still shows English" bug).
export interface SupportedLocale {
  value: string
  label: string
}
export const SUPPORTED_LOCALES: readonly SupportedLocale[] = [
  { value: 'en', label: 'English' },
  { value: ZH_HANS, label: '中文' },
] as const

void i18n.use(initReactI18next).init({
  resources: {
    en: { translation: en },
    [ZH_HANS]: { translation: zhHans },
  },
  lng: detectLocale(),
  fallbackLng: 'en',
  interpolation: {
    escapeValue: false,
  },
})

// After init, reconcile with the server-configured language. An explicit
// localStorage choice (set by either the language switcher or the config page)
// always wins; only when there is none do we adopt core.language, so that a
// fresh browser — which used to default to English regardless of config — now
// honours the configured zh-Hans.
void syncLocaleFromServer()

function detectLocale(): string {
  if (typeof navigator === 'undefined') return 'en'
  const stored = localStorage.getItem('progress.locale')
  if (stored) return normalizeLocale(stored)
  const nav = navigator.language?.toLowerCase() ?? ''
  if (nav.startsWith('zh')) return ZH_HANS
  return 'en'
}

// Migrate legacy lowercase "zh-hans" (written by older builds) to the BCP-47
// canonical "zh-Hans" so it matches the resource key after i18next's
// Intl.getCanonicalLocales normalization.
export function normalizeLocale(locale: string): string {
  if (locale.toLowerCase() === 'zh-hans') return ZH_HANS
  return locale
}

async function syncLocaleFromServer(): Promise<void> {
  if (typeof window === 'undefined') return
  // An explicit local choice takes precedence over the server config.
  if (localStorage.getItem('progress.locale')) return
  try {
    const resp = await fetch('/api/v1/config/language')
    if (!resp.ok) return
    const data = (await resp.json()) as { language?: string }
    const configured = data.language ? normalizeLocale(data.language) : undefined
    if (configured && configured !== 'en' && configured !== i18n.language) {
      await i18n.changeLanguage(configured)
      if (typeof document !== 'undefined') {
        document.documentElement.lang = configured
      }
    }
  } catch {
    // Network/availability issue — keep the detected locale; not user-facing.
  }
}

export function changeLocale(locale: string): void {
  const normalized = normalizeLocale(locale)
  void i18n.changeLanguage(normalized)
  localStorage.setItem('progress.locale', normalized)
  if (typeof document !== 'undefined') {
    document.documentElement.lang = normalized
  }
}

export default i18n
