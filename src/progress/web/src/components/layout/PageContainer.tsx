import { cn } from '@/lib/utils'
import { ReactNode } from 'react'

type ContainerSize = 'narrow' | 'medium' | 'wide'

interface PageContainerProps {
  children: ReactNode
  size?: ContainerSize
  className?: string
}

const containerSizes: Record<ContainerSize, string> = {
  narrow: 'max-w-2xl',
  medium: 'max-w-3xl',
  wide: 'max-w-6xl',
}

/**
 * PageContainer Component
 * Consistent page wrapper with proper spacing and max-width.
 * Handles responsive padding and provides visual consistency.
 * Includes id="main-content" for skip-to-content accessibility.
 * Works with gradient background defined in index.css.
 */
export function PageContainer({
  children,
  size = 'medium',
  className,
}: PageContainerProps) {
  return (
    <main
      id="main-content"
      className={cn(
        'mx-auto px-4 py-4',
        'sm:px-6 sm:py-8',
        'lg:px-8 lg:py-10',
        containerSizes[size],
        'animate-fade-in',
        'min-h-[calc(100vh-4rem)]',
        className
      )}
      tabIndex={-1}
    >
      {children}
    </main>
  )
}
