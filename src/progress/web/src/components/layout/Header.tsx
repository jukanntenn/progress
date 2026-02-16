import { cn } from '@/lib/utils'
import { Menu, X, Settings, Rss, Moon, Sun } from 'lucide-react'
import { useEffect, useState } from 'react'
import { Link, useLocation } from 'react-router-dom'

/**
 * Header Component
 * Global navigation with logo, nav items (Config, RSS Feed).
 * Sticky position with glass-navbar backdrop blur for visual depth.
 * Mobile-friendly with hamburger menu on small screens.
 * Includes skip-to-content link for accessibility.
 */
export function Header() {
  const [isMobileMenuOpen, setIsMobileMenuOpen] = useState(false)
  const [isDarkMode, setIsDarkMode] = useState(false)
  const location = useLocation()

  useEffect(() => {
    const isDark = document.documentElement.classList.contains('dark') ||
      document.documentElement.getAttribute('data-theme') === 'dark' ||
      window.matchMedia('(prefers-color-scheme: dark)').matches
    setIsDarkMode(isDark)

    const mediaQuery = window.matchMedia('(prefers-color-scheme: dark)')
    const handleChange = (e: MediaQueryListEvent) => setIsDarkMode(e.matches)
    mediaQuery.addEventListener('change', handleChange)
    return () => mediaQuery.removeEventListener('change', handleChange)
  }, [])

  const toggleDarkMode = () => {
    const newIsDark = !isDarkMode
    setIsDarkMode(newIsDark)
    if (newIsDark) {
      document.documentElement.classList.add('dark')
      document.documentElement.setAttribute('data-theme', 'dark')
    } else {
      document.documentElement.classList.remove('dark')
      document.documentElement.removeAttribute('data-theme')
    }
  }

  const navItems = [
    { href: '/config', label: 'Config', icon: Settings },
    { href: '/api/v1/rss', label: 'RSS Feed', icon: Rss, external: true },
  ]

  const isActive = (href: string) => {
    if (href === '/config') {
      return location.pathname === '/config'
    }
    return false
  }

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
            {navItems.map((item) => {
              const Icon = item.icon
              const active = isActive(item.href)

              if (item.external) {
                return (
                  <a
                    key={item.href}
                    href={item.href}
                    className={cn(
                      'inline-flex items-center gap-2 px-3 py-2',
                      'text-sm font-medium',
                      'rounded-md',
                      'transition-all duration-200 ease-out',
                      'text-muted-foreground hover:text-foreground hover:bg-accent/50',
                      'focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring/50'
                    )}
                  >
                    <Icon className="h-4 w-4" />
                    <span>{item.label}</span>
                  </a>
                )
              }

              return (
                <Link
                  key={item.href}
                  to={item.href}
                  className={cn(
                    'inline-flex items-center gap-2 px-3 py-2',
                    'text-sm font-medium',
                    'rounded-md',
                    'transition-all duration-200 ease-out',
                    active
                      ? 'text-foreground bg-glass-bg-primary/60 shadow-sm'
                      : 'text-muted-foreground hover:text-foreground hover:bg-accent/50',
                    'focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring/50'
                  )}
                >
                  <Icon className="h-4 w-4" />
                  <span>{item.label}</span>
                </Link>
              )
            })}

            <button
              type="button"
              onClick={toggleDarkMode}
              className={cn(
                'inline-flex items-center justify-center',
                'h-9 w-9 rounded-md',
                'text-muted-foreground hover:text-foreground hover:bg-accent/50',
                'transition-all duration-200 ease-out active:scale-95',
                'focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring/50'
              )}
              aria-label={isDarkMode ? 'Switch to light mode' : 'Switch to dark mode'}
            >
              {isDarkMode ? (
                <Sun className="h-4 w-4" />
              ) : (
                <Moon className="h-4 w-4" />
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
              {navItems.map((item) => {
                const Icon = item.icon
                const active = isActive(item.href)

                if (item.external) {
                  return (
                    <a
                      key={item.href}
                      href={item.href}
                      onClick={() => setIsMobileMenuOpen(false)}
                      className={cn(
                        'inline-flex items-center gap-3 px-3 py-3',
                        'text-sm font-medium',
                        'rounded-md',
                        'transition-all duration-200 ease-out',
                        'text-muted-foreground hover:text-foreground hover:bg-accent/50',
                        'focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring/50'
                      )}
                    >
                      <Icon className="h-5 w-5" />
                      <span>{item.label}</span>
                    </a>
                  )
                }

                return (
                  <Link
                    key={item.href}
                    to={item.href}
                    onClick={() => setIsMobileMenuOpen(false)}
                    className={cn(
                      'inline-flex items-center gap-3 px-3 py-3',
                      'text-sm font-medium',
                      'rounded-md',
                      'transition-all duration-200 ease-out',
                      active
                        ? 'text-foreground bg-glass-bg-primary/60 shadow-sm'
                        : 'text-muted-foreground hover:text-foreground hover:bg-accent/50',
                      'focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring/50'
                    )}
                  >
                    <Icon className="h-5 w-5" />
                    <span>{item.label}</span>
                  </Link>
                )
              })}

              <button
                type="button"
                onClick={toggleDarkMode}
                className={cn(
                  'inline-flex items-center gap-3 px-3 py-3',
                  'text-sm font-medium',
                  'rounded-md',
                  'text-muted-foreground hover:text-foreground hover:bg-accent/50',
                  'transition-all duration-200 ease-out',
                  'focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring/50'
                )}
                aria-label={isDarkMode ? 'Switch to light mode' : 'Switch to dark mode'}
              >
                {isDarkMode ? (
                  <Sun className="h-5 w-5" />
                ) : (
                  <Moon className="h-5 w-5" />
                )}
                <span>{isDarkMode ? 'Light Mode' : 'Dark Mode'}</span>
              </button>
            </div>
          </div>
        )}
      </nav>
    </header>
    </>
  )
}
