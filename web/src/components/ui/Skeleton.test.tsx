import { describe, expect, it } from 'vitest'
import { render, screen } from '@testing-library/react'
import { Skeleton, SkeletonList, ReportListItemSkeleton, ReportDetailSkeleton } from './Skeleton'

describe('Skeleton', () => {
  it('renders a div with the animate-pulse class and passthrough className', () => {
    const { container } = render(<Skeleton className="h-8 w-full" data-testid="sk" />)
    const el = container.firstChild as HTMLElement
    expect(el.tagName).toBe('DIV')
    expect(el.className).toContain('animate-pulse')
    expect(el.className).toContain('h-8')
    expect(el.className).toContain('w-full')
  })

  it('forwards extra html attributes', () => {
    render(<Skeleton aria-hidden data-testid="sk" />)
    expect(screen.getByTestId('sk')).toHaveAttribute('aria-hidden')
  })
})

describe('SkeletonList', () => {
  it('renders the requested number of skeleton items and marks itself busy', () => {
    const { container } = render(<SkeletonList items={4} />)
    const list = container.querySelector('ul') as HTMLUListElement
    expect(list).not.toBeNull()
    expect(list).toHaveAttribute('aria-busy', 'true')
    expect(list.querySelectorAll('li')).toHaveLength(4)
    // each li renders two skeleton bars
    expect(list.querySelectorAll('div.animate-pulse')).toHaveLength(8)
  })

  it('defaults to 5 items', () => {
    const { container } = render(<SkeletonList />)
    expect((container.querySelector('ul') as HTMLUListElement).querySelectorAll('li')).toHaveLength(
      5,
    )
  })
})

describe('ReportListItemSkeleton', () => {
  it('renders the list-row layout (title + two meta bars + chevron)', () => {
    const { container } = render(<ReportListItemSkeleton />)
    const bars = container.querySelectorAll('div.animate-pulse')
    // 1 title + 2 meta + 1 chevron = 4 skeleton bars
    expect(bars.length).toBeGreaterThanOrEqual(4)
  })
})

describe('ReportDetailSkeleton', () => {
  it('renders the detail-page layout (title + meta row + content bars)', () => {
    const { container } = render(<ReportDetailSkeleton />)
    const bars = container.querySelectorAll('div.animate-pulse')
    // title bar + 3 meta badges + >=6 content bars
    expect(bars.length).toBeGreaterThanOrEqual(10)
  })
})
