import * as React from 'react'
import { cn } from '@/lib/utils'

export interface CheckboxProps
  extends React.InputHTMLAttributes<HTMLInputElement> {}

const Checkbox = React.forwardRef<HTMLInputElement, CheckboxProps>(
  ({ className, ...props }, ref) => (
    <input
      type="checkbox"
      className={cn(
        'rounded border-gray-300 text-blue-600 focus:ring-blue-500',
        className,
      )}
      ref={ref}
      {...props}
    />
  ),
)
Checkbox.displayName = 'Checkbox'

export { Checkbox }

