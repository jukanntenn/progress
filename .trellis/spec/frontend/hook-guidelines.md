# Hook Guidelines

> How hooks are used in this project.

---

## Overview

This project uses **SWR** for data fetching and custom hooks for reusable stateful logic. Hooks are organized in `src/hooks/` with a clear separation between data fetching hooks and utility hooks.

Key patterns:
- **SWR** for server state (API data)
- **Custom hooks** for reusable logic
- **TypeScript interfaces** for all hook returns

---

## Custom Hook Patterns

### Data Fetching Hook

```tsx
// src/hooks/api.ts
import useSWR from 'swr'

const fetcher = async (url: string) => {
  const res = await fetch(url)
  if (!res.ok) {
    throw new Error('Failed to fetch')
  }
  return res.json()
}

export interface Report {
  id: number
  title: string | null
  created_at: string
  markpost_url: string | null
}

export interface PaginatedReports {
  reports: Report[]
  page: number
  total_pages: number
  total: number
  has_prev: boolean
  has_next: boolean
}

export function useReports(page: number = 1) {
  return useSWR<PaginatedReports>(`/api/v1/reports?page=${page}`, fetcher)
}
```

### Utility Hook

```tsx
// src/hooks/useTheme.ts
import { useEffect, useState } from 'react'

type Theme = 'light' | 'dark' | 'system'

export function useTheme() {
  const [theme, setTheme] = useState<Theme>(() => {
    const stored = localStorage.getItem('theme')
    return (stored as Theme) || 'system'
  })

  useEffect(() => {
    const root = document.documentElement
    root.classList.remove('light', 'dark')

    if (theme === 'system') {
      const systemTheme = window.matchMedia('(prefers-color-scheme: dark)').matches
        ? 'dark'
        : 'light'
      root.classList.add(systemTheme)
    } else {
      root.classList.add(theme)
    }

    localStorage.setItem('theme', theme)
  }, [theme])

  return { theme, setTheme }
}
```

### Event Tracking Hook

```tsx
// src/hooks/useScrollSpy.ts
import { useEffect, useState } from 'react'

export function useScrollSpy(ids: string[]) {
  const [activeId, setActiveId] = useState<string | null>(null)

  useEffect(() => {
    const observer = new IntersectionObserver(
      (entries) => {
        entries.forEach((entry) => {
          if (entry.isIntersecting) {
            setActiveId(entry.target.id)
          }
        })
      },
      { threshold: 0.5 }
    )

    ids.forEach((id) => {
      const element = document.getElementById(id)
      if (element) observer.observe(element)
    })

    return () => observer.disconnect()
  }, [ids])

  return activeId
}
```

---

## Data Fetching

### SWR Pattern

```tsx
// Basic usage
function ReportList() {
  const { data, error, isLoading } = useReports(page)

  if (isLoading) return <Skeleton />
  if (error) return <ErrorState />

  return <ReportItems reports={data.reports} />
}

// Conditional fetching (null key = no fetch)
const { data } = useSWR(id ? `/api/reports/${id}` : null, fetcher)
```

### Mutation

```tsx
import { mutate } from 'swr'

// After creating/updating data
async function saveConfig(toml: string) {
  const res = await fetch('/api/v1/config', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ toml }),
  })
  const result = await res.json()

  // Revalidate cache
  mutate('/api/v1/config')

  return result
}
```

---

## Naming Conventions

| Type | Convention | Example |
|------|-----------|---------|
| Data fetching | `use<Resource>` | `useReports()`, `useConfig()` |
| State toggle | `use<Toggle>` | `useTheme()` |
| Event tracking | `use<Action>Spy` | `useScrollSpy()` |
| Derived state | `useComputed<Value>` | `useComputedTotal()` |

---

## Hook Return Types

Always return an object with named properties:

```tsx
// Good - named returns
function useReports(page: number) {
  return useSWR<PaginatedReports>(`/api/v1/reports?page=${page}`, fetcher)
}
// Usage: const { data, error, isLoading } = useReports()

// Good - custom return object
function useTheme() {
  const [theme, setTheme] = useState<Theme>('system')
  return { theme, setTheme }
}
// Usage: const { theme, setTheme } = useTheme()
```

---

## Common Mistakes

### 1. Not handling loading state

```tsx
// Bad - no loading handling
function ReportList() {
  const { data } = useReports()
  return <div>{data.reports.map(...)}</div>  // Crashes if data is undefined
}

// Good - handle loading
function ReportList() {
  const { data, isLoading } = useReports()
  if (isLoading) return <Skeleton />
  return <div>{data.reports.map(...)}</div>
}
```

### 2. Fetching in useEffect

```tsx
// Bad - manual fetch in useEffect
function ReportList() {
  const [reports, setReports] = useState([])
  useEffect(() => {
    fetch('/api/reports').then(r => r.json()).then(setReports)
  }, [])
}

// Good - use SWR
function ReportList() {
  const { data } = useReports()
}
```

### 3. Not typing the response

```tsx
// Bad - no type
const { data } = useSWR('/api/reports', fetcher)

// Good - typed response
const { data } = useSWR<PaginatedReports>('/api/reports', fetcher)
```

### 4. Not exporting interfaces

```tsx
// Bad - interface not exported
interface Report { ... }
function useReports() { ... }

// Good - export for consumers
export interface Report { ... }
export function useReports() { ... }
```
