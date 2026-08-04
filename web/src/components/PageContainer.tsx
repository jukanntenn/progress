import { type ReactNode } from 'react'
import { cn } from '@/lib/utils'

interface PageContainerProps {
  children: ReactNode
  className?: string
  size?: 'narrow' | 'medium' | 'wide'
}

const sizeClass: Record<NonNullable<PageContainerProps['size']>, string> = {
  narrow: 'max-w-2xl',
  medium: 'max-w-3xl',
  wide: 'max-w-6xl',
}

export function PageContainer({ children, className, size = 'medium' }: PageContainerProps) {
  return (
    <main
      id="main-content"
      tabIndex={-1}
      className={cn(
        'animate-fade-in mx-auto min-h-[calc(100vh-3.5rem)] w-full px-4 py-4 sm:px-6 sm:py-8 lg:px-8 lg:py-10',
        sizeClass[size],
        className,
      )}
    >
      {children}
    </main>
  )
}
