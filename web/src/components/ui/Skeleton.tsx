import { type HTMLAttributes } from 'react'
import { cn } from '@/lib/utils'

export function Skeleton({ className, ...props }: HTMLAttributes<HTMLDivElement>) {
  return (
    <div
      className={cn('bg-muted animate-pulse rounded-md', className)}
      style={{ animationDuration: '1.5s' }}
      {...props}
    />
  )
}

export function SkeletonList({ items = 5 }: { items?: number }) {
  return (
    <ul className="divide-border/30 divide-y" aria-busy="true">
      {Array.from({ length: items }).map((_, i) => (
        <li key={i} className="py-4 first:pt-0 last:pb-0">
          <Skeleton className="h-5 w-3/4" />
          <Skeleton className="mt-2 h-3 w-1/4" />
        </li>
      ))}
    </ul>
  )
}

export function ReportListItemSkeleton() {
  return (
    <div className="flex items-center justify-between gap-3 py-4">
      <div className="flex-1 space-y-2">
        <Skeleton className="h-5 w-3/4" />
        <div className="flex gap-2">
          <Skeleton className="h-4 w-20" />
          <Skeleton className="h-4 w-16" />
        </div>
      </div>
      <Skeleton className="h-5 w-5" />
    </div>
  )
}

export function ReportDetailSkeleton() {
  return (
    <>
      <Skeleton className="mb-3 h-8 w-2/3" />
      <div className="mb-6 flex gap-2">
        <Skeleton className="h-5 w-24" />
        <Skeleton className="h-5 w-20" />
        <Skeleton className="h-5 w-16" />
      </div>
      <div className="space-y-3">
        <Skeleton className="h-4 w-full" />
        <Skeleton className="h-4 w-5/6" />
        <Skeleton className="h-4 w-4/6" />
        <Skeleton className="h-24 w-full" />
        <Skeleton className="h-4 w-full" />
        <Skeleton className="h-4 w-3/4" />
      </div>
    </>
  )
}
