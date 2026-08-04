import { createContext, useContext } from 'react'

type ThemePref = 'system' | 'light' | 'dark'
type ResolvedTheme = 'light' | 'dark'

export interface ThemeContextValue {
  theme: ResolvedTheme
  preference: ThemePref
  cyclePreference: () => void
  setPreference: (pref: ThemePref) => void
}

export const ThemeContext = createContext<ThemeContextValue | null>(null)

export function useTheme(): ThemeContextValue {
  const ctx = useContext(ThemeContext)
  if (!ctx) throw new Error('useTheme must be used within a ThemeProvider')
  return ctx
}
