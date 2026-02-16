import { useEffect, useState } from 'react'

type ThemePreference = 'light' | 'dark' | 'system'
type ResolvedTheme = 'light' | 'dark'

const STORAGE_KEY = 'theme-preference'

const CYCLE_ORDER: ThemePreference[] = ['system', 'light', 'dark']

function getSystemTheme(): ResolvedTheme {
  if (typeof window === 'undefined') return 'light'
  return window.matchMedia('(prefers-color-scheme: dark)').matches ? 'dark' : 'light'
}

function getStoredPreference(): ThemePreference {
  if (typeof window === 'undefined') return 'system'
  const stored = localStorage.getItem(STORAGE_KEY)
  if (stored === 'light' || stored === 'dark' || stored === 'system') {
    return stored
  }
  return 'system'
}

function resolveTheme(preference: ThemePreference): ResolvedTheme {
  if (preference === 'system') {
    return getSystemTheme()
  }
  return preference
}

function applyTheme(theme: ResolvedTheme): void {
  const root = document.documentElement
  if (theme === 'dark') {
    root.classList.add('dark')
    root.setAttribute('data-theme', 'dark')
  } else {
    root.classList.remove('dark')
    root.removeAttribute('data-theme')
  }
}

export interface UseThemeReturn {
  preference: ThemePreference
  resolvedTheme: ResolvedTheme
  cycleTheme: () => void
}

export function useTheme(): UseThemeReturn {
  const [preference, setPreference] = useState<ThemePreference>('system')
  const [resolvedTheme, setResolvedTheme] = useState<ResolvedTheme>('light')

  useEffect(() => {
    const stored = getStoredPreference()
    setPreference(stored)
    const resolved = resolveTheme(stored)
    setResolvedTheme(resolved)
    applyTheme(resolved)
  }, [])

  useEffect(() => {
    if (preference !== 'system') return

    const mediaQuery = window.matchMedia('(prefers-color-scheme: dark)')
    const handleChange = () => {
      const resolved = getSystemTheme()
      setResolvedTheme(resolved)
      applyTheme(resolved)
    }

    mediaQuery.addEventListener('change', handleChange)
    return () => mediaQuery.removeEventListener('change', handleChange)
  }, [preference])

  const cycleTheme = () => {
    const currentIndex = CYCLE_ORDER.indexOf(preference)
    const nextIndex = (currentIndex + 1) % CYCLE_ORDER.length
    const nextPreference = CYCLE_ORDER[nextIndex]

    setPreference(nextPreference)
    localStorage.setItem(STORAGE_KEY, nextPreference)

    const resolved = resolveTheme(nextPreference)
    setResolvedTheme(resolved)
    applyTheme(resolved)
  }

  return { preference, resolvedTheme, cycleTheme }
}
