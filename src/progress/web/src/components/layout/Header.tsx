import { cn } from '@/lib/utils'
import { useTheme } from '@/hooks/useTheme'
import { Settings, Rss, Moon, Sun, SunMoon } from 'lucide-react'
import { Link, useLocation } from 'react-router-dom'
import { useTranslation } from 'react-i18next'
import { LanguageSelector } from './LanguageSelector'

/**
 * Header Component
 * Global navigation with logo, nav items (Config, RSS Feed).
 * Sticky position with glass-navbar backdrop blur for visual depth.
 * Mobile-friendly with hamburger menu on small screens.
 * Includes skip-to-content link for accessibility.
 */
export function Header() {
  const { t } = useTranslation()
  const location = useLocation()
  const { preference, cycleTheme } = useTheme()

  const isConfigActive = location.pathname === '/config'

  return (
    <>
      <a
        href="#main-content"
        className={cn(
          'sr-only focus:not-sr-only',
          'focus:fixed focus:top-4 focus:left-4 focus:z-[9999]',
          'focus:px-4 focus:py-2',
          'focus:bg-primary focus:text-primary-foreground',
          'focus:rounded-md focus:shadow-lg',
          'focus:outline-none focus:ring-2 focus:ring-ring focus:ring-offset-2'
        )}
      >
        Skip to content
      </a>

      <header
        className={cn(
          'glass-navbar sticky top-0 z-sticky',
          'transition-all duration-200 ease-out'
        )}
      >
        <nav className="mx-auto max-w-3xl px-4 sm:px-6 lg:px-8">
          <div className="flex h-14 items-center justify-between">
            <Link
              to="/"
              className={cn(
                'text-xl font-bold',
                'text-primary',
                'transition-colors duration-200 ease-out',
                'hover:text-primary/80',
                'focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring/50'
              )}
            >
              Progress
            </Link>

            <div className="flex items-center gap-1">
              <Link
                to="/config"
                className={cn(
                  'inline-flex items-center gap-2 px-3 py-2',
                  'text-sm font-medium',
                  'rounded-md',
                  'transition-all duration-200 ease-out',
                  isConfigActive
                    ? 'text-foreground bg-glass-bg-primary/60 shadow-sm'
                    : 'text-muted-foreground hover:text-foreground hover:bg-accent/50',
                  'focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring/50'
                )}
                aria-label={t('nav.settings')}
              >
                <Settings className="h-4 w-4" />
                <span className="hidden sm:inline">{t('nav.settings')}</span>
              </Link>

              <a
                href="/api/v1/rss"
                className={cn(
                  'inline-flex items-center gap-2 px-3 py-2',
                  'text-sm font-medium',
                  'rounded-md',
                  'transition-all duration-200 ease-out',
                  'text-muted-foreground hover:text-foreground hover:bg-accent/50',
                  'focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring/50'
                )}
                aria-label={t('nav.rss')}
              >
                <Rss className="h-4 w-4" />
                <span className="hidden sm:inline">{t('nav.rss')}</span>
              </a>

              <LanguageSelector />

              <button
                type="button"
                onClick={cycleTheme}
                className={cn(
                  'inline-flex items-center justify-center',
                  'h-9 w-9 rounded-md',
                  'text-muted-foreground hover:text-foreground hover:bg-accent/50',
                  'transition-all duration-200 ease-out active:scale-95',
                  'focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring/50'
                )}
                aria-label={t(`nav.theme.${preference}`)}
              >
                {preference === 'system' ? (
                  <SunMoon className="h-4 w-4" />
                ) : preference === 'dark' ? (
                  <Moon className="h-4 w-4" />
                ) : (
                  <Sun className="h-4 w-4" />
                )}
              </button>
            </div>
          </div>
        </nav>
      </header>
    </>
  )
}
