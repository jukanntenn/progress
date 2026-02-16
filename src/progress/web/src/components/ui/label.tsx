import * as React from 'react'
import { cn } from '@/lib/utils'

/**
 * Label Component
 * Form label with Apple-style text hierarchy.
 * Uses text-primary for main label color.
 */
const Label = React.forwardRef<
  HTMLLabelElement,
  React.LabelHTMLAttributes<HTMLLabelElement>
>(({ className, ...props }, ref) => (
  <label
    ref={ref}
    className={cn(
      'text-sm font-medium leading-none text-foreground',
      'peer-disabled:cursor-not-allowed peer-disabled:opacity-70',
      'transition-colors duration-150',
      className,
    )}
    {...props}
  />
))
Label.displayName = 'Label'

export { Label }
