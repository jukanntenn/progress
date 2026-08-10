import { zodResolver } from '@hookform/resolvers/zod'
import { useState } from 'react'
import { Navigate, useLocation, useNavigate } from 'react-router'
import { useForm } from 'react-hook-form'
import { useTranslation } from 'react-i18next'
import { Eye, EyeOff, AlertCircle, User, Lock } from 'lucide-react'
import { z } from 'zod'
import { Button } from '@/components/ui/Button'
import { Input } from '@/components/ui/Input'
import { Label } from '@/components/ui/Label'
import { useAuth } from './useAuth'

interface LocationState {
  from?: { pathname: string }
}

export default function LoginPage() {
  const { t } = useTranslation()
  const { login, isAuthenticated, isLoading } = useAuth()
  const navigate = useNavigate()
  const location = useLocation()
  const [showPassword, setShowPassword] = useState(false)
  const [globalError, setGlobalError] = useState<string | null>(null)

  const from = (location.state as LocationState | null)?.from?.pathname ?? '/reports'

  const schema = z.object({
    username: z.string().min(3, t('auth.usernameTooShort')),
    password: z.string().min(8, t('auth.passwordTooShort')),
  })
  type FormValues = z.infer<typeof schema>

  const {
    register,
    handleSubmit,
    formState: { errors, isSubmitting },
  } = useForm<FormValues>({
    resolver: zodResolver(schema),
    defaultValues: { username: '', password: '' },
  })

  if (isLoading) {
    return (
      <main className="flex min-h-screen items-center justify-center px-4">
        <div className="glass-card w-full max-w-sm rounded-xl border p-6">
          <div className="space-y-4">
            <div className="bg-muted mx-auto h-12 w-12 animate-pulse rounded-full" />
            <div className="bg-muted mx-auto h-6 w-32 animate-pulse rounded" />
            <div className="bg-muted h-4 w-full animate-pulse rounded" />
            <div className="bg-muted h-10 w-full animate-pulse rounded-md" />
            <div className="bg-muted h-10 w-full animate-pulse rounded-md" />
            <div className="bg-muted h-10 w-full animate-pulse rounded-md" />
          </div>
        </div>
      </main>
    )
  }

  if (isAuthenticated) return <Navigate to={from} replace />

  const onSubmit = async (values: FormValues) => {
    setGlobalError(null)
    try {
      await login(values.username, values.password)
      navigate(from, { replace: true })
    } catch (err) {
      const msg = err instanceof Error ? err.message : ''
      if (/invalid|incorrect|credentials|401/i.test(msg)) {
        setGlobalError(t('auth.invalidCredentials'))
      } else if (/disabled|inactive|deactivat/i.test(msg)) {
        setGlobalError(t('auth.accountDisabled'))
      } else {
        setGlobalError(t('auth.loginFailed'))
      }
    }
  }

  return (
    <main className="relative flex min-h-screen items-center justify-center overflow-hidden px-4 py-12">
      <div className="w-full max-w-sm">
        <div className="mb-8 text-center">
          <div className="glass-card mx-auto mb-4 flex h-14 w-14 items-center justify-center rounded-2xl border">
            <span className="text-primary text-2xl font-bold">P</span>
          </div>
          <h1 className="text-foreground text-2xl font-bold tracking-tight">
            {t('auth.welcomeHeading')}
          </h1>
          <p className="text-muted-foreground mt-1.5 text-sm">{t('auth.welcomeSubtitle')}</p>
        </div>

        <div className="glass-card rounded-2xl border p-6">
          {globalError && (
            <div className="border-destructive/30 bg-destructive/10 mb-4 flex items-start gap-2 rounded-lg border p-3">
              <AlertCircle className="text-destructive mt-0.5 h-4 w-4 shrink-0" />
              <p className="text-destructive text-sm">{globalError}</p>
            </div>
          )}

          <form onSubmit={handleSubmit(onSubmit)} className="space-y-4">
            <div className="space-y-1.5">
              <Label htmlFor="username">{t('auth.username')}</Label>
              <div className="relative">
                <User className="text-muted-foreground absolute top-1/2 left-3 h-4 w-4 -translate-y-1/2" />
                <Input
                  id="username"
                  autoComplete="username"
                  autoFocus
                  placeholder={t('auth.usernamePlaceholder')}
                  className="pl-9"
                  error={!!errors.username}
                  {...register('username')}
                />
              </div>
              {errors.username && (
                <p className="text-destructive text-xs">{errors.username.message}</p>
              )}
            </div>

            <div className="space-y-1.5">
              <Label htmlFor="password">{t('auth.password')}</Label>
              <div className="relative">
                <Lock className="text-muted-foreground absolute top-1/2 left-3 h-4 w-4 -translate-y-1/2" />
                <Input
                  id="password"
                  type={showPassword ? 'text' : 'password'}
                  autoComplete="current-password"
                  placeholder={t('auth.passwordPlaceholder')}
                  className="px-9"
                  error={!!errors.password}
                  {...register('password')}
                />
                <button
                  type="button"
                  onClick={() => setShowPassword((v) => !v)}
                  className="text-muted-foreground hover:text-foreground absolute inset-y-0 right-0 flex items-center px-3"
                  aria-label={showPassword ? t('auth.hidePassword') : t('auth.showPassword')}
                  tabIndex={-1}
                >
                  {showPassword ? <EyeOff className="h-4 w-4" /> : <Eye className="h-4 w-4" />}
                </button>
              </div>
              {errors.password && (
                <p className="text-destructive text-xs">{errors.password.message}</p>
              )}
            </div>

            <Button type="submit" className="w-full" disabled={isSubmitting}>
              {isSubmitting ? t('auth.signingIn') : t('auth.signIn')}
            </Button>
          </form>
        </div>
      </div>
    </main>
  )
}
