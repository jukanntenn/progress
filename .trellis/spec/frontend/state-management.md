# State Management

> How state is managed in this project.

---

## Overview

This project uses a **simple, pragmatic state management approach**:

- **SWR** for server state (API data)
- **React useState/useContext** for local/global UI state
- **URL state** for pagination and navigation
- **No global state library** (Redux, Zustand, etc.)

---

## State Categories

| Category | Solution | Examples |
|----------|----------|----------|
| Server state | SWR | Reports, config, timezones |
| Local UI state | useState | Form inputs, modals, tabs |
| Global UI state | Context | Theme, toasts |
| URL state | react-router | Page number, active section |

---

## When to Use Each Type

### Server State → SWR

Data from API endpoints should always use SWR:

```tsx
// Automatic caching, revalidation, deduplication
const { data, error, isLoading } = useReports(page)
const { data: config } = useConfig()
```

### Local UI State → useState

Component-specific state:

```tsx
// Form inputs
const [value, setValue] = useState('')

// Modal visibility
const [isOpen, setIsOpen] = useState(false)

// Tab selection
const [activeTab, setActiveTab] = useState('general')
```

### Global UI State → Context

State shared across components:

```tsx
// Theme context
const { theme, setTheme } = useTheme()

// Toast notifications
const { showToast } = useToast()
```

### URL State → Router

State that should be bookmarkable/shareable:

```tsx
// Pagination
const [searchParams, setSearchParams] = useSearchParams()
const page = parseInt(searchParams.get('page') || '1', 10)

// Update URL
setSearchParams({ page: newPage.toString() })
```

---

## When to Use Global State

Promote state to global (Context) when:

1. **Multiple components** need the same state
2. **Prop drilling** becomes painful (>2 levels)
3. **Theme/appearance** settings
4. **Notifications/toasts** that appear anywhere

Do NOT use global state for:
- Single-component state
- Form inputs that don't affect other components
- Temporary UI states (hover, focus)

---

## Server State

### SWR Configuration

```tsx
// Default configuration (implicit)
useSWR(key, fetcher)

// Custom options
useSWR(key, fetcher, {
  revalidateOnFocus: false,
  refreshInterval: 30000,
})
```

### Cache Invalidation

```tsx
import { mutate } from 'swr'

// Revalidate specific key
mutate('/api/v1/reports')

// Revalidate all keys
mutate(() => true)

// Optimistic update
mutate('/api/v1/reports', newReports, false)
```

### Error Handling

```tsx
const { data, error, isLoading } = useReports()

if (error) {
  return <ErrorState message="Failed to load reports" />
}
```

---

## Common Mistakes

### 1. Duplicating server state in local state

```tsx
// Bad - copying server data to local state
const { data } = useReports()
const [reports, setReports] = useState(data?.reports || [])

// Good - use SWR data directly
const { data } = useReports()
// Render data.reports directly
```

### 2. Not using URL for pagination

```tsx
// Bad - local state for pagination
const [page, setPage] = useState(1)

// Good - URL state (bookmarkable)
const [searchParams, setSearchParams] = useSearchParams()
const page = parseInt(searchParams.get('page') || '1', 10)
```

### 3. Over-engineering with global state library

```tsx
// Bad - Redux for simple theme state
const dispatch = useDispatch()
const theme = useSelector(state => state.theme)

// Good - React Context
const { theme, setTheme } = useTheme()
```

### 4. Not handling SWR states

```tsx
// Bad - assumes data is always available
function ReportList() {
  const { data } = useReports()
  return data.reports.map(...)  // Crashes on undefined
}

// Good - handle all states
function ReportList() {
  const { data, error, isLoading } = useReports()

  if (isLoading) return <Skeleton />
  if (error) return <ErrorState />
  return data.reports.map(...)
}
```

### 5. Prop drilling instead of Context

```tsx
// Bad - prop drilling through multiple levels
<App>
  <Layout theme={theme}>
    <Header theme={theme} setTheme={setTheme}>
      <ThemeToggle theme={theme} setTheme={setTheme} />

// Good - Context for shared state
<App>
  <ThemeProvider>
    <Layout>
      <Header>
        <ThemeToggle />
```
