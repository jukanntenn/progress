import { afterEach, describe, expect, it, vi, beforeEach } from 'vitest'
import { render, screen, fireEvent, waitFor } from '@testing-library/react'
import { MemoryRouter, Routes, Route } from 'react-router'
import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { I18nextProvider } from 'react-i18next'
import i18n from '@/i18n'
import { Header } from './Header'

const logoutMock = vi.fn()
const navigateMock = vi.fn()

vi.mock('@/auth/useAuth', () => ({
  useAuth: () => ({
    user: { id: 1, username: 'admin', email: 'a@b.c', is_active: true, is_superuser: true },
    logout: logoutMock,
  }),
}))

vi.mock('@/components/providers/useTheme', () => ({
  useTheme: () => ({
    preference: 'system',
    cyclePreference: vi.fn(),
  }),
}))

vi.mock('react-router', async () => {
  const actual = await vi.importActual<typeof import('react-router')>('react-router')
  return {
    ...actual,
    useNavigate: () => navigateMock,
  }
})

function renderHeader() {
  const queryClient = new QueryClient({ defaultOptions: { queries: { retry: false } } })
  return render(
    <I18nextProvider i18n={i18n}>
      <QueryClientProvider client={queryClient}>
        <MemoryRouter initialEntries={['/reports']}>
          <Routes>
            <Route path="*" element={<Header />} />
          </Routes>
        </MemoryRouter>
      </QueryClientProvider>
    </I18nextProvider>,
  )
}

beforeEach(() => {
  logoutMock.mockReset()
  navigateMock.mockReset()
})

afterEach(() => {
  vi.restoreAllMocks()
})

describe('Header UserMenu', () => {
  it('navigates to settings when Change Password is clicked', async () => {
    renderHeader()
    const trigger = await screen.findByText('admin')
    fireEvent.click(trigger)
    const item = await screen.findByText('Change Password')
    fireEvent.click(item)
    await waitFor(() => {
      expect(navigateMock).toHaveBeenCalledWith('/settings/account')
    })
  })

  it('logs out and navigates to login when Sign out is clicked', async () => {
    renderHeader()
    const trigger = await screen.findByText('admin')
    fireEvent.click(trigger)
    const item = await screen.findByText('Sign out')
    fireEvent.click(item)
    await waitFor(() => {
      expect(logoutMock).toHaveBeenCalledTimes(1)
      expect(navigateMock).toHaveBeenCalledWith('/login', { replace: true })
    })
  })
})
