import { cn } from '@/lib/utils'

export function Label({ className, ...props }: React.LabelHTMLAttributes<HTMLLabelElement>) {
  return (
    <label
      className={cn(
        'text-foreground text-sm leading-none font-medium',
        'peer-disabled:cursor-not-allowed peer-disabled:opacity-70',
        'transition-colors duration-150',
        className,
      )}
      {...props}
    />
  )
}
