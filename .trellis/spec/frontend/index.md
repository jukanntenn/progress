# Frontend Development Guidelines

> Best practices for frontend development in this project.

---

## Overview

This project is a **React 18 + TypeScript** frontend built with:
- **Vite 5** for development and build
- **Tailwind CSS** for styling
- **SWR** for data fetching
- **pnpm** for package management

Design system: **Liquid Glass** - a glassmorphism style inspired by Apple HIG.

---

## Quick Reference

| Topic | Key Points |
|-------|-----------|
| Package manager | `pnpm install`, `pnpm dev` |
| Styling | Tailwind CSS with semantic tokens |
| Data fetching | SWR with typed interfaces |
| State | useState (local), Context (global), SWR (server) |
| Components | Functional with forwardRef, displayName |
| Types | Strict TypeScript, no `any` |

---

## Guidelines Index

| Guide | Description | Status |
|-------|-------------|--------|
| [Directory Structure](./directory-structure.md) | Module organization and file layout | Filled |
| [Component Guidelines](./component-guidelines.md) | Component patterns, props, composition | Filled |
| [Hook Guidelines](./hook-guidelines.md) | Custom hooks, data fetching patterns | Filled |
| [State Management](./state-management.md) | Local, global, server, URL state | Filled |
| [Quality Guidelines](./quality-guidelines.md) | Code standards, forbidden patterns | Filled |
| [Type Safety](./type-safety.md) | Type patterns, validation | Filled |

---

## Key Patterns

### Component Creation

```tsx
import * as React from 'react'
import { cn } from '@/lib/utils'

export interface ButtonProps
  extends React.ButtonHTMLAttributes<HTMLButtonElement> {
  variant?: 'default' | 'outline'
}

const Button = React.forwardRef<HTMLButtonElement, ButtonProps>(
  ({ className, variant = 'default', ...props }, ref) => {
    return (
      <button
        ref={ref}
        className={cn(buttonVariants({ variant, className }))}
        {...props}
      />
    )
  }
)
Button.displayName = 'Button'
export { Button }
```

### Data Fetching

```tsx
import useSWR from 'swr'

export function useReports(page: number = 1) {
  return useSWR<PaginatedReports>(`/api/v1/reports?page=${page}`, fetcher)
}

// Usage
function ReportList() {
  const { data, error, isLoading } = useReports(page)
  if (isLoading) return <Skeleton />
  if (error) return <ErrorState />
  return <List data={data.reports} />
}
```

### Styling

```tsx
// Use semantic tokens
<div className="bg-primary text-primary-foreground">

// Glassmorphism
<div className="bg-glass-bg-primary/70 backdrop-blur-glass-1 border border-glass-border/60">

// Conditional classes
<div className={cn('base-classes', isActive && 'active-classes', className)}>
```

---

## Common Commands

```bash
# Install dependencies
cd src/progress/web && pnpm install

# Start dev server
pnpm dev

# Build for production
pnpm build

# Run lint
pnpm lint

# Type check
pnpm typecheck
```

---

**Language**: All documentation should be written in **English**.
