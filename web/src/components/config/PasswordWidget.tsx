/**
 * PasswordWidget: SecretStr fields rendered as ``type="password"`` with an
 * eye toggle that reveals/obscures the plaintext in place (no backend
 * round-trip — the value lives in the form state).
 *
 * Honors ``ui:emptyValue`` (spec 7.2): clearing the input emits ``""`` rather
 * than ``null`` so the backend never receives a rejected ``null``.
 */

import { useState } from 'react'
import { Eye, EyeOff } from 'lucide-react'
import type { WidgetProps } from '@rjsf/utils'
import { ariaDescribedByIds, getUiOptions } from '@rjsf/utils'
import { Input } from '@/components/ui/Input'
import { cn } from '@/lib/utils'

export function PasswordWidget(props: WidgetProps) {
  const {
    id,
    htmlName,
    placeholder,
    required,
    readonly,
    disabled,
    autofocus,
    value,
    onChange,
    onBlur,
    onFocus,
    uiSchema,
    rawErrors = [],
    className,
  } = props
  const [revealed, setRevealed] = useState(false)
  const emptyValue = getUiOptions(uiSchema).emptyValue

  return (
    <div className={cn('flex items-center gap-0', className)}>
      <Input
        id={id}
        name={htmlName || id}
        type={revealed ? 'text' : 'password'}
        placeholder={placeholder ?? '••••••••'}
        required={required}
        disabled={disabled || readonly}
        readOnly={readonly}
        autoFocus={autofocus}
        value={value ?? ''}
        autoComplete="off"
        onChange={(e) => onChange(e.target.value === '' ? emptyValue : e.target.value)}
        onBlur={(e) => onBlur(id, e.target.value)}
        onFocus={(e) => onFocus(id, e.target.value)}
        aria-describedby={ariaDescribedByIds(id)}
        error={rawErrors.length > 0}
        className={cn(
          revealed && 'rounded-r-none border-r-0',
          !revealed && 'rounded-r-none border-r-0',
        )}
      />
      <button
        type="button"
        onClick={() => setRevealed((v) => !v)}
        disabled={disabled || readonly}
        aria-label={revealed ? 'Hide password' : 'Show password'}
        aria-pressed={revealed}
        className={cn(
          'glass-input text-muted-foreground hover:text-foreground rounded-l-none border-l-0',
          'flex h-10 w-10 shrink-0 items-center justify-center rounded-r-md',
          'focus-visible:ring-ring/50 transition-colors duration-200 focus-visible:ring-2 focus-visible:outline-none',
          'disabled:cursor-not-allowed disabled:opacity-50',
          rawErrors.length > 0 && 'border-error/50',
        )}
      >
        {revealed ? <EyeOff className="h-4 w-4" /> : <Eye className="h-4 w-4" />}
      </button>
    </div>
  )
}

export default PasswordWidget
