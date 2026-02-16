import i18n from 'i18next'
import { initReactI18next } from 'react-i18next'

import en from './locales/en.json'
import zhHans from './locales/zh-Hans.json'

const LANGUAGE_KEY = 'progress-language'

const SUPPORTED_LANGUAGES = ['en', 'zh-Hans'] as const
type SupportedLanguage = (typeof SUPPORTED_LANGUAGES)[number]

function isSupportedLanguage(value: string): value is SupportedLanguage {
  return (SUPPORTED_LANGUAGES as readonly string[]).includes(value)
}

function getSavedLanguage(): SupportedLanguage {
  if (typeof window === 'undefined') return 'en'

  const saved = localStorage.getItem(LANGUAGE_KEY)
  if (saved) {
    if (isSupportedLanguage(saved)) return saved
    localStorage.removeItem(LANGUAGE_KEY)
  }

  const browserLang = navigator.language
  if (browserLang.startsWith('zh')) return 'zh-Hans'

  return 'en'
}

i18n.use(initReactI18next).init({
  resources: {
    en: { translation: en },
    'zh-Hans': { translation: zhHans },
  },
  supportedLngs: [...SUPPORTED_LANGUAGES],
  lng: getSavedLanguage(),
  fallbackLng: 'en',
  interpolation: {
    escapeValue: false,
  },
})

i18n.on('languageChanged', (lng) => {
  if (typeof window === 'undefined') return
  if (isSupportedLanguage(lng)) {
    localStorage.setItem(LANGUAGE_KEY, lng)
    return
  }
  localStorage.removeItem(LANGUAGE_KEY)
})

export default i18n
export type { SupportedLanguage }
export { SUPPORTED_LANGUAGES, LANGUAGE_KEY, isSupportedLanguage }
