import { useState } from 'react'
import { useTranslation } from 'react-i18next'
import { Eye, EyeOff } from 'lucide-react'
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
}: {
  id: string
  label: string
  value: string
  onChange: (v: string) => void
  placeholder?: string
}) {
  const [visible, setVisible] = useState(false)
  const { t } = useTranslation()
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
    </div>
  )
}

export default function SettingsPage() {
  const { t } = useTranslation()
  const { user } = useAuth()
  const [currentPassword, setCurrentPassword] = useState('')
  const [newPassword, setNewPassword] = useState('')
  const [confirmPassword, setConfirmPassword] = useState('')
  const [error, setError] = useState('')
  const [success, setSuccess] = useState('')
  const [submitting, setSubmitting] = useState(false)

  const passwordsMatch = newPassword === confirmPassword
  const sameAsCurrent = newPassword.length > 0 && newPassword === currentPassword
  const canSubmit =
    currentPassword.length > 0 && newPassword.length >= 8 && passwordsMatch && !sameAsCurrent

  async function handleSubmit(e: React.FormEvent) {
    e.preventDefault()
    setError('')
    setSuccess('')
    if (!passwordsMatch) {
      setError(t('settings.passwordMismatch'))
      return
    }
    if (sameAsCurrent) {
      setError(t('settings.passwordSameAsCurrent'))
      return
    }
    setSubmitting(true)
    try {
      const { response } = await fetchClient.POST('/api/v1/auth/change-password', {
        body: { current_password: currentPassword, new_password: newPassword },
      })
      if (!response.ok) {
        const body = await response.json().catch(() => null)
        throw new Error(body?.error?.message ?? 'Failed to change password')
      }
      setSuccess(t('settings.passwordChanged'))
      setCurrentPassword('')
      setNewPassword('')
      setConfirmPassword('')
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Failed to change password')
    } finally {
      setSubmitting(false)
    }
  }

  return (
    <div className="mx-auto max-w-xl px-4 py-8">
      <Card>
        <CardHeader>
          <CardTitle>{t('settings.title')}</CardTitle>
        </CardHeader>
        <CardContent>
          <form onSubmit={handleSubmit} className="space-y-5">
            <div className="text-muted-foreground text-sm">
              {t('settings.userLabel', { username: user?.username ?? '' })}
            </div>

            <PasswordField
              id="currentPassword"
              label={t('settings.currentPassword')}
              value={currentPassword}
              onChange={setCurrentPassword}
            />

            <PasswordField
              id="newPassword"
              label={t('settings.newPassword')}
              value={newPassword}
              onChange={setNewPassword}
              placeholder={t('settings.newPasswordPlaceholder')}
            />

            <PasswordField
              id="confirmPassword"
              label={t('settings.confirmPassword')}
              value={confirmPassword}
              onChange={setConfirmPassword}
            />

            {!passwordsMatch && confirmPassword.length > 0 && (
              <p className="text-destructive text-sm">{t('settings.passwordMismatch')}</p>
            )}
            {sameAsCurrent && (
              <p className="text-destructive text-sm">{t('settings.passwordSameAsCurrent')}</p>
            )}

            {error && <p className="text-destructive text-sm">{error}</p>}
            {success && <p className="text-sm text-green-600">{success}</p>}

            <Button type="submit" disabled={!canSubmit || submitting} className="w-full">
              {submitting ? t('settings.changing') : t('settings.submit')}
            </Button>
          </form>
        </CardContent>
      </Card>
    </div>
  )
}
