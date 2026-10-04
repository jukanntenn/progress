/**
 * ErrorListTemplate: top-of-form validation error list (AJV submit errors and
 * backend 422 messages).
 */

import { AlertCircle } from 'lucide-react'
import type { ErrorListProps } from '@rjsf/utils'
import { useTranslation } from 'react-i18next'

export function ErrorListTemplate(props: ErrorListProps) {
  const { errors } = props
  const { t } = useTranslation()
  if (errors.length === 0) return null
  return (
    <div className="border-error/40 bg-error/10 rounded-lg border p-4">
      <div className="flex items-center gap-2">
        <AlertCircle className="text-error h-4 w-4" />
        <h3 className="text-foreground text-sm font-semibold">{t('config.validationErrors')}</h3>
      </div>
      <ul className="text-error mt-2 list-disc space-y-1 pl-5 text-xs">
        {errors.map((error, i) => (
          <li key={i}>{error.stack}</li>
        ))}
      </ul>
    </div>
  )
}

export default ErrorListTemplate
