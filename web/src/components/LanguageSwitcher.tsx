import { Select } from '@base-ui/react'
import { useTranslation } from 'react-i18next'
import { changeLocale } from '@/i18n'
import { $api } from '@/api/client'
import { cn } from '@/lib/utils'

const locales = [
  { value: 'en', label: 'English' },
  { value: 'zh-hans', label: '中文' },
] as const
const [defaultLocale] = locales

export function LanguageSwitcher({ className }: { className?: string }) {
  const { i18n, t } = useTranslation()
  const current = locales.find((l) => l.value === i18n.language) ?? defaultLocale
  const updateMutation = $api.useMutation('put', '/api/v1/config/language')

  const handleChange = (value: string) => {
    // Update the SPA immediately for snappy feedback, then persist to the
    // server so core.language and the UI stay in sync (previously the switcher
    // only wrote localStorage, leaving the server-configured language stale).
    changeLocale(value)
    updateMutation.mutate({ body: { language: value } })
  }

  return (
    <Select.Root
      value={i18n.language}
      onValueChange={(value) => handleChange(value as string)}
      items={locales}
    >
      <Select.Trigger
        className={cn(
          'border-border bg-background inline-flex h-8 items-center gap-1 rounded-md border px-2 py-1 text-sm',
          className,
        )}
        aria-label={t('nav.language')}
      >
        <Select.Value>{current.label}</Select.Value>
        <Select.Icon>
          <svg width="12" height="12" viewBox="0 0 12 12" fill="none">
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
        <Select.Positioner sideOffset={4}>
          <Select.Popup className="border-border bg-background z-50 min-w-32 overflow-hidden rounded-md border p-1 shadow-md">
            {locales.map((locale) => (
              <Select.Item
                key={locale.value}
                value={locale.value}
                className="data-[highlighted]:bg-accent data-[highlighted]:text-accent-foreground flex cursor-pointer items-center gap-2 rounded px-2 py-1.5 text-sm outline-none"
              >
                <Select.ItemText>{locale.label}</Select.ItemText>
                <Select.ItemIndicator>
                  <svg width="14" height="14" viewBox="0 0 14 14" fill="none">
                    <path
                      d="M3 7L6 10L11 4"
                      stroke="currentColor"
                      strokeWidth="1.75"
                      strokeLinecap="round"
                      strokeLinejoin="round"
                    />
                  </svg>
                </Select.ItemIndicator>
              </Select.Item>
            ))}
          </Select.Popup>
        </Select.Positioner>
      </Select.Portal>
    </Select.Root>
  )
}
