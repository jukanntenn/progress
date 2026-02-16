import React, { createContext, useCallback, useContext, useState } from 'react'
import { cn } from '@/lib/utils'
import { X, CheckCircle, AlertCircle, Info, AlertTriangle } from 'lucide-react'

type ToastType = 'success' | 'error' | 'info' | 'warning'

interface Toast {
  id: number
  message: string
  type: ToastType
  isExiting?: boolean
}

interface ToastContextType {
  showToast: (message: string, type?: ToastType) => void
}

const ToastContext = createContext<ToastContextType | undefined>(undefined)

export function useToast() {
  const context = useContext(ToastContext)
  if (!context) {
    throw new Error('useToast must be used within a ToastProvider')
  }
  return context
}

const toastConfig: Record<ToastType, { className: string; icon: React.ReactNode }> = {
  success: {
    className: 'bg-success text-success-foreground',
    icon: <CheckCircle className="h-4 w-4" />,
  },
  error: {
    className: 'bg-error text-error-foreground',
    icon: <AlertCircle className="h-4 w-4" />,
  },
  info: {
    className: 'bg-info text-info-foreground',
    icon: <Info className="h-4 w-4" />,
  },
  warning: {
    className: 'bg-warning text-warning-foreground',
    icon: <AlertTriangle className="h-4 w-4" />,
  },
}

/**
 * ToastProvider Component
 * Liquid Glass toasts with backdrop blur and smooth animations.
 * Uses --radius-md (14px) for Apple-style rounded corners.
 */
export function ToastProvider({ children }: { children: React.ReactNode }) {
  const [toasts, setToasts] = useState<Toast[]>([])

  const removeToast = useCallback((id: number) => {
    setToasts((prev) =>
      prev.map((t) => (t.id === id ? { ...t, isExiting: true } : t))
    )

    setTimeout(() => {
      setToasts((prev) => prev.filter((t) => t.id !== id))
    }, 200)
  }, [])

  const showToast = useCallback((message: string, type: ToastType = 'info') => {
    const id = Date.now()
    setToasts((prev) => [...prev, { id, message, type }])

    setTimeout(() => {
      removeToast(id)
    }, 4000)
  }, [removeToast])

  return (
    <ToastContext.Provider value={{ showToast }}>
      {children}
      <div
        className="fixed bottom-4 right-4 z-toast flex flex-col gap-2"
        role="region"
        aria-label="Notifications"
      >
        {toasts.map((toast) => {
          const config = toastConfig[toast.type]
          return (
            <div
              key={toast.id}
              role="alert"
              className={cn(
                'flex items-center gap-3 rounded-md px-4 py-3 text-sm',
                'backdrop-blur-glass-2 saturate-glass',
                'shadow-glass transition-all duration-200 ease-out',
                toast.isExiting
                  ? 'opacity-0 translate-x-2 scale-[0.98]'
                  : 'opacity-100 translate-x-0 scale-100 animate-toast-in',
                config.className
              )}
            >
              {config.icon}
              <span>{toast.message}</span>
              <button
                onClick={() => removeToast(toast.id)}
                className={cn(
                  'ml-2 rounded p-1 opacity-70 hover:opacity-100',
                  'transition-opacity duration-150',
                  'focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-white/50'
                )}
                aria-label="Dismiss notification"
              >
                <X className="h-3 w-3" />
              </button>
            </div>
          )
        })}
      </div>
    </ToastContext.Provider>
  )
}
