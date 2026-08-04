import { describe, expect, it, vi, beforeEach } from 'vitest'

const mockUse = vi.fn()
const mockCreateFetchClient = vi.fn(() => ({
  use: mockUse,
  POST: vi.fn(),
  GET: vi.fn(),
}))
const mockCreateQueryClient = vi.fn()

vi.mock('openapi-fetch', () => ({
  default: mockCreateFetchClient,
  createQueryClient: mockCreateQueryClient,
}))

vi.mock('./schema', () => ({}))

function okResponse<T>(data: T) {
  return { data, response: { ok: true } as Response }
}

function errResponse(message: string, status: number) {
  return {
    data: undefined,
    response: {
      ok: false,
      status,
      async json() {
        return { error: { message } }
      },
    } as unknown as Response,
  }
}

type OnResponseHandler = (opts: {
  request: Request
  schemaPath: string
  params: Record<string, never>
  id: string
  options: Record<string, never>
  response: Response
}) => Promise<Response | undefined>

describe('api/client 401 interceptor', () => {
  beforeEach(() => {
    mockUse.mockClear()
    mockCreateFetchClient.mockClear()
    mockCreateQueryClient.mockClear()
    localStorage.clear()
    vi.resetModules()
    global.fetch = undefined as unknown as typeof fetch
  })

  it('middleware registered at module load', async () => {
    await import('./client')
    expect(mockCreateFetchClient).toHaveBeenCalledTimes(1)
    expect(mockUse).toHaveBeenCalledTimes(1)
    const mw = mockUse.mock.calls[0]?.[0]
    expect(mw).toHaveProperty('onRequest')
    expect(mw).toHaveProperty('onResponse')
  })

  it('401 → refresh → retry with new token', async () => {
    const fetchMock = vi
      .fn()
      .mockResolvedValueOnce(
        new Response(JSON.stringify({ access_token: 'new-token', refresh_token: 'new-refresh' }), {
          status: 200,
          headers: { 'Content-Type': 'application/json' },
        }),
      )
      .mockResolvedValueOnce(
        new Response(JSON.stringify({ data: 'ok' }), {
          status: 200,
          headers: { 'Content-Type': 'application/json' },
        }),
      )
    global.fetch = fetchMock

    localStorage.setItem('progress.token', 'old-token')
    localStorage.setItem('progress.refreshToken', 'old-refresh')

    await import('./client')
    const firstMw = mockUse.mock.calls[0]?.[0] as { onResponse?: OnResponseHandler } | undefined
    const onResponse = firstMw?.onResponse
    expect(onResponse).toBeDefined()

    let response = errResponse('Unauthorized', 401)
    if (onResponse) {
      const result = await onResponse({
        request: new Request('http://localhost/api/v1/test', {
          method: 'POST',
          headers: { Authorization: 'Bearer old-token' },
        }),
        schemaPath: '/api/v1/test',
        params: {},
        id: '1',
        options: {},
        response: response.response,
      })
      if (result instanceof Response) {
        response = { ...response, response: result }
      }
    }

    expect(fetchMock).toHaveBeenCalledTimes(2)
    expect(fetchMock.mock.calls[0]?.[0]).toBe('/api/v1/auth/refresh')
    expect(localStorage.getItem('progress.token')).toBe('new-token')
    expect(localStorage.getItem('progress.refreshToken')).toBe('new-refresh')
  })

  it('401 with no refresh token → localStorage cleared', async () => {
    global.fetch = vi.fn()
    localStorage.setItem('progress.token', 'old-token')

    await import('./client')
    const firstMw = mockUse.mock.calls[0]?.[0] as { onResponse?: OnResponseHandler } | undefined
    const onResponse = firstMw?.onResponse
    expect(onResponse).toBeDefined()

    let response = errResponse('Unauthorized', 401)
    if (onResponse) {
      const result = await onResponse({
        request: new Request('http://localhost/api/v1/test', {
          method: 'POST',
          headers: { Authorization: 'Bearer old-token' },
        }),
        schemaPath: '/api/v1/test',
        params: {},
        id: '1',
        options: {},
        response: response.response,
      })
      if (result instanceof Response) {
        response = { ...response, response: result }
      }
    }

    expect(localStorage.getItem('progress.token')).toBeNull()
    expect(localStorage.getItem('progress.refreshToken')).toBeNull()
  })

  it('non-401 response does not trigger refresh', async () => {
    global.fetch = vi.fn()
    localStorage.setItem('progress.token', 'valid-token')
    localStorage.setItem('progress.refreshToken', 'valid-refresh')

    await import('./client')
    const firstMw = mockUse.mock.calls[0]?.[0] as { onResponse?: OnResponseHandler } | undefined
    const onResponse = firstMw?.onResponse

    let response = okResponse({ data: 'ok' })
    if (onResponse) {
      const result = await onResponse({
        request: new Request('http://localhost/api/v1/test', { method: 'POST' }),
        schemaPath: '/api/v1/test',
        params: {},
        id: '1',
        options: {},
        response: response.response,
      })
      if (result instanceof Response) {
        response = { ...response, response: result }
      }
    }

    expect(global.fetch).not.toHaveBeenCalled()
  })

  it('401 on /auth/login is bypassed so the login form can show inline errors', async () => {
    global.fetch = vi.fn()
    const originalHref = window.location.href
    // @ts-expect-error — jsdom allows overriding location.href via delete+define
    delete window.location
    // @ts-expect-error — minimal location stub
    window.location = { href: originalHref }

    await import('./client')
    const firstMw = mockUse.mock.calls[0]?.[0] as { onResponse?: OnResponseHandler } | undefined
    const onResponse = firstMw?.onResponse
    expect(onResponse).toBeDefined()

    const loginResponse = errResponse('Incorrect username or password', 401)
    const result = await onResponse?.({
      request: new Request('http://localhost/api/v1/auth/login', { method: 'POST' }),
      schemaPath: '/api/v1/auth/login',
      params: {},
      id: '1',
      options: {},
      response: loginResponse.response,
    })

    // The interceptor must return the response unchanged (no refresh, no redirect)
    expect(result).toBe(loginResponse.response)
    expect(global.fetch).not.toHaveBeenCalled()
    expect(window.location.href).toBe(originalHref)
  })
})
