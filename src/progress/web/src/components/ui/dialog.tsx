import * as React from 'react'
import { cn } from '@/lib/utils'
import { X } from 'lucide-react'

interface DialogProps {
  open: boolean
  onClose: () => void
  title: string
  description?: string
  children: React.ReactNode
}

/**
 * Dialog Component
 * Liquid Glass modal with deep blur and specular highlight.
 * Uses --radius-xl (28px) for Apple-style rounded corners.
 */
const Dialog: React.FC<DialogProps> = ({ open, onClose, title, description, children }) => {
  const [isVisible, setIsVisible] = React.useState(false)
  const [shouldRender, setShouldRender] = React.useState(false)

  React.useEffect(() => {
    if (open) {
      setShouldRender(true)
      requestAnimationFrame(() => {
        setIsVisible(true)
      })
    } else {
      setIsVisible(false)
      const timer = setTimeout(() => {
        setShouldRender(false)
      }, 200)
      return () => clearTimeout(timer)
    }
  }, [open])

  if (!shouldRender) return null

  return (
    <div className="fixed inset-0 z-modal flex items-center justify-center">
      <div
        className={cn(
          'fixed inset-0 z-modal-backdrop bg-black/40 backdrop-blur-glass-2',
          'transition-opacity duration-200 ease-out',
          isVisible ? 'opacity-100' : 'opacity-0'
        )}
        onClick={onClose}
        aria-hidden="true"
      />
      <div
        role="dialog"
        aria-modal="true"
        aria-labelledby="dialog-title"
        className={cn(
          'glass-modal relative z-modal mx-4 w-full max-w-md rounded-xl p-0',
          'transition-all duration-200 ease-out',
          isVisible
            ? 'opacity-100 translate-y-0 scale-100'
            : 'opacity-0 translate-y-4 scale-[0.98]'
        )}
      >
        <div className="flex items-center justify-between border-b border-border/30 p-6">
          <div>
            <h3
              id="dialog-title"
              className="text-lg font-semibold text-foreground"
            >
              {title}
            </h3>
            {description && (
              <p className="mt-1 text-sm text-muted-foreground">{description}</p>
            )}
          </div>
          <button
            onClick={onClose}
            className={cn(
              'rounded-lg p-2 text-muted-foreground',
              'hover:bg-accent/50 hover:text-foreground',
              'transition-all duration-200 ease-out active:scale-95',
              'focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring/50'
            )}
            aria-label="Close dialog"
          >
            <X className="h-5 w-5" />
          </button>
        </div>
        <div className="p-6">{children}</div>
      </div>
    </div>
  )
}

export { Dialog }
