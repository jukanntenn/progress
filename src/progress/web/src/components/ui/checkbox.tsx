import * as React from 'react'
import { cn } from '@/lib/utils'

export interface CheckboxProps
  extends React.InputHTMLAttributes<HTMLInputElement> {}

/**
 * Checkbox Component
 * Liquid Glass style with Apple Blue accent color.
 * Uses --radius-xs (6px) for small element rounded corners.
 */
const Checkbox = React.forwardRef<HTMLInputElement, CheckboxProps>(
  ({ className, ...props }, ref) => (
    <input
      type="checkbox"
      className={cn(
        'h-4 w-4 rounded-xs border border-border/60 ring-offset-background',
        'glass-input',
        'focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring/50',
        'disabled:cursor-not-allowed disabled:opacity-50',
        'accent-primary transition-all duration-200 ease-out',
        'cursor-pointer',
        className,
      )}
      ref={ref}
      {...props}
    />
  ),
)
Checkbox.displayName = 'Checkbox'

export { Checkbox }
