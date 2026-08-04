import { afterEach, describe, expect, it, vi, beforeEach } from 'vitest'
import { render, screen, fireEvent } from '@testing-library/react'
import { Toc } from './Toc'

// jsdom has no IntersectionObserver; the component's useScrollSpy hooks one up.
class MockIntersectionObserver {
  observe = vi.fn()
  unobserve = vi.fn()
  disconnect = vi.fn()
  takeRecords = vi.fn(() => [])
}
beforeEach(() => {
  // @ts-expect-error — minimal mock for test env
  globalThis.IntersectionObserver = MockIntersectionObserver
})
afterEach(() => {
  vi.restoreAllMocks()
})

describe('Toc', () => {
  it('renders nothing when there are no items', () => {
    const { container } = render(<Toc items={[]} />)
    expect(container.firstChild).toBeNull()
  })

  it('renders a button per item and a hidden-on-mobile nav', () => {
    const items = [
      { id: 'overview', text: 'Overview', level: 2 },
      { id: 'highlights', text: 'Highlights', level: 3 },
    ]
    render(<Toc items={items} />)
    const nav = document.querySelector('nav') as HTMLElement
    expect(nav).not.toBeNull()
    // the nav is desktop-only (hidden lg:block)
    expect(nav.className).toContain('hidden')
    expect(screen.getByRole('button', { name: 'Overview' })).toBeInTheDocument()
    expect(screen.getByRole('button', { name: 'Highlights' })).toBeInTheDocument()
  })

  it('indents level-3 items relative to level-2', () => {
    render(
      <Toc
        items={[
          { id: 'a', text: 'A', level: 2 },
          { id: 'b', text: 'B', level: 3 },
        ]}
      />,
    )
    const level3 = screen.getByRole('button', { name: 'B' })
    expect(level3.className).toContain('pl-4')
    const level2 = screen.getByRole('button', { name: 'A' })
    expect(level2.className).not.toContain('pl-4')
  })

  it('scrolls the matching heading into view on click', () => {
    const scrollIntoView = vi.fn()
    const target = document.createElement('h2')
    target.id = 'conclusion'
    target.scrollIntoView = scrollIntoView
    document.body.appendChild(target)

    render(<Toc items={[{ id: 'conclusion', text: 'Conclusion', level: 2 }]} />)
    fireEvent.click(screen.getByRole('button', { name: 'Conclusion' }))
    expect(scrollIntoView).toHaveBeenCalledTimes(1)
    expect(scrollIntoView).toHaveBeenCalledWith({ behavior: 'smooth', block: 'start' })

    document.body.removeChild(target)
  })

  it('does not throw when the target id is absent', () => {
    render(<Toc items={[{ id: 'missing', text: 'Missing', level: 2 }]} />)
    expect(() => fireEvent.click(screen.getByRole('button', { name: 'Missing' }))).not.toThrow()
  })
})
