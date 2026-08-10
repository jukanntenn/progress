/**
 * BaseInputTemplate: every plain <input> (text/number/email/…) routes through
 * here, reusing the shared ui/Input. Honors ``ui:emptyValue`` so clearing a
 * field produces ``""`` instead of ``null`` (spec 7.2).
 */

import type { ChangeEvent } from 'react'
import type { BaseInputTemplateProps } from '@rjsf/utils'
import { ariaDescribedByIds, getInputProps } from '@rjsf/utils'
import { Input } from '@/components/ui/Input'
import { cn } from '@/lib/utils'

export function BaseInputTemplate(props: BaseInputTemplateProps) {
  const {
    id,
    htmlName,
    placeholder,
    required,
    readonly,
    disabled,
    type,
    value,
    onChange,
    onChangeOverride,
    onBlur,
    onFocus,
    autofocus,
    options,
    schema,
    rawErrors = [],
    extraProps,
    className,
  } = props

  const inputProps = {
    ...extraProps,
    ...getInputProps(schema, type, options),
  }

  const handleChange = (e: ChangeEvent<HTMLInputElement>) =>
    onChange(e.target.value === '' ? options.emptyValue : e.target.value)

  return (
    <Input
      id={id}
      name={htmlName || id}
      type={type}
      placeholder={placeholder}
      required={required}
      disabled={disabled}
      readOnly={readonly}
      autoFocus={autofocus}
      value={value ?? ''}
      onChange={onChangeOverride ?? handleChange}
      onBlur={(e) => onBlur(id, e.target.value)}
      onFocus={(e) => onFocus(id, e.target.value)}
      aria-describedby={ariaDescribedByIds(id)}
      error={rawErrors.length > 0}
      {...inputProps}
      className={cn(className)}
    />
  )
}

export default BaseInputTemplate
