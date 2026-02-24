# Component Guidelines

> How components are built in this project.

---

## Overview

This project uses **React 18** with **TypeScript** and **Tailwind CSS**. Components follow a functional pattern with hooks. The design system is "Liquid Glass" - a glassmorphism style inspired by Apple HIG.

Key characteristics:
- Functional components with hooks
- TypeScript for type safety
- Tailwind CSS for styling
- `class-variance-authority` for component variants
- `forwardRef` for DOM access

---

## Component Structure

### Basic Component

```tsx
import { cn } from '@/lib/utils'

interface MyComponentProps {
  className?: string
  children: React.ReactNode
}

export function MyComponent({ className, children }: MyComponentProps) {
  return (
    <div className={cn('base-classes', className)}>
      {children}
    </div>
  )
}
```

### Component with forwardRef

```tsx
import * as React from 'react'
import { cn } from '@/lib/utils'

export interface ButtonProps
  extends React.ButtonHTMLAttributes<HTMLButtonElement> {
  variant?: 'default' | 'secondary' | 'outline'
  loading?: boolean
}

const Button = React.forwardRef<HTMLButtonElement, ButtonProps>(
  ({ className, variant = 'default', loading, children, ...props }, ref) => {
    return (
      <button
        className={cn(buttonVariants({ variant, className }))}
        ref={ref}
        disabled={loading}
        {...props}
      >
        {loading ? <Spinner /> : children}
      </button>
    )
  }
)
Button.displayName = 'Button'

export { Button }
```

### Component with Variants

```tsx
import { cva, type VariantProps } from 'class-variance-authority'

const cardVariants = cva(
  'rounded-md border transition-all duration-200',
  {
    variants: {
      variant: {
        default: 'bg-card text-card-foreground',
        glass: 'bg-glass-bg-primary/70 backdrop-blur-glass-1',
      },
      size: {
        default: 'p-4',
        lg: 'p-6',
      },
    },
    defaultVariants: {
      variant: 'default',
      size: 'default',
    },
  }
)

// Usage
type CardProps = VariantProps<typeof cardVariants>
```

---

## Props Conventions

### Extend Native Props

```tsx
// Good - extends button props
export interface ButtonProps
  extends React.ButtonHTMLAttributes<HTMLButtonElement> {
  variant?: 'default' | 'outline'
}

// Good - extends div props
export interface CardProps extends React.HTMLAttributes<HTMLDivElement> {
  variant?: 'default' | 'glass'
}
```

### Optional Props with Defaults

```tsx
interface Props {
  variant?: 'default' | 'secondary'  // Optional, has default
  size?: 'sm' | 'default' | 'lg'     // Optional, has default
  disabled?: boolean                  // Optional, defaults to false
  title: string                       // Required
}

// Destructure with defaults
function MyComponent({ variant = 'default', size = 'default', title }: Props) {
  // ...
}
```

### Children Pattern

```tsx
// Standard children
interface Props {
  children: React.ReactNode
}

// With optional children
interface Props {
  children?: React.ReactNode
}

// Multiple slots
interface Props {
  header?: React.ReactNode
  children: React.ReactNode
  footer?: React.ReactNode
}
```

---

## Styling Patterns

### Tailwind Classes

```tsx
// Good - Tailwind classes
<div className="flex items-center gap-2 rounded-lg bg-primary p-4 text-white">
  {children}
</div>

// Good - using cn() for conditional classes
<div className={cn(
  'base-classes',
  isActive && 'active-classes',
  className
)}>
```

### Glassmorphism (Liquid Glass Design)

```tsx
// Glass card
<div className="bg-glass-bg-primary/70 backdrop-blur-glass-1 border border-glass-border/60 shadow-glass">
  {children}
</div>

// Glass input
<input className="bg-glass-bg-tertiary/40 backdrop-blur-glass-1 border border-glass-border/42" />
```

### CSS Variables

Use design tokens from `index.css`:

```tsx
// Using semantic colors
<span className="text-primary">Primary text</span>
<span className="text-muted-foreground">Secondary text</span>
<span className="bg-success text-success-foreground">Success</span>
```

---

## Accessibility

### Focus States

```tsx
// Always include focus-visible styles
<button className="focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring focus-visible:ring-offset-2">
  Click me
</button>
```

### Semantic HTML

```tsx
// Good - semantic elements
<nav>
  <ul>
    <li><a href="/">Home</a></li>
  </ul>
</nav>

// Good - ARIA labels when needed
<button aria-label="Close dialog" onClick={onClose}>
  <XIcon />
</button>
```

### Disabled States

```tsx
// Good - proper disabled styling
<button
  className="disabled:pointer-events-none disabled:opacity-50"
  disabled={isLoading}
>
  Submit
</button>
```

---

## Common Mistakes

### 1. Not using forwardRef for interactive elements

```tsx
// Bad - no ref forwarding
function Button({ children }: Props) {
  return <button>{children}</button>
}

// Good - ref forwarded
const Button = React.forwardRef<HTMLButtonElement, Props>(
  ({ children }, ref) => {
    return <button ref={ref}>{children}</button>
  }
)
```

### 2. Inline styles instead of Tailwind

```tsx
// Bad - inline styles
<div style={{ padding: '16px', backgroundColor: 'red' }}>

// Good - Tailwind classes
<div className="p-4 bg-red-500">
```

### 3. Missing displayName

```tsx
// Bad - no displayName
const Button = React.forwardRef(...)

// Good - with displayName for debugging
const Button = React.forwardRef(...)
Button.displayName = 'Button'
```

### 4. Not spreading rest props

```tsx
// Bad - loses other props
function Button({ children }: Props) {
  return <button>{children}</button>
}

// Good - spreads remaining props
function Button({ children, ...props }: Props) {
  return <button {...props}>{children}</button>
}
```

### 5. Hardcoded colors

```tsx
// Bad - hardcoded color
<div className="bg-[#007AFF]">

// Good - semantic color token
<div className="bg-primary">
```
