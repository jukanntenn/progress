import * as React from 'react'
import { cn } from '@/lib/utils'

interface SkeletonProps extends React.HTMLAttributes<HTMLDivElement> {
  variant?: 'default' | 'text' | 'circular' | 'rectangular'
  width?: string | number
  height?: string | number
}

const Skeleton = React.forwardRef<HTMLDivElement, SkeletonProps>(
  ({ className, variant = 'default', width, height, style, ...props }, ref) => {
    const variantStyles = {
      default: 'rounded-md',
      text: 'rounded h-4',
      circular: 'rounded-full',
      rectangular: 'rounded-lg',
    }

    return (
      <div
        ref={ref}
        className={cn(
          'skeleton',
          variantStyles[variant],
          className
        )}
        style={{
          width: width,
          height: height,
          ...style,
        }}
        {...props}
      />
    )
  }
)
Skeleton.displayName = 'Skeleton'

const SkeletonText = React.forwardRef<
  HTMLDivElement,
  React.HTMLAttributes<HTMLDivElement> & { lines?: number }
>(({ className, lines = 3, ...props }, ref) => (
  <div ref={ref} className={cn('space-y-2', className)} {...props}>
    {Array.from({ length: lines }).map((_, i) => (
      <Skeleton
        key={i}
        variant="text"
        className={cn(i === lines - 1 && 'w-4/5')}
      />
    ))}
  </div>
))
SkeletonText.displayName = 'SkeletonText'

const SkeletonCard = React.forwardRef<
  HTMLDivElement,
  React.HTMLAttributes<HTMLDivElement>
>(({ className, ...props }, ref) => (
  <div ref={ref} className={cn('card p-6 space-y-4', className)} {...props}>
    <Skeleton className="h-6 w-1/3" />
    <SkeletonText lines={2} />
    <div className="flex gap-2 pt-2">
      <Skeleton className="h-8 w-20" />
      <Skeleton className="h-8 w-20" />
    </div>
  </div>
))
SkeletonCard.displayName = 'SkeletonCard'

const SkeletonList = React.forwardRef<
  HTMLDivElement,
  React.HTMLAttributes<HTMLDivElement> & { items?: number }
>(({ className, items = 5, ...props }, ref) => (
  <div ref={ref} className={cn('space-y-0', className)} {...props}>
    {Array.from({ length: items }).map((_, i) => (
      <div
        key={i}
        className={cn(
          'py-4 border-b border-border last:border-b-0',
          i === 0 && 'pt-0'
        )}
      >
        <Skeleton className="h-5 w-3/4 mb-2" />
        <Skeleton className="h-4 w-1/3" />
      </div>
    ))}
  </div>
))
SkeletonList.displayName = 'SkeletonList'

export { Skeleton, SkeletonText, SkeletonCard, SkeletonList }
