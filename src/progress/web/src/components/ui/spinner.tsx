import * as React from 'react'
import { cn } from '@/lib/utils'

interface SpinnerProps extends React.HTMLAttributes<SVGElement> {
  size?: 'sm' | 'md' | 'lg'
}

const sizeMap = {
  sm: 'h-3 w-3',
  md: 'h-4 w-4',
  lg: 'h-6 w-6',
}

const Spinner = React.forwardRef<SVGSVGElement, SpinnerProps>(
  ({ className, size = 'md', ...props }, ref) => (
    <svg
      ref={ref}
      className={cn(
        'animate-spin text-current',
        sizeMap[size],
        className
      )}
      xmlns="http://www.w3.org/2000/svg"
      fill="none"
      viewBox="0 0 24 24"
      {...props}
    >
      <circle
        className="opacity-25"
        cx="12"
        cy="12"
        r="10"
        stroke="currentColor"
        strokeWidth="4"
      />
      <path
        className="opacity-75"
        fill="currentColor"
        d="M4 12a8 8 0 018-8V0C5.373 0 0 5.373 0 12h4zm2 5.291A7.962 7.962 0 014 12H0c0 3.042 1.135 5.824 3 7.938l3-2.647z"
      />
    </svg>
  )
)
Spinner.displayName = 'Spinner'

interface LoadingDotsProps extends React.HTMLAttributes<HTMLSpanElement> {
  size?: 'sm' | 'md' | 'lg'
}

const dotSizeMap = {
  sm: 'h-1 w-1',
  md: 'h-1.5 w-1.5',
  lg: 'h-2 w-2',
}

const LoadingDots = React.forwardRef<HTMLSpanElement, LoadingDotsProps>(
  ({ className, size = 'md', ...props }, ref) => {
    return (
      <span
        ref={ref}
        className={cn('inline-flex items-center gap-1', className)}
        {...props}
      >
        {[0, 1, 2].map((index) => (
          <span
            key={index}
            className={cn(
              'rounded-full bg-current',
              dotSizeMap[size]
            )}
            style={{
              animation: 'pulse-gentle 1.4s ease-in-out infinite',
              animationDelay: `${index * 0.15}s`,
            }}
          />
        ))}
      </span>
    )
  }
)
LoadingDots.displayName = 'LoadingDots'

export { Spinner, LoadingDots }
