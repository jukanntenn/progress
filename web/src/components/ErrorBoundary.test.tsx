import { describe, expect, it, beforeAll, vi } from 'vitest'
import { render, screen, fireEvent } from '@testing-library/react'
import { MemoryRouter } from 'react-router'
import i18n from 'i18next'
import { initReactI18next } from 'react-i18next'
import { ErrorBoundary } from './ErrorBoundary'
import en from '@/i18n/en.json'

// ErrorBoundary renders an i18n-driven fallback (errors.boundaryTitle /
// errors.boundaryDescription / common.refresh / common.backHome). Initialize a
// minimal i18n with the English catalog so the fallback text is deterministic.
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

function Boom({ message }: { message: string }): never {
  throw new Error(message)
}

// The fallback UI contains a react-router <Link to="/reports">, so render the
// boundary inside a MemoryRouter to provide the routing context.
function renderInRouter(ui: React.ReactElement) {
  return render(<MemoryRouter>{ui}</MemoryRouter>)
}

describe('ErrorBoundary', () => {
  it('renders children when no error is thrown', () => {
    const { container } = renderInRouter(
      <ErrorBoundary>
        <p>child content</p>
      </ErrorBoundary>,
    )
    expect(container.textContent).toContain('child content')
  })

  it('renders the fallback UI (not the broken child) when a child throws', () => {
    const spy = vi.spyOn(console, 'error').mockImplementation(() => {})
    renderInRouter(
      <ErrorBoundary>
        <Boom message="kaboom" />
      </ErrorBoundary>,
    )
    expect(screen.getByText(en.errors.boundaryTitle)).toBeInTheDocument()
    expect(screen.getByText(en.errors.boundaryDescription)).toBeInTheDocument()
    expect(screen.getByText('kaboom')).toBeInTheDocument()
    spy.mockRestore()
  })

  it('exposes Refresh and Home actions in the fallback', () => {
    const spy = vi.spyOn(console, 'error').mockImplementation(() => {})
    const reloadSpy = vi.fn()
    Object.defineProperty(window, 'location', {
      value: { reload: reloadSpy, href: '' },
      writable: true,
    })
    renderInRouter(
      <ErrorBoundary>
        <Boom message="fail" />
      </ErrorBoundary>,
    )
    const refresh = screen.getByRole('button', { name: new RegExp(en.common.refresh) })
    fireEvent.click(refresh)
    expect(reloadSpy).toHaveBeenCalledTimes(1)
    expect(screen.getByRole('link', { name: new RegExp(en.common.backHome) })).toHaveAttribute(
      'href',
      '/reports',
    )
    spy.mockRestore()
  })
})
