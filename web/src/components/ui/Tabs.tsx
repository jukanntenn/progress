import { Tabs as TabsPrimitive } from '@base-ui/react/tabs'
import { cn } from '@/lib/utils'

export function Tabs({
  value,
  onValueChange,
  defaultValue,
  children,
  className,
}: {
  value?: string
  defaultValue?: string
  onValueChange?: (value: string) => void
  children: React.ReactNode
  className?: string
}) {
  return (
    <TabsPrimitive.Root
      value={value}
      defaultValue={defaultValue}
      onValueChange={onValueChange}
      className={className}
    >
      {children}
    </TabsPrimitive.Root>
  )
}

export function TabsList({
  children,
  className,
}: {
  children: React.ReactNode
  className?: string
}) {
  return (
    <TabsPrimitive.List
      className={cn(
        'inline-flex h-10 items-center justify-center rounded-md p-1',
        'bg-muted/50 saturate-150 backdrop-blur-sm',
        'text-muted-foreground',
        className,
      )}
    >
      {children}
    </TabsPrimitive.List>
  )
}

export function TabsTrigger({
  value,
  children,
  className,
}: {
  value: string
  children: React.ReactNode
  className?: string
}) {
  return (
    <TabsPrimitive.Tab
      value={value}
      className={cn(
        'inline-flex items-center justify-center rounded-sm px-3 py-1.5 whitespace-nowrap',
        'ring-offset-background text-sm font-medium',
        'transition-all duration-200 ease-out',
        'focus-visible:ring-ring/50 focus-visible:ring-2 focus-visible:outline-none',
        'data-[selected]:bg-glass-bg-primary/90 data-[selected]:text-foreground data-[selected]:shadow-sm',
        'hover:text-foreground hover:bg-glass-bg-primary/40',
        className,
      )}
    >
      {children}
    </TabsPrimitive.Tab>
  )
}

export function TabsContent({
  value,
  children,
  className,
}: {
  value: string
  children: React.ReactNode
  className?: string
}) {
  return (
    <TabsPrimitive.Panel
      value={value}
      className={cn(
        'ring-offset-background mt-2',
        'focus-visible:ring-ring focus-visible:ring-2 focus-visible:ring-offset-2 focus-visible:outline-none',
        'animate-fade-in',
        className,
      )}
    >
      {children}
    </TabsPrimitive.Panel>
  )
}
