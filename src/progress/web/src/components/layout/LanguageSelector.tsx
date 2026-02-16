import { isSupportedLanguage, SUPPORTED_LANGUAGES, type SupportedLanguage } from '@/i18n'
import { cn } from '@/lib/utils'
import { ChevronDown, Globe } from 'lucide-react'
import { useEffect, useRef, useState } from 'react'
import { useTranslation } from 'react-i18next'

const LANGUAGE_LABELS: Record<SupportedLanguage, string> = {
  en: 'English',
  'zh-Hans': '简体中文',
}

export function LanguageSelector() {
  const { i18n, t } = useTranslation()
  const [isOpen, setIsOpen] = useState(false)
  const dropdownRef = useRef<HTMLDivElement>(null)

  const resolvedLanguage = i18n.resolvedLanguage ?? i18n.language
  const currentLanguage: SupportedLanguage = isSupportedLanguage(resolvedLanguage)
    ? resolvedLanguage
    : 'en'
  const currentLabel = LANGUAGE_LABELS[currentLanguage]

  useEffect(() => {
    function handleClickOutside(event: MouseEvent) {
      if (!dropdownRef.current) return
      if (dropdownRef.current.contains(event.target as Node)) return
      setIsOpen(false)
    }

    document.addEventListener('mousedown', handleClickOutside)
    return () => document.removeEventListener('mousedown', handleClickOutside)
  }, [])

  const handleLanguageChange = (lang: SupportedLanguage) => {
    i18n.changeLanguage(lang)
    setIsOpen(false)
  }

  return (
    <div className="relative" ref={dropdownRef}>
      <button
        type="button"
        onClick={() => setIsOpen((v) => !v)}
        className={cn(
          'inline-flex items-center gap-1.5',
          'h-9 px-2 rounded-md',
          'text-sm font-medium',
          'text-muted-foreground hover:text-foreground hover:bg-accent/50',
          'transition-all duration-200 ease-out active:scale-95',
          'focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring/50'
        )}
        aria-label={t('nav.language')}
        aria-expanded={isOpen}
        aria-haspopup="listbox"
      >
        <Globe className="h-4 w-4" />
        <span className="hidden sm:inline">{currentLabel}</span>
        <ChevronDown
          className={cn(
            'hidden sm:block h-3 w-3 transition-transform duration-200',
            isOpen && 'rotate-180'
          )}
        />
      </button>

      {isOpen && (
        <div
          className={cn(
            'absolute right-0 top-full mt-1',
            'min-w-[140px]',
            'glass-card p-1',
            'animate-slide-down',
            'z-50'
          )}
          role="listbox"
          aria-label={t('nav.language')}
        >
          {SUPPORTED_LANGUAGES.map((lang) => (
            <button
              key={lang}
              type="button"
              onClick={() => handleLanguageChange(lang)}
              className={cn(
                'w-full flex items-center',
                'px-3 py-2 rounded-md',
                'text-sm text-left',
                'transition-colors duration-150',
                'hover:bg-accent/50',
                currentLanguage === lang
                  ? 'text-foreground bg-accent/30'
                  : 'text-muted-foreground hover:text-foreground'
              )}
              role="option"
              aria-selected={currentLanguage === lang}
            >
              {LANGUAGE_LABELS[lang]}
            </button>
          ))}
        </div>
      )}
    </div>
  )
}
