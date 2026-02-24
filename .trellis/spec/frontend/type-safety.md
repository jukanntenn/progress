# Type Safety

> Type safety patterns in this project.

---

## Overview

This project uses **TypeScript** in strict mode with comprehensive type coverage. Types are defined alongside the code that uses them, with shared types exported from relevant modules.

Key principles:
- No `any` types
- Explicit types on all public interfaces
- Inference for internal variables
- Export types alongside functions

---

## Type Organization

### Co-located Types

Define types in the same file as the code that uses them:

```tsx
// src/hooks/api.ts
export interface Report {
  id: number
  title: string | null
  created_at: string
  markpost_url: string | null
}

export function useReports(page: number) {
  return useSWR<PaginatedReports>(`/api/v1/reports?page=${page}`, fetcher)
}
```

### Component Props

Define interface at the top of the component file:

```tsx
// src/components/ui/button.tsx
export interface ButtonProps
  extends React.ButtonHTMLAttributes<HTMLButtonElement> {
  variant?: 'default' | 'secondary' | 'outline' | 'ghost'
  size?: 'sm' | 'default' | 'lg'
  loading?: boolean
  leftIcon?: React.ReactNode
  rightIcon?: React.ReactNode
}
```

### Shared Types

For types used across multiple files, define in a types file or the most relevant module:

```tsx
// src/hooks/api.ts - API response types are used by many components
export interface PaginatedReports {
  reports: Report[]
  page: number
  total_pages: number
  total: number
  has_prev: boolean
  has_next: boolean
}
```

---

## Validation

### Backend Validation

Backend uses Pydantic for validation. Frontend receives validated data.

### Frontend Validation

No runtime validation library (Zod, Yup). TypeScript provides compile-time safety.

For form validation, validate before submit:

```tsx
function validateConfig(toml: string): { valid: boolean; error?: string } {
  if (!toml.trim()) {
    return { valid: false, error: 'Config cannot be empty' }
  }
  return { valid: true }
}
```

---

## Common Patterns

### Extending HTML Elements

```tsx
// Extend button attributes
interface ButtonProps extends React.ButtonHTMLAttributes<HTMLButtonElement> {
  variant?: 'default' | 'outline'
}

// Extend div attributes
interface CardProps extends React.HTMLAttributes<HTMLDivElement> {
  variant?: 'default' | 'glass'
}

// Extend input attributes
interface InputProps extends React.InputHTMLAttributes<HTMLInputElement> {
  label?: string
}
```

### Union Types

```tsx
type Theme = 'light' | 'dark' | 'system'
type Status = 'loading' | 'success' | 'error'
type Variant = 'default' | 'secondary' | 'outline' | 'ghost'
```

### Optional Props

```tsx
interface Props {
  required: string
  optional?: string
  withDefault?: number  // Provide default in destructuring
}

function Component({ required, optional, withDefault = 10 }: Props) {
  // ...
}
```

### Generic Components

```tsx
interface SelectProps<T> {
  value: T
  options: { value: T; label: string }[]
  onChange: (value: T) => void
}

function Select<T>({ value, options, onChange }: SelectProps<T>) {
  // ...
}
```

### Type Guards

```tsx
function isReport(data: unknown): data is Report {
  return (
    typeof data === 'object' &&
    data !== null &&
    'id' in data &&
    'title' in data
  )
}
```

---

## Forbidden Patterns

### 1. Using `any`

```tsx
// Bad - loses type safety
function process(data: any) {
  return data.value
}

// Good - proper type
function process(data: Report) {
  return data.title
}

// If type unknown, use unknown
function process(data: unknown) {
  if (isReport(data)) {
    return data.title
  }
}
```

### 2. Type assertions without validation

```tsx
// Bad - unsafe assertion
const report = data as Report

// Good - type guard
if (isReport(data)) {
  const report = data  // TypeScript knows it's Report
}
```

### 3. Non-null assertion

```tsx
// Bad - assumes value exists
const name = user!.name

// Good - handle null case
const name = user?.name ?? 'Unknown'
```

### 4. Unused type parameters

```tsx
// Bad - T declared but not used
function identity<T>(value: string): string {
  return value
}

// Good - use the type parameter
function identity<T>(value: T): T {
  return value
}
```

---

## Importing Types

```tsx
// Import types with `type` keyword for clarity
import type { Report, PaginatedReports } from '@/hooks/api'

// Or import together
import { useReports, type Report, type PaginatedReports } from '@/hooks/api'
```
