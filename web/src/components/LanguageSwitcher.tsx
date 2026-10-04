import { Select } from '@base-ui/react'
import { useTranslation } from 'react-i18next'
import { Globe, Check } from 'lucide-react'
import { changeLocale, normalizeLocale, SUPPORTED_LOCALES } from '@/i18n'
import { $api } from '@/api/client'
import { cn } from '@/lib/utils'

export function LanguageSwitcher({ className }: { className?: string }) {
  const { i18n, t } = useTranslation()
  const normalized = normalizeLocale(i18n.language)
  const current = SUPPORTED_LOCALES.find((l) => l.value === normalized) ?? {
    value: 'en',
    label: 'English',
  }
  const updateMutation = $api.useMutation('put', '/api/v1/config/language')

  const handleChange = (value: string) => {
    changeLocale(value)
    updateMutation.mutate({ body: { language: value } })
  }

  return (
    <Select.Root value={normalized} onValueChange={(value) => handleChange(value as string)}>
      <Select.Trigger
        className={cn(
          'glass-chip inline-flex h-9 items-center justify-center gap-1.5 rounded-lg px-2.5 text-sm font-medium',
          className,
        )}
        aria-label={t('nav.language')}
      >
        <Globe className="h-4 w-4" />
        <span className="hidden sm:inline">{current.label}</span>
        <Select.Icon>
          <svg width="10" height="10" viewBox="0 0 12 12" fill="none" aria-hidden="true">
            <path
              d="M3 4.5L6 7.5L9 4.5"
              stroke="currentColor"
              strokeWidth="1.5"
              strokeLinecap="round"
            />
          </svg>
        </Select.Icon>
      </Select.Trigger>
      <Select.Portal>
        <Select.Positioner sideOffset={6} className="z-50">
          <Select.Popup className="glass-popover animate-scale-in min-w-40 overflow-hidden rounded-xl p-1.5">
            {SUPPORTED_LOCALES.map((locale) => {
              const isActive = locale.value === normalized
              return (
                <Select.Item
                  key={locale.value}
                  value={locale.value}
                  className="focus:bg-accent/50 flex cursor-pointer items-center gap-2.5 rounded-lg px-2.5 py-2 text-sm transition-colors outline-none"
                >
                  <span
                    className={cn(
                      'h-4 w-1 rounded-full transition-colors',
                      isActive ? 'bg-accent' : 'bg-transparent',
                    )}
                  />
                  <Select.ItemText className="flex-1">{locale.label}</Select.ItemText>
                  <Select.ItemIndicator>
                    <Check className="text-accent h-4 w-4" />
                  </Select.ItemIndicator>
                </Select.Item>
              )
            })}
          </Select.Popup>
        </Select.Positioner>
      </Select.Portal>
    </Select.Root>
  )
}
