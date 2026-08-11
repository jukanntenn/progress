import { describe, expect, it, beforeAll, beforeEach, vi } from 'vitest'
import { render, screen, waitFor, fireEvent } from '@testing-library/react'
import { MemoryRouter, Routes, Route } from 'react-router'
import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import i18n from 'i18next'
import { initReactI18next } from 'react-i18next'
import en from '@/i18n/en.json'

// Replace the production openapi-fetch client with a controllable stub. The
// real client needs an absolute baseUrl + a fetch that MSW can intercept,
// which is awkward under jsdom. The stub records calls and returns canned
// responses, which is all the auth components need.
const { mockPost, mockGet } = vi.hoisted(() => ({
  mockPost: vi.fn(),
  mockGet: vi.fn(),
}))
vi.mock('@/api/client', () => ({
  fetchClient: {
    POST: mockPost,
    GET: mockGet,
  },
}))

import { AuthProvider } from './AuthContext'
import { RequireAuth } from './RequireAuth'
import LoginPage from './LoginPage'
import { TOKEN_STORAGE_KEY } from './useAuth'

beforeAll(async () => {
  if (!i18n.isInitialized) {
    await i18n.use(initReactI18next).init({
      resources: { en: { translation: en } },
      lng: 'en',
      fallbackLng: 'en',
      interpolation: { escapeValue: false },
    })
  } else {
    await i18n.changeLanguage('en')
  }
})

beforeEach(() => {
  mockPost.mockReset()
  mockGet.mockReset()
  localStorage.clear()
})

function ProtectedPage() {
  return <div>Protected content</div>
}

function renderWithProviders(initialEntries: string[] = ['/protected']) {
  const queryClient = new QueryClient({
    defaultOptions: { queries: { retry: false } },
  })
  return render(
    <QueryClientProvider client={queryClient}>
      <MemoryRouter initialEntries={initialEntries}>
        <AuthProvider>
          <Routes>
            <Route path="/login" element={<LoginPage />} />
            <Route
              path="/protected"
              element={
                <RequireAuth>
                  <ProtectedPage />
                </RequireAuth>
              }
            />
          </Routes>
        </AuthProvider>
      </MemoryRouter>
    </QueryClientProvider>,
  )
}

function okResponse<T>(data: T) {
  return { data, response: { ok: true } as Response }
}
function errResponse(message: string, status: number) {
  return {
    data: undefined,
    error: { error: { code: 'client_error', message, details: {} } },
    response: {
      ok: false,
      status,
      get bodyUsed() {
        return true
      },
      async json() {
        throw new TypeError('Body has already been used')
      },
    } as unknown as Response,
  }
}

describe('AuthProvider + RequireAuth', () => {
  it('redirects to /login when no token is stored', async () => {
    renderWithProviders()
    await waitFor(() => {
      expect(screen.getByRole('button', { name: /sign in/i })).toBeInTheDocument()
    })
  })

  it('shows protected content after successful login', async () => {
    mockPost.mockResolvedValue(
      okResponse({
        access_token: 'fake-token',
        refresh_token: 'fake-refresh',
        token_type: 'bearer',
      }),
    )
    mockGet.mockResolvedValue(
      okResponse({ id: 1, username: 'admin', email: '', is_active: true, is_superuser: true }),
    )
    renderWithProviders()
    await waitFor(() => screen.getByLabelText(/username/i))
    fireEvent.change(screen.getByLabelText(/username/i), { target: { value: 'admin' } })
    fireEvent.change(screen.getByLabelText('Password'), { target: { value: 'pass1234' } })
    fireEvent.click(screen.getByRole('button', { name: /sign in/i }))
    await waitFor(() => {
      expect(screen.getByText('Protected content')).toBeInTheDocument()
    })
    expect(localStorage.getItem(TOKEN_STORAGE_KEY)).toBe('fake-token')
  })

  it('shows error on wrong credentials and clears the password field', async () => {
    mockPost.mockResolvedValue(errResponse('Incorrect username or password', 401))
    renderWithProviders()
    await waitFor(() => screen.getByLabelText(/username/i))
    fireEvent.change(screen.getByLabelText(/username/i), { target: { value: 'admin' } })
    fireEvent.change(screen.getByLabelText('Password'), { target: { value: 'wrongpass' } })
    fireEvent.click(screen.getByRole('button', { name: /sign in/i }))
    await waitFor(() => {
      expect(screen.getByText(/incorrect username or password/i)).toBeInTheDocument()
    })
    expect((screen.getByLabelText(/username/i) as HTMLInputElement).value).toBe('admin')
  })

  it('shows invalidCredentials for a wrong username (not the generic loginFailed)', async () => {
    mockPost.mockResolvedValue(errResponse('Incorrect username or password', 401))
    renderWithProviders()
    await waitFor(() => screen.getByLabelText(/username/i))
    fireEvent.change(screen.getByLabelText(/username/i), { target: { value: 'nonexistent' } })
    fireEvent.change(screen.getByLabelText('Password'), { target: { value: 'whatever' } })
    fireEvent.click(screen.getByRole('button', { name: /sign in/i }))
    await waitFor(() => {
      expect(screen.getByText(/incorrect username or password/i)).toBeInTheDocument()
    })
    expect(screen.queryByText(/unable to sign in/i)).not.toBeInTheDocument()
  })

  it('toggles password visibility via the eye button', async () => {
    mockPost.mockResolvedValue(errResponse('fail', 401))
    renderWithProviders()
    await waitFor(() => screen.getByLabelText(/username/i))
    const passwordInput = screen.getByLabelText('Password') as HTMLInputElement
    expect(passwordInput.type).toBe('password')
    fireEvent.change(passwordInput, { target: { value: 'secret' } })
    fireEvent.click(screen.getByRole('button', { name: /show password/i }))
    expect(passwordInput.type).toBe('text')
    fireEvent.click(screen.getByRole('button', { name: /hide password/i }))
    expect(passwordInput.type).toBe('password')
  })

  it('clears invalid token on mount and redirects to login', async () => {
    mockGet.mockResolvedValue(errResponse('invalid token', 401))
    localStorage.setItem(TOKEN_STORAGE_KEY, 'expired-token')
    renderWithProviders()
    await waitFor(() => {
      expect(localStorage.getItem(TOKEN_STORAGE_KEY)).toBeNull()
    })
    await waitFor(() => {
      expect(screen.getByRole('button', { name: /sign in/i })).toBeInTheDocument()
    })
  })
})
