import { useCallback, useMemo, useRef, useState, type ReactNode } from 'react'
import { CheckCircle2, AlertCircle, Info, X } from 'lucide-react'
import { cn } from '@/lib/utils'
import { ToastContext, type ToastContextValue } from './useToast'

type ToastVariant = 'success' | 'error' | 'info'

interface Toast {
  id: number
  title: string
  description?: string
  variant: ToastVariant
}

const VARIANT_STYLES: Record<ToastVariant, { icon: typeof CheckCircle2; accent: string }> = {
  success: { icon: CheckCircle2, accent: 'text-success' },
  error: { icon: AlertCircle, accent: 'text-destructive' },
  info: { icon: Info, accent: 'text-info' },
}

export function ToastProvider({ children }: { children: ReactNode }) {
  const [toasts, setToasts] = useState<Toast[]>([])
  const idRef = useRef(0)

  const dismiss = useCallback((id: number) => {
    setToasts((prev) => prev.filter((t) => t.id !== id))
  }, [])

  const toast = useCallback(
    ({
      title,
      description,
      variant = 'info',
    }: {
      title: string
      description?: string
      variant?: ToastVariant
    }) => {
      const id = ++idRef.current
      setToasts((prev) => [
        ...prev,
        { id, title, variant, ...(description !== undefined && { description }) },
      ])
      window.setTimeout(() => dismiss(id), 4000)
    },
    [dismiss],
  )

  const value = useMemo<ToastContextValue>(() => ({ toast }), [toast])

  return (
    <ToastContext.Provider value={value}>
      {children}
      <div className="pointer-events-none fixed right-4 bottom-4 z-[100] flex w-full max-w-sm flex-col gap-2">
        {toasts.map((t) => {
          const { icon: Icon, accent } = VARIANT_STYLES[t.variant]
          return (
            <div
              key={t.id}
              className="glass-card animate-toast-in pointer-events-auto flex items-start gap-3 rounded-lg p-4"
              role="alert"
            >
              <Icon className={cn('mt-0.5 h-5 w-5 shrink-0', accent)} />
              <div className="min-w-0 flex-1">
                <p className="text-foreground text-sm font-medium">{t.title}</p>
                {t.description && (
                  <p className="text-muted-foreground mt-1 text-sm">{t.description}</p>
                )}
              </div>
              <button
                type="button"
                onClick={() => dismiss(t.id)}
                className="text-muted-foreground hover:bg-accent hover:text-foreground shrink-0 rounded-md p-1 transition-colors"
                aria-label="Dismiss"
              >
                <X className="h-4 w-4" />
              </button>
            </div>
          )
        })}
      </div>
    </ToastContext.Provider>
  )
}
