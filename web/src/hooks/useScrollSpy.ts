import { useEffect, useState } from 'react'

/**
 * Track which section id is currently active in the viewport, for the config
 * editor sidebar nav. Mirrors the pre-refactor IntersectionObserver recipe:
 * a section counts as active when its top sits between 20% and 30% from the
 * top of the viewport, and the topmost intersecting section wins.
 */
export function useScrollSpy(
  sectionIds: string[],
  options: { rootMargin?: string; threshold?: number } = {},
): string | null {
  const [active, setActive] = useState<string | null>(sectionIds[0] ?? null)

  useEffect(() => {
    if (typeof window === 'undefined') return
    const observer = new IntersectionObserver(
      (entries) => {
        const visible = entries
          .filter((e) => e.isIntersecting)
          .sort((a, b) => a.boundingClientRect.top - b.boundingClientRect.top)
        if (visible.length > 0) {
          const first = visible[0] as IntersectionObserverEntry
          setActive(first.target.id)
        }
      },
      {
        rootMargin: options.rootMargin ?? '-20% 0px -70% 0px',
        threshold: options.threshold ?? 0,
      },
    )

    const elements = sectionIds
      .map((id) => document.getElementById(id))
      .filter((el): el is HTMLElement => el !== null)
    elements.forEach((el) => observer.observe(el))
    return () => observer.disconnect()
  }, [sectionIds, options.rootMargin, options.threshold])

  return active
}
