import { useMemo } from 'react'
import { useScrollSpy } from '@/hooks/useScrollSpy'
import { cn } from '@/lib/utils'

export interface TocItem {
  id: string
  text: string
  level: number
}

interface TocProps {
  items: TocItem[]
}

export function Toc({ items }: TocProps) {
  const ids = useMemo(() => items.map((i) => i.id), [items])
  const activeId = useScrollSpy(ids)

  if (items.length === 0) return null

  const handleClick = (id: string) => {
    document.getElementById(id)?.scrollIntoView({ behavior: 'smooth', block: 'start' })
  }

  return (
    <nav className="hidden lg:block">
      <ul className="space-y-1">
        {items.map((item) => (
          <li key={item.id}>
            <button
              type="button"
              onClick={() => handleClick(item.id)}
              className={cn(
                'block w-full py-1 pr-2 text-left text-sm transition-colors',
                item.level === 3 && 'pl-4',
                activeId === item.id
                  ? 'text-primary font-medium'
                  : 'text-muted-foreground hover:text-foreground',
              )}
            >
              {item.text}
            </button>
          </li>
        ))}
      </ul>
    </nav>
  )
}
