import { useState } from 'react'
import { useTranslation } from 'react-i18next'
import { Eye, EyeOff, AlertCircle } from 'lucide-react'
import { Button } from '@/components/ui/Button'
import { Card, CardContent, CardHeader, CardTitle } from '@/components/ui/Card'
import { Input } from '@/components/ui/Input'
import { Label } from '@/components/ui/Label'
import { fetchClient } from '@/api/client'
import { useAuth } from '@/auth/useAuth'

function PasswordField({
  id,
  label,
  value,
  onChange,
  placeholder,
  error,
}: {
  id: string
  label: string
  value: string
  onChange: (v: string) => void
  placeholder?: string
  error?: string | null
}) {
  const { t } = useTranslation()
  const [visible, setVisible] = useState(false)
  return (
    <div className="space-y-1.5">
      <Label htmlFor={id}>{label}</Label>
      <div className="relative">
        <Input
          id={id}
          type={visible ? 'text' : 'password'}
          value={value}
          onChange={(e) => onChange(e.target.value)}
          placeholder={placeholder}
          error={!!error}
          className="pr-10"
        />
        <button
          type="button"
          onClick={() => setVisible((v) => !v)}
          className="text-muted-foreground hover:text-foreground absolute inset-y-0 right-0 flex h-full w-9 items-center justify-center"
          aria-label={visible ? t('settings.hidePassword') : t('settings.showPassword')}
        >
          {visible ? <EyeOff className="h-4 w-4" /> : <Eye className="h-4 w-4" />}
        </button>
      </div>
      {error && <p className="text-destructive text-xs">{error}</p>}
    </div>
  )
}

export default function SettingsPage() {
  const { t } = useTranslation()
  const { user } = useAuth()
  const [currentPassword, setCurrentPassword] = useState('')
  const [newPassword, setNewPassword] = useState('')
  const [confirmPassword, setConfirmPassword] = useState('')
  const [globalError, setGlobalError] = useState<string | null>(null)
  const [fieldError, setFieldError] = useState<string | null>(null)
  const [success, setSuccess] = useState('')
  const [submitting, setSubmitting] = useState(false)

  const passwordsMatch = newPassword === confirmPassword
  const sameAsCurrent = newPassword.length > 0 && newPassword === currentPassword
  const confirmError =
    confirmPassword.length > 0 && !passwordsMatch ? t('settings.passwordMismatch') : null
  const newError = sameAsCurrent ? t('settings.passwordSameAsCurrent') : null
  const canSubmit =
    currentPassword.length > 0 &&
    newPassword.length >= 8 &&
    passwordsMatch &&
    !sameAsCurrent &&
    !submitting

  async function handleSubmit(e: React.FormEvent) {
    e.preventDefault()
    setGlobalError(null)
    setFieldError(null)
    setSuccess('')
    if (!passwordsMatch) {
      setFieldError(t('settings.passwordMismatch'))
      return
    }
    if (sameAsCurrent) {
      setFieldError(t('settings.passwordSameAsCurrent'))
      return
    }
    setSubmitting(true)
    try {
      const { response } = await fetchClient.POST('/api/v1/auth/change-password', {
        body: { current_password: currentPassword, new_password: newPassword },
      })
      if (!response.ok) {
        const body = await response.json().catch(() => null)
        const msg = body?.error?.message ?? 'Failed to change password'
        if (/current|incorrect|invalid/i.test(msg)) {
          setFieldError(t('settings.incorrectPassword'))
        } else {
          setGlobalError(msg)
        }
        return
      }
      setSuccess(t('settings.passwordChanged'))
      setCurrentPassword('')
      setNewPassword('')
      setConfirmPassword('')
    } catch (err) {
      setGlobalError(err instanceof Error ? err.message : 'Failed to change password')
    } finally {
      setSubmitting(false)
    }
  }

  return (
    <div className="space-y-4">
      <h2 className="text-muted-foreground font-mono text-sm font-semibold tracking-wide uppercase">
        {t('settings.changePassword')}
      </h2>
      <Card>
        <CardHeader>
          <CardTitle>{t('settings.changePassword')}</CardTitle>
        </CardHeader>
        <CardContent>
          <form onSubmit={handleSubmit} className="space-y-5">
            <div className="text-muted-foreground text-sm">
              {t('settings.userLabel', { username: user?.username ?? '' })}
            </div>

            {globalError && (
              <div className="border-destructive/30 bg-destructive/10 flex items-start gap-2 rounded-lg border p-3">
                <AlertCircle className="text-destructive mt-0.5 h-4 w-4 shrink-0" />
                <p className="text-destructive text-sm">{globalError}</p>
              </div>
            )}

            <PasswordField
              id="currentPassword"
              label={t('settings.currentPassword')}
              value={currentPassword}
              onChange={setCurrentPassword}
              error={fieldError}
            />

            <PasswordField
              id="newPassword"
              label={t('settings.newPassword')}
              value={newPassword}
              onChange={setNewPassword}
              placeholder={t('settings.newPasswordPlaceholder')}
              error={newError}
            />

            <PasswordField
              id="confirmPassword"
              label={t('settings.confirmPassword')}
              value={confirmPassword}
              onChange={setConfirmPassword}
              error={confirmError}
            />

            {success && <p className="text-sm text-green-600">{success}</p>}

            <Button type="submit" disabled={!canSubmit} className="w-full">
              {submitting ? t('settings.changing') : t('settings.submit')}
            </Button>
          </form>
        </CardContent>
      </Card>
    </div>
  )
}
