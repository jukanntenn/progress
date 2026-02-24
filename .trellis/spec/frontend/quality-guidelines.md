# Quality Guidelines

> Code quality standards for frontend development.

---

## Overview

This project follows React and TypeScript best practices with:
- **TypeScript** strict mode enabled
- **ESLint** for linting
- **Tailwind CSS** for consistent styling
- **pnpm** for package management

---

## Forbidden Patterns

### 1. Inline styles

```tsx
// Bad - inline styles
<div style={{ padding: '16px', backgroundColor: 'red' }}>

// Good - Tailwind classes
<div className="p-4 bg-red-500">
```

### 2. Hardcoded colors

```tsx
// Bad - hardcoded hex
<div className="bg-[#007AFF]">

// Good - semantic tokens
<div className="bg-primary">
```

### 3. Any type

```tsx
// Bad - loses type safety
const data: any = response

// Good - proper typing
const data: Report = response
```

### 4. useEffect for data fetching

```tsx
// Bad - manual fetch
useEffect(() => {
  fetch('/api/data').then(r => r.json()).then(setData)
}, [])

// Good - SWR
const { data } = useData()
```

### 5. Prop drilling

```tsx
// Bad - passing through many levels
<Parent prop={value}>
  <Child prop={value}>
    <Grandchild prop={value}>

// Good - Context for shared state
<Provider>
  <Parent>
    <Child>
      <Grandchild>  {/* uses context directly */}
```

### 6. Index as key

```tsx
// Bad - index as key (unstable)
{items.map((item, index) => <Item key={index} />)}

// Good - stable unique key
{items.map((item) => <Item key={item.id} />)}
```

---

## Required Patterns

### 1. Type all props

```tsx
// Good - typed props
interface ButtonProps {
  variant?: 'default' | 'outline'
  size?: 'sm' | 'default' | 'lg'
  children: React.ReactNode
}
```

### 2. Handle loading/error states

```tsx
// Good - comprehensive state handling
function ReportList() {
  const { data, error, isLoading } = useReports()

  if (isLoading) return <Skeleton />
  if (error) return <ErrorState />
  return <List data={data} />
}
```

### 3. Use semantic HTML

```tsx
// Good - semantic elements
<nav>
  <ul>
    <li><a href="/">Home</a></li>
  </ul>
</nav>

<article>
  <h2>Title</h2>
  <p>Content</p>
</article>
```

### 4. Include focus states

```tsx
// Good - accessible focus styles
<button className="focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring">
  Click
</button>
```

### 5. Use displayName

```tsx
// Good - for debugging
const Button = forwardRef<HTMLButtonElement, ButtonProps>((props, ref) => {
  // ...
})
Button.displayName = 'Button'
```

---

## Testing Requirements

### Run Lint

```bash
cd src/progress/web
pnpm lint
```

### Run Type Check

```bash
cd src/progress/web
pnpm typecheck
```

### Run Build

```bash
cd src/progress/web
pnpm build
```

---

## Code Review Checklist

### Before Submitting

- [ ] TypeScript types on all props
- [ ] No `any` types
- [ ] Loading and error states handled
- [ ] Tailwind classes (no inline styles)
- [ ] Semantic tokens for colors
- [ ] Focus-visible styles on interactive elements
- [ ] Unique keys in lists (not index)
- [ ] `displayName` on forwardRef components

### For Reviewers

- [ ] Follows existing component patterns
- [ ] Responsive design (mobile-friendly)
- [ ] Accessible (keyboard navigation, ARIA)
- [ ] No prop drilling (use Context if needed)
- [ ] Consistent with Liquid Glass design system
