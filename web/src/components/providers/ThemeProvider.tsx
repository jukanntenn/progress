import { useCallback, useEffect, useMemo, useState, type ReactNode } from 'react'
import { ThemeContext, type ThemeContextValue } from './useTheme'

type ThemePref = 'system' | 'light' | 'dark'
type ResolvedTheme = 'light' | 'dark'

const STORAGE_KEY = 'progress-theme'

function getSystemTheme(): ResolvedTheme {
  if (typeof window === 'undefined') return 'light'
  return window.matchMedia('(prefers-color-scheme: dark)').matches ? 'dark' : 'light'
}

function resolveTheme(pref: ThemePref): ResolvedTheme {
  return pref === 'system' ? getSystemTheme() : pref
}

function applyTheme(theme: ResolvedTheme): void {
  const root = document.documentElement
  root.classList.toggle('dark', theme === 'dark')
  root.style.colorScheme = theme
}

export function ThemeProvider({ children }: { children: ReactNode }) {
  const [preference, setPreferenceState] = useState<ThemePref>(() => {
    if (typeof window === 'undefined') return 'system'
    const stored = window.localStorage.getItem(STORAGE_KEY)
    if (stored === 'light' || stored === 'dark' || stored === 'system') return stored
    return 'system'
  })
  const [theme, setTheme] = useState<ResolvedTheme>(() => resolveTheme(preference))

  useEffect(() => {
    const resolved = resolveTheme(preference)
    setTheme(resolved)
    applyTheme(resolved)
    window.localStorage.setItem(STORAGE_KEY, preference)
  }, [preference])

  useEffect(() => {
    const media = window.matchMedia('(prefers-color-scheme: dark)')
    const handler = () => {
      if (preference === 'system') {
        const resolved = getSystemTheme()
        setTheme(resolved)
        applyTheme(resolved)
      }
    }
    media.addEventListener('change', handler)
    return () => media.removeEventListener('change', handler)
  }, [preference])

  const setPreference = useCallback((next: ThemePref) => setPreferenceState(next), [])
  const cyclePreference = useCallback(
    () =>
      setPreferenceState((prev) =>
        prev === 'system' ? 'light' : prev === 'light' ? 'dark' : 'system',
      ),
    [],
  )

  const value = useMemo<ThemeContextValue>(
    () => ({ theme, preference, cyclePreference, setPreference }),
    [theme, preference, cyclePreference, setPreference],
  )

  return <ThemeContext.Provider value={value}>{children}</ThemeContext.Provider>
}
