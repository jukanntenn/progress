# Directory Structure

> How frontend code is organized in this project.

---

## Overview

The frontend is a **React 18 + TypeScript** application built with **Vite 5** and styled with **Tailwind CSS**. It follows a feature-based organization with shared UI components.

Location: `src/progress/web/`

---

## Directory Layout

```
src/progress/web/
├── index.html              # HTML entry point
├── package.json            # Dependencies (pnpm)
├── pnpm-lock.yaml          # Lock file
├── tsconfig.json           # TypeScript config
├── tsconfig.node.json      # Node.js TS config
├── vite.config.ts          # Vite configuration
├── tailwind.config.ts      # Tailwind configuration
├── postcss.config.js       # PostCSS config
├── src/
│   ├── main.tsx            # React entry point
│   ├── App.tsx             # Root component with routes
│   ├── index.css           # Global styles + CSS variables
│   ├── i18n/               # Internationalization
│   │   └── index.ts        # i18n setup
│   ├── lib/                # Utilities
│   │   ├── utils.ts        # General utilities (cn, etc.)
│   │   └── path.ts         # Path helpers
│   ├── hooks/              # Custom hooks
│   │   ├── api.ts          # Data fetching hooks (SWR)
│   │   ├── useTheme.ts     # Theme management
│   │   └── useScrollSpy.ts # Scroll tracking
│   ├── components/
│   │   ├── ui/             # Reusable UI components
│   │   │   ├── button.tsx
│   │   │   ├── card.tsx
│   │   │   ├── input.tsx
│   │   │   ├── select.tsx
│   │   │   ├── dialog.tsx
│   │   │   ├── toast.tsx
│   │   │   ├── tabs.tsx
│   │   │   ├── spinner.tsx
│   │   │   ├── skeleton/
│   │   │   ├── label.tsx
│   │   │   ├── textarea.tsx
│   │   │   └── checkbox.tsx
│   │   ├── layout/         # Layout components
│   │   │   ├── Header.tsx
│   │   │   ├── PageContainer.tsx
│   │   │   ├── LanguageSelector.tsx
│   │   │   └── index.ts    # Re-exports
│   │   └── config/         # Feature components
│   │       ├── ConfigSections.tsx
│   │       └── SectionNav.tsx
│   └── pages/              # Page components
│       ├── ReportList.tsx
│       ├── ReportDetail.tsx
│       └── Config.tsx
└── public/                 # Static assets
```

---

## Module Organization

### Adding a New Page

1. Create component in `src/pages/`
2. Add route in `App.tsx`:

```tsx
import NewPage from './pages/NewPage'

function App() {
  return (
    <Routes>
      <Route path="/new-page" element={<NewPage />} />
    </Routes>
  )
}
```

### Adding a New UI Component

1. Create component in `src/components/ui/`
2. Export from `index.ts` if needed
3. Use Tailwind for styling
4. Follow existing patterns (forwardRef, displayName)

### Adding a New Hook

1. Create hook in `src/hooks/`
2. Use SWR for data fetching
3. Export typed interfaces

---

## Naming Conventions

| Type | Convention | Example |
|------|-----------|---------|
| Component files | PascalCase.tsx | `Button.tsx`, `ReportList.tsx` |
| Hook files | camelCase.ts | `useTheme.ts`, `useScrollSpy.ts` |
| Utility files | camelCase.ts | `utils.ts`, `path.ts` |
| CSS classes | kebab-case (Tailwind) | `bg-primary`, `text-muted-foreground` |
| Component names | PascalCase | `<Button>`, `<PageContainer>` |
| Hook names | use prefix | `useReports()`, `useTheme()` |

---

## Path Aliases

Configured in `vite.config.ts`:

```typescript
resolve: {
  alias: {
    '@': path.resolve(__dirname, './src'),
  },
}
```

Usage:

```tsx
import { Button } from '@/components/ui/button'
import { useReports } from '@/hooks/api'
import { cn } from '@/lib/utils'
```

---

## Examples

Well-organized modules to reference:

- **`components/ui/`** - Reusable UI primitives with variants
- **`components/layout/`** - Layout components with re-exports
- **`hooks/api.ts`** - Typed data fetching hooks with SWR
- **`pages/ReportList.tsx`** - Page component with loading/error states
