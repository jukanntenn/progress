# Liquid Glass Apple Design System

This design system defines the visual style preferences for the Progress web application. All UI development should follow these guidelines to maintain consistency.

## Design Principles

| Principle | Description |
|-----------|-------------|
| **Glassmorphism** | Core visual identity using translucent layers with blur effects |
| **Apple HIG Compliance** | Follow Apple Human Interface Guidelines for colors, typography, and interactions |
| **Minimalism** | Clean layouts with purposeful whitespace, no unnecessary decoration |
| **Fluid Motion** | Smooth, natural animations with carefully crafted easing curves |
| **Refined Details** | Subtle specular highlights, layered shadows, and precise spacing |

## Color System

### Primary Accent Color

| Mode | Color | Hex | Usage |
|------|-------|-----|-------|
| Light | Apple Blue | #007AFF | Primary actions, links, focus rings |
| Dark | Apple Blue (Dark) | #0a84ff | Primary actions, links, focus rings |

### Semantic Colors (Apple System Colors)

| Semantic | Hex | Usage |
|----------|-----|-------|
| Success | #30d158 | Success states, positive feedback |
| Warning | #ff9f0a | Warnings, attention needed |
| Error | #ff453a | Errors, destructive actions |
| Info | #0a84ff | Informational messages |

### Glass Effect Colors

#### Light Mode
| Layer | Opacity | Usage |
|-------|---------|-------|
| Primary | 72% | Cards, main surfaces |
| Secondary | 55% | Sidebars, secondary panels |
| Tertiary | 40% | Inputs, subtle backgrounds |
| Border | 60% | Glass borders |
| Specular | 75% | Top-left highlight |

#### Dark Mode
| Layer | Opacity | Usage |
|-------|---------|-------|
| Primary | 72% | Cards, main surfaces |
| Secondary | 60% | Sidebars, secondary panels |
| Tertiary | 48% | Inputs, subtle backgrounds |
| Border | 12% | Glass borders |
| Specular | 15% | Top-left highlight |

### Background Gradients

```
Light: linear-gradient(135deg, #e8f4fc, #f0e8f8, #fef6e8)
Dark:  linear-gradient(135deg, #0a0a12, #12121f, #1a1020)
```

## Typography

### Font Stack

| Type | Primary Font | Fallbacks |
|------|-------------|-----------|
| Sans | Inter | -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto |
| Mono | JetBrains Mono | "Fira Code", Consolas, Menlo |

### Font Size Scale

| Token | Size | Usage |
|-------|------|-------|
| xs | 12px | Labels, badges, hints |
| sm | 14px | Small text, table cells |
| base | 16px | Body text (default) |
| lg | 18px | Subheadings |
| xl | 20px | Small headings |
| 2xl | 24px | H2 headings |
| 3xl | 30px | H1 headings |
| 4xl | 36px | Large headings |
| 5xl | 48px | Display headings |

### Line Height Scale

| Token | Value | Usage |
|-------|-------|-------|
| none | 1 | Headings |
| tight | 1.25 | Dense text |
| normal | 1.5 | Body text (default) |
| relaxed | 1.625 | Readable paragraphs |

## Spacing System

Based on 8px grid with 4px minimum unit:

| Token | Size | Usage |
|-------|------|-------|
| 1 | 4px | Tight spacing |
| 2 | 8px | Small gaps |
| 3 | 12px | Medium gaps |
| 4 | 16px | Standard padding |
| 6 | 24px | Section padding |
| 8 | 32px | Large spacing |

## Border Radius

Apple-style soft, organic curves:

| Token | Size | Usage |
|-------|------|-------|
| xs | 6px | Badges, small elements |
| sm | 10px | Buttons, inputs |
| md | 14px | Cards (default) |
| lg | 20px | Large cards |
| xl | 28px | Modals, dialogs |
| 2xl | 36px | Special elements |

## Shadows & Depth

### Standard Shadows

| Token | Usage |
|-------|-------|
| sm | Subtle elevation |
| md | Default elevation |
| lg | Prominent elements |
| xl | Modals, overlays |

### Glass Shadows

| Token | Usage |
|-------|-------|
| glass-card | Standard glass cards |
| glass-elevated | Elevated glass surfaces |
| glass-navbar | Navigation bar |

### Specular Highlight

All glass surfaces include a subtle top-left highlight:
```css
box-shadow: inset 1px 1px 0 rgb(255 255 255 / 0.75);
```

## Animation & Motion

### Duration Scale

| Token | Duration | Usage |
|-------|----------|-------|
| instant | 50ms | Immediate feedback |
| fast | 100ms | Quick transitions |
| normal | 150ms | Standard transitions (default) |
| slow | 200ms | Emphasized motion |

### Easing Functions

| Name | Curve | Usage |
|------|-------|-------|
| immediate | cubic-bezier(0.4, 0, 0.2, 1) | Quick response |
| smooth | cubic-bezier(0.25, 0.8, 0.25, 1) | Smooth transitions |
| bounce | cubic-bezier(0.34, 1.56, 0.64, 1) | Playful, elastic feel |
| out-expo | cubic-bezier(0.16, 1, 0.3, 1) | Apple-style entrance |

### Interaction Feedback

| Element | Effect |
|---------|--------|
| Buttons (active) | scale(0.98) |
| Cards (hover) | translateY(-2px) + shadow enhancement |
| Links (hover) | Underline width 0 → 100% |
| Toasts (enter) | slide + scale combination |

### Animation Types

| Type | Usage |
|------|-------|
| slide-in/out | Dropdowns, popovers |
| fade-in/out | Overlays, modals |
| scale-in/out | Dialogs, zoom effects |
| shimmer | Loading skeletons |
| pulse-gentle | Status indicators |

## Component Patterns

### Glass Card

```css
.glass-card {
  background: rgb(255 255 255 / 0.72);
  backdrop-filter: blur(16px) saturate(180%);
  border: 1px solid rgb(255 255 255 / 0.60);
  box-shadow: var(--shadow-glass-card), inset 1px 1px 0 rgb(255 255 255 / 0.75);
}
```

### Primary Button

```css
.btn-primary {
  background: #007AFF;
  color: white;
  border-radius: 10px;
  transition: all 150ms cubic-bezier(0.4, 0, 0.2, 1);
}
.btn-primary:hover { filter: brightness(1.1); }
.btn-primary:active { transform: scale(0.98); }
```

### Glass Input

```css
.glass-input {
  background: rgb(255 255 255 / 0.40);
  backdrop-filter: blur(16px);
  border: 1px solid rgb(255 255 255 / 0.42);
  border-radius: 10px;
}
.glass-input:focus {
  ring: 2px solid #007AFF;
  ring-offset: 2px;
}
```

## Accessibility

- **Focus Rings**: Always visible 2px ring with offset
- **Reduced Motion**: Respect `prefers-reduced-motion`
- **Color Contrast**: WCAG AA compliant
- **Font Rendering**: antialiased, optimizeLegibility

## Usage Guidelines

### DO

- Use glass effects for elevated surfaces (cards, popovers, modals)
- Apply specular highlights to glass surfaces
- Use Apple system colors for semantic states
- Follow the 8px spacing grid
- Use bounce easing for playful interactions
- Include smooth transitions on interactive elements

### DON'T

- Mix different glass opacity levels inconsistently
- Use harsh shadows without blur
- Apply glass effects on flat backgrounds without gradient
- Use non-Apple system colors for semantic states
- Skip focus states on interactive elements
- Use animations longer than 300ms for standard interactions

## Design Tokens Reference

All design tokens are defined in:
- CSS Variables: `src/progress/web/src/index.css`
- Tailwind Config: `src/progress/web/tailwind.config.ts`

When extending the design system, always define new tokens in both files.
