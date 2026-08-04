import { Switch as SwitchPrimitive } from '@base-ui/react/switch'
import { cn } from '@/lib/utils'

export interface SwitchProps extends Omit<
  React.ComponentProps<typeof SwitchPrimitive.Root>,
  'checked'
> {
  checked?: boolean
  onCheckedChange?: (checked: boolean) => void
}

export function Switch({ className, checked, onCheckedChange, ...props }: SwitchProps) {
  return (
    <SwitchPrimitive.Root
      checked={checked}
      onCheckedChange={onCheckedChange}
      className={cn(
        'peer inline-flex h-6 w-11 shrink-0 cursor-pointer items-center rounded-full p-0.5',
        'ring-offset-background transition-colors duration-200 ease-out',
        'focus-visible:ring-ring/50 focus-visible:ring-2 focus-visible:outline-none',
        'data-[checked]:bg-primary data-[unchecked]:bg-muted-foreground/30',
        'disabled:cursor-not-allowed disabled:opacity-50',
        className,
      )}
      {...props}
    >
      <SwitchPrimitive.Thumb
        className={cn(
          'pointer-events-none block h-5 w-5 rounded-full bg-white shadow-lg',
          'ring-0 transition-transform duration-200 ease-out',
          'data-[checked]:translate-x-5 data-[unchecked]:translate-x-0',
        )}
      />
    </SwitchPrimitive.Root>
  )
}
