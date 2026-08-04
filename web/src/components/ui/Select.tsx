import { ChevronDown } from 'lucide-react'
import { cn } from '@/lib/utils'

type SelectProps = React.SelectHTMLAttributes<HTMLSelectElement>

export function Select({ className, children, ...props }: SelectProps) {
  return (
    <div className="relative">
      <select
        className={cn(
          'glass-input flex h-10 w-full appearance-none rounded-md px-3 py-2 pr-9 text-sm',
          'ring-offset-background',
          'transition-all duration-200 ease-out',
          'hover:border-ring/40',
          'focus-visible:ring-ring/50 focus-visible:ring-2 focus-visible:outline-none',
          'disabled:cursor-not-allowed disabled:opacity-50',
          'cursor-pointer',
          className,
        )}
        {...props}
      >
        {children}
      </select>
      <ChevronDown className="text-muted-foreground pointer-events-none absolute top-1/2 right-3 h-4 w-4 -translate-y-1/2" />
    </div>
  )
}
