import { useState } from 'react'
import { NavLink, useNavigate } from 'react-router'
import { useTranslation } from 'react-i18next'
import {
  MenuIcon,
  X,
  Sun,
  Moon,
  Contrast,
  Rss,
  ChevronDown,
  Settings as SettingsIcon,
} from 'lucide-react'
import { Menu } from '@base-ui/react'
import { LanguageSwitcher } from '@/components/LanguageSwitcher'
import { useTheme } from '@/components/providers/useTheme'
import { useAuth } from '@/auth/useAuth'
import { cn } from '@/lib/utils'

const navItems = [{ to: '/reports', key: 'nav.reports' }] as const

function ThemeToggle() {
  const { preference, cyclePreference } = useTheme()
  const { t } = useTranslation()
  const Icon = preference === 'system' ? Contrast : preference === 'dark' ? Moon : Sun
  const label =
    preference === 'system'
      ? t('nav.themeSystem')
      : preference === 'dark'
        ? t('nav.themeDark')
        : t('nav.themeLight')
  return (
    <button
      type="button"
      onClick={cyclePreference}
      className="text-muted-foreground hover:bg-accent hover:text-foreground inline-flex h-9 w-9 items-center justify-center rounded-lg transition-colors"
      aria-label={label}
      title={label}
    >
      <Icon className="h-4 w-4" />
    </button>
  )
}

function UserMenu() {
  const { t } = useTranslation()
  const { user, logout } = useAuth()
  const navigate = useNavigate()
  if (!user) return null
  return (
    <Menu.Root>
      <Menu.Trigger className="text-muted-foreground hover:bg-accent hover:text-foreground glass-chip inline-flex h-9 items-center gap-1.5 rounded-lg px-2 transition-colors">
        <span className="hidden text-xs font-medium sm:inline">{user.username}</span>
        <ChevronDown className="h-4 w-4" />
      </Menu.Trigger>
      <Menu.Portal>
        <Menu.Positioner className="z-50" sideOffset={6}>
          <Menu.Popup className="glass-popover animate-scale-in min-w-44 rounded-xl p-1.5">
            <Menu.Item
              className="focus:bg-accent/50 text-foreground flex cursor-pointer items-center gap-2 rounded-lg px-3 py-2 text-sm transition-colors outline-none"
              onClick={() => navigate('/settings/config/core')}
            >
              <SettingsIcon className="h-4 w-4" />
              {t('nav.settings')}
            </Menu.Item>
            <div className="bg-border/40 my-1 h-px" />
            <Menu.Item
              className="focus:bg-accent/50 text-foreground flex cursor-pointer items-center gap-2 rounded-lg px-3 py-2 text-sm transition-colors outline-none"
              onClick={() => navigate('/settings/account')}
            >
              {t('settings.changePassword')}
            </Menu.Item>
            <Menu.Item
              className="focus:bg-accent/50 text-destructive flex cursor-pointer items-center gap-2 rounded-lg px-3 py-2 text-sm transition-colors outline-none"
              onClick={() => {
                logout()
                navigate('/login', { replace: true })
              }}
            >
              {t('auth.logout')}
            </Menu.Item>
          </Menu.Popup>
        </Menu.Positioner>
      </Menu.Portal>
    </Menu.Root>
  )
}

export function Header() {
  const { t } = useTranslation()
  const [open, setOpen] = useState(false)

  return (
    <header className="glass-navbar sticky top-0 z-40">
      <div className="mx-auto flex h-14 max-w-3xl items-center justify-between px-4">
        <div className="flex items-center gap-6">
          <NavLink to="/reports" className="text-primary text-base font-semibold tracking-tight">
            {t('app.title')}
          </NavLink>
          <nav className="hidden items-center gap-1 md:flex">
            {navItems.map((item) => (
              <NavLink
                key={item.to}
                to={item.to}
                className={({ isActive }) =>
                  cn(
                    'rounded-lg px-3 py-1.5 text-sm font-medium transition-all duration-150 ease-out',
                    isActive
                      ? 'bg-glass-bg-primary/80 text-foreground shadow-sm'
                      : 'text-muted-foreground hover:bg-glass-bg-primary/40 hover:text-foreground',
                  )
                }
              >
                {t(item.key)}
              </NavLink>
            ))}
          </nav>
        </div>

        <div className="flex items-center gap-1">
          <a
            href="/api/v1/rss"
            className="text-muted-foreground hover:bg-accent hover:text-foreground hidden inline-flex h-9 w-9 items-center justify-center rounded-lg transition-colors sm:inline-flex"
            aria-label={t('nav.rss')}
            title={t('nav.rss')}
          >
            <Rss className="h-4 w-4" />
          </a>
          <ThemeToggle />
          <LanguageSwitcher />
          <UserMenu />
          <button
            type="button"
            className="text-muted-foreground hover:bg-accent hover:text-foreground inline-flex h-9 w-9 items-center justify-center rounded-lg transition-colors md:hidden"
            onClick={() => setOpen((v) => !v)}
            aria-label="Toggle navigation"
          >
            {open ? <X className="h-4 w-4" /> : <MenuIcon className="h-4 w-4" />}
          </button>
        </div>
      </div>

      {open && (
        <nav className="border-border/50 border-t md:hidden">
          {navItems.map((item) => (
            <NavLink
              key={item.to}
              to={item.to}
              onClick={() => setOpen(false)}
              className={({ isActive }) =>
                cn(
                  'block px-4 py-2 text-sm font-medium transition-colors',
                  isActive
                    ? 'bg-glass-bg-primary/80 text-foreground'
                    : 'text-muted-foreground hover:bg-glass-bg-primary/40 hover:text-foreground',
                )
              }
            >
              {t(item.key)}
            </NavLink>
          ))}
        </nav>
      )}
    </header>
  )
}
