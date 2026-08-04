import { createContext, useContext } from 'react'

export interface AuthUser {
  id: number
  username: string
  email: string
  is_active: boolean
  is_superuser: boolean
}

export interface AuthContextValue {
  user: AuthUser | null
  token: string | null
  refreshToken: string | null
  isAuthenticated: boolean
  isLoading: boolean
  login: (username: string, password: string) => Promise<void>
  logout: () => void
}

export const AuthContext = createContext<AuthContextValue | null>(null)
export const TOKEN_STORAGE_KEY = 'progress.token'
export const REFRESH_TOKEN_STORAGE_KEY = 'progress.refreshToken'

export function useAuth(): AuthContextValue {
  const ctx = useContext(AuthContext)
  if (!ctx) throw new Error('useAuth must be used within an AuthProvider')
  return ctx
}
