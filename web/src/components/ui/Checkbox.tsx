import { cn } from '@/lib/utils'

type CheckboxProps = React.InputHTMLAttributes<HTMLInputElement>

export function Checkbox({ className, ...props }: CheckboxProps) {
  return (
    <input
      type="checkbox"
      className={cn(
        'border-border/60 ring-offset-background h-4 w-4 rounded-xs border',
        'glass-input',
        'focus-visible:ring-ring/50 focus-visible:ring-2 focus-visible:outline-none',
        'disabled:cursor-not-allowed disabled:opacity-50',
        'accent-primary transition-all duration-200 ease-out',
        'cursor-pointer',
        className,
      )}
      {...props}
    />
  )
}
