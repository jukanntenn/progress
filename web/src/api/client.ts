import createFetchClient from 'openapi-fetch'
import createQueryClient from 'openapi-react-query'
import type { paths } from './schema'
import { TOKEN_STORAGE_KEY, REFRESH_TOKEN_STORAGE_KEY } from '@/auth/useAuth'

export const fetchClient = createFetchClient<paths>({
  baseUrl: import.meta.env.VITE_API_BASE_URL ?? '/',
})

fetchClient.use({
  async onRequest({ request }) {
    const locale = localStorage.getItem('progress.locale') ?? 'en'
    request.headers.set('Accept-Language', locale)
    const token = localStorage.getItem(TOKEN_STORAGE_KEY)
    if (token && !request.headers.has('Authorization')) {
      request.headers.set('Authorization', `Bearer ${token}`)
    }
    return request
  },
  async onResponse({ request, response }) {
    if (
      response.status !== 401 ||
      request.url.includes('/auth/refresh') ||
      request.url.includes('/auth/login')
    ) {
      return response
    }
    const refreshToken = localStorage.getItem(REFRESH_TOKEN_STORAGE_KEY)
    if (!refreshToken) {
      localStorage.removeItem(TOKEN_STORAGE_KEY)
      localStorage.removeItem(REFRESH_TOKEN_STORAGE_KEY)
      window.location.href = '/login'
      return response
    }
    if (!_refreshPromise) {
      _refreshPromise = (async () => {
        try {
          const refreshResponse = await fetch('/api/v1/auth/refresh', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ refresh_token: refreshToken }),
          })
          if (!refreshResponse.ok) {
            _doLogout()
            return
          }
          const data = await refreshResponse.json()
          localStorage.setItem(TOKEN_STORAGE_KEY, data.access_token)
          localStorage.setItem(REFRESH_TOKEN_STORAGE_KEY, data.refresh_token)
          window.dispatchEvent(new Event('token-refreshed'))
        } catch {
          _doLogout()
        } finally {
          _refreshPromise = null
        }
      })()
    }
    await _refreshPromise
    const newToken = localStorage.getItem(TOKEN_STORAGE_KEY)
    if (!newToken) {
      return response
    }
    const retryRequest = new Request(request, {
      headers: Object.fromEntries(request.headers.entries()),
    })
    retryRequest.headers.set('Authorization', `Bearer ${newToken}`)
    return fetch(retryRequest.clone())
  },
})

function _doLogout(): void {
  localStorage.removeItem(TOKEN_STORAGE_KEY)
  localStorage.removeItem(REFRESH_TOKEN_STORAGE_KEY)
  window.location.href = '/login'
}

let _refreshPromise: Promise<void> | null = null

export const $api = createQueryClient(fetchClient)
