import * as React from 'react'
import { cn } from '@/lib/utils'

export interface SelectProps extends React.SelectHTMLAttributes<HTMLSelectElement> {}

/**
 * Select Component
 * Liquid Glass style dropdown with translucent background.
 * Uses --radius-md (14px) for Apple-style rounded corners.
 */
const Select = React.forwardRef<HTMLSelectElement, SelectProps>(
  ({ className, children, ...props }, ref) => (
    <select
      className={cn(
        'glass-input flex h-10 w-full rounded-md px-3 py-2 text-sm',
        'ring-offset-background',
        'transition-all duration-200 ease-out',
        'hover:border-ring/40',
        'focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring/50',
        'disabled:cursor-not-allowed disabled:opacity-50',
        'cursor-pointer appearance-none bg-no-repeat bg-right',
        className,
      )}
      ref={ref}
      {...props}
    >
      {children}
    </select>
  ),
)
Select.displayName = 'Select'

export { Select }
