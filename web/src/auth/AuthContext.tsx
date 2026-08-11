import { useCallback, useEffect, useMemo, useState, type ReactNode } from 'react'
import { fetchClient } from '@/api/client'
import { AuthContext, type AuthUser, TOKEN_STORAGE_KEY, REFRESH_TOKEN_STORAGE_KEY } from './useAuth'

export function AuthProvider({ children }: { children: ReactNode }) {
  const [token, setToken] = useState<string | null>(() =>
    typeof window === 'undefined' ? null : localStorage.getItem(TOKEN_STORAGE_KEY),
  )
  const [refreshToken, setRefreshToken] = useState<string | null>(() =>
    typeof window === 'undefined' ? null : localStorage.getItem(REFRESH_TOKEN_STORAGE_KEY),
  )
  const [user, setUser] = useState<AuthUser | null>(null)
  const [isLoading, setIsLoading] = useState(true)

  const login = useCallback(async (username: string, password: string) => {
    const { data, response, error } = await fetchClient.POST('/api/v1/auth/login', {
      body: { username, password },
    })
    if (!response.ok || !data) {
      const envelope = error as { error?: { message?: string } } | undefined
      throw new Error(envelope?.error?.message ?? 'Login failed')
    }
    localStorage.setItem(TOKEN_STORAGE_KEY, data.access_token)
    localStorage.setItem(REFRESH_TOKEN_STORAGE_KEY, data.refresh_token)
    setToken(data.access_token)
    setRefreshToken(data.refresh_token)
    const meResponse = await fetchClient.GET('/api/v1/auth/me', {
      headers: { Authorization: `Bearer ${data.access_token}` },
    })
    if (!meResponse.response.ok || !meResponse.data) {
      const envelope = meResponse.error as { error?: { message?: string } } | undefined
      throw new Error(envelope?.error?.message ?? 'Failed to fetch user profile')
    }
    setUser(meResponse.data)
  }, [])

  const logout = useCallback(() => {
    localStorage.removeItem(TOKEN_STORAGE_KEY)
    localStorage.removeItem(REFRESH_TOKEN_STORAGE_KEY)
    setToken(null)
    setRefreshToken(null)
    setUser(null)
  }, [])

  useEffect(() => {
    let cancelled = false
    async function loadUser() {
      if (!token) {
        setIsLoading(false)
        return
      }
      const { data, response } = await fetchClient.GET('/api/v1/auth/me', {
        headers: { Authorization: `Bearer ${token}` },
      })
      if (cancelled) return
      if (!response.ok || !data) {
        localStorage.removeItem(TOKEN_STORAGE_KEY)
        localStorage.removeItem(REFRESH_TOKEN_STORAGE_KEY)
        setToken(null)
        setRefreshToken(null)
        setUser(null)
      } else {
        setUser(data)
      }
      setIsLoading(false)
    }
    void loadUser()
    return () => {
      cancelled = true
    }
  }, [token])

  useEffect(() => {
    const handler = () => {
      const newToken = localStorage.getItem(TOKEN_STORAGE_KEY)
      const newRefresh = localStorage.getItem(REFRESH_TOKEN_STORAGE_KEY)
      setToken(newToken)
      setRefreshToken(newRefresh)
    }
    window.addEventListener('token-refreshed', handler)
    return () => window.removeEventListener('token-refreshed', handler)
  }, [])

  const value = useMemo(
    () => ({
      user,
      token,
      refreshToken,
      isAuthenticated: token !== null && user !== null,
      isLoading,
      login,
      logout,
    }),
    [user, token, refreshToken, isLoading, login, logout],
  )

  return <AuthContext.Provider value={value}>{children}</AuthContext.Provider>
}
