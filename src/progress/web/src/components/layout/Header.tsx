import { cn } from '@/lib/utils'
import { useTheme } from '@/hooks/useTheme'
import { Menu, X, Settings, Rss, Moon, Sun, SunMoon } from 'lucide-react'
import { useState } from 'react'
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
  const [isMobileMenuOpen, setIsMobileMenuOpen] = useState(false)
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
      <nav className="mx-auto max-w-6xl px-4 sm:px-6 lg:px-8">
        <div className="flex h-16 items-center justify-between">
          <Link
            to="/"
            className={cn(
              'flex items-center gap-2',
              'text-xl font-bold',
              'text-foreground',
              'transition-colors duration-200 ease-out',
              'hover:text-primary',
              'focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring/50'
            )}
          >
            <span
              className={cn(
                'h-6 w-1 rounded-full',
                'bg-primary'
              )}
            />
            <span>Progress</span>
          </Link>

          <div className="hidden md:flex md:items-center md:gap-1">
            <Link
              to="/config"
              className={cn(
                'inline-flex items-center justify-center',
                'h-9 w-9 rounded-md',
                'transition-all duration-200 ease-out active:scale-95',
                isConfigActive
                  ? 'text-foreground bg-glass-bg-primary/60 shadow-sm'
                  : 'text-muted-foreground hover:text-foreground hover:bg-accent/50',
                'focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring/50'
              )}
              title={t('nav.settings')}
              aria-label={t('nav.settings')}
            >
              <Settings className="h-4 w-4" />
            </Link>

            <a
              href="/api/v1/rss"
              className={cn(
                'inline-flex items-center justify-center',
                'h-9 w-9 rounded-md',
                'text-muted-foreground hover:text-foreground hover:bg-accent/50',
                'transition-all duration-200 ease-out active:scale-95',
                'focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring/50'
              )}
              title={t('nav.rss')}
              aria-label={t('nav.rss')}
            >
              <Rss className="h-4 w-4" />
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
              title={t(`nav.theme.${preference}`)}
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

          <button
            type="button"
            onClick={() => setIsMobileMenuOpen(!isMobileMenuOpen)}
            className={cn(
              'md:hidden',
              'inline-flex items-center justify-center',
              'h-10 w-10 rounded-md',
              'text-muted-foreground hover:text-foreground hover:bg-accent/50',
              'transition-all duration-200 ease-out active:scale-95',
              'focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring/50'
            )}
            aria-label={isMobileMenuOpen ? 'Close menu' : 'Open menu'}
            aria-expanded={isMobileMenuOpen}
          >
            {isMobileMenuOpen ? (
              <X className="h-5 w-5" />
            ) : (
              <Menu className="h-5 w-5" />
            )}
          </button>
        </div>

        {isMobileMenuOpen && (
          <div
            className={cn(
              'md:hidden',
              'border-t border-border/30',
              'py-3',
              'animate-slide-down'
            )}
          >
            <div className="flex flex-col gap-1">
              <Link
                to="/config"
                onClick={() => setIsMobileMenuOpen(false)}
                className={cn(
                  'inline-flex items-center justify-center',
                  'h-11 w-11 rounded-md mx-3',
                  'transition-all duration-200 ease-out',
                  isConfigActive
                    ? 'text-foreground bg-glass-bg-primary/60 shadow-sm'
                    : 'text-muted-foreground hover:text-foreground hover:bg-accent/50',
                  'focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring/50'
                )}
                title={t('nav.settings')}
                aria-label={t('nav.settings')}
              >
                <Settings className="h-5 w-5" />
              </Link>

              <a
                href="/api/v1/rss"
                onClick={() => setIsMobileMenuOpen(false)}
                className={cn(
                  'inline-flex items-center justify-center',
                  'h-11 w-11 rounded-md mx-3',
                  'text-muted-foreground hover:text-foreground hover:bg-accent/50',
                  'transition-all duration-200 ease-out',
                  'focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring/50'
                )}
                title={t('nav.rss')}
                aria-label={t('nav.rss')}
              >
                <Rss className="h-5 w-5" />
              </a>

              <div className="px-3 py-1">
                <LanguageSelector />
              </div>

              <button
                type="button"
                onClick={cycleTheme}
                className={cn(
                  'inline-flex items-center gap-3 px-3 py-3',
                  'text-sm font-medium',
                  'rounded-md',
                  'text-muted-foreground hover:text-foreground hover:bg-accent/50',
                  'transition-all duration-200 ease-out',
                  'focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring/50'
                )}
                title={t(`nav.theme.${preference}`)}
                aria-label={t(`nav.theme.${preference}`)}
              >
                {preference === 'system' ? (
                  <SunMoon className="h-5 w-5" />
                ) : preference === 'dark' ? (
                  <Moon className="h-5 w-5" />
                ) : (
                  <Sun className="h-5 w-5" />
                )}
                <span>{t(`nav.theme.${preference}`)}</span>
              </button>
            </div>
          </div>
        )}
      </nav>
    </header>
    </>
  )
}
