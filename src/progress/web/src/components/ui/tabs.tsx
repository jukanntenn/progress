import * as React from 'react'
import { cn } from '@/lib/utils'

interface TabsProps {
  value: string
  onValueChange: (value: string) => void
  children: React.ReactNode
}

interface TabsListProps {
  children: React.ReactNode
  className?: string
}

interface TabsTriggerProps {
  value: string
  children: React.ReactNode
}

interface TabsContentProps {
  value: string
  children: React.ReactNode
}

const TabsContext = React.createContext<{
  value: string
  onValueChange: (value: string) => void
} | null>(null)

const Tabs: React.FC<TabsProps> = ({ value, onValueChange, children }) => (
  <TabsContext.Provider value={{ value, onValueChange }}>
    {children}
  </TabsContext.Provider>
)

const TabsList: React.FC<TabsListProps> = ({ children, className }) => (
  <div className={cn('flex gap-2', className)}>{children}</div>
)

const TabsTrigger: React.FC<TabsTriggerProps> = ({ value, children }) => {
  const context = React.useContext(TabsContext)
  if (!context) throw new Error('TabsTrigger must be used within Tabs')

  const isActive = context.value === value

  return (
    <button
      onClick={() => context.onValueChange(value)}
      className={cn(
        'rounded-lg px-3 py-1.5 text-sm font-medium transition-colors',
        isActive
          ? 'bg-blue-600 text-white'
          : 'text-gray-600 hover:bg-gray-100 dark:text-gray-400 dark:hover:bg-gray-700',
      )}
    >
      {children}
    </button>
  )
}

const TabsContent: React.FC<TabsContentProps> = ({ value, children }) => {
  const context = React.useContext(TabsContext)
  if (!context) throw new Error('TabsContent must be used within Tabs')

  if (context.value !== value) return null
  return <>{children}</>
}

export { Tabs, TabsList, TabsTrigger, TabsContent }

