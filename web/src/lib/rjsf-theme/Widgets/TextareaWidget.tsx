/**
 * TextareaWidget: long string fields rendered with the shared ui/Textarea.
 */

import type { WidgetProps } from '@rjsf/utils'
import { ariaDescribedByIds } from '@rjsf/utils'
import { Textarea } from '@/components/ui/Textarea'
import { cn } from '@/lib/utils'

export function TextareaWidget(props: WidgetProps) {
  const {
    id,
    placeholder,
    required,
    readonly,
    disabled,
    autofocus,
    value,
    onChange,
    onBlur,
    onFocus,
    options,
    schema,
    rawErrors = [],
    className,
  } = props

  const handleChange = (next: string) => onChange(next === '' ? options.emptyValue : next)

  return (
    <Textarea
      id={id}
      placeholder={placeholder}
      required={required}
      disabled={disabled}
      readOnly={readonly}
      autoFocus={autofocus}
      value={value ?? ''}
      onChange={(e) => handleChange(e.target.value)}
      onBlur={(e) => onBlur(id, e.target.value)}
      onFocus={(e) => onFocus(id, e.target.value)}
      aria-describedby={ariaDescribedByIds(id)}
      error={rawErrors.length > 0}
      className={cn(className)}
      rows={typeof schema.maxLength === 'number' && schema.maxLength > 80 ? 6 : 3}
    />
  )
}

export default TextareaWidget
