/**
 * FieldTemplate: the shell around every single field — label + widget +
 * description + errors + help.
 */

import type { FieldTemplateProps } from '@rjsf/utils'
import { getTemplate, getUiOptions } from '@rjsf/utils'
import { Label } from '@/components/ui/Label'
import { cn } from '@/lib/utils'

export function FieldTemplate(props: FieldTemplateProps) {
  const {
    id,
    children,
    displayLabel,
    rawErrors = [],
    errors,
    help,
    description,
    rawDescription,
    classNames,
    style,
    disabled,
    label,
    hidden,
    onKeyRename,
    onKeyRenameBlur,
    onRemoveProperty,
    readonly,
    required,
    schema,
    uiSchema,
    registry,
  } = props
  const uiOptions = getUiOptions(uiSchema)
  const WrapIfAdditionalTemplate = getTemplate<'WrapIfAdditionalTemplate'>(
    'WrapIfAdditionalTemplate',
    registry,
    uiOptions,
  )

  if (hidden) {
    return <div className="hidden">{children}</div>
  }

  const isCheckbox = uiOptions.widget === 'checkbox'

  return (
    <WrapIfAdditionalTemplate
      classNames={classNames ?? ''}
      style={style ?? {}}
      disabled={disabled}
      id={id}
      label={label}
      displayLabel={displayLabel ?? false}
      onKeyRename={onKeyRename}
      onKeyRenameBlur={onKeyRenameBlur}
      onRemoveProperty={onRemoveProperty}
      rawDescription={rawDescription ?? ''}
      readonly={readonly}
      required={required ?? false}
      schema={schema}
      uiSchema={uiSchema ?? {}}
      registry={registry}
    >
      <div className={cn('space-y-1.5', classNames)} style={style}>
        {displayLabel && !isCheckbox && (
          <Label htmlFor={id} className={cn(rawErrors.length > 0 && 'text-destructive')}>
            {label}
            {required && <span className="text-destructive ml-1">*</span>}
          </Label>
        )}
        {children}
        {displayLabel && rawDescription && !isCheckbox && (
          <span
            className={cn(
              'text-muted-foreground block text-xs leading-relaxed',
              rawErrors.length > 0 && 'text-destructive',
            )}
          >
            {description}
          </span>
        )}
        {errors}
        {help}
      </div>
    </WrapIfAdditionalTemplate>
  )
}

export default FieldTemplate
