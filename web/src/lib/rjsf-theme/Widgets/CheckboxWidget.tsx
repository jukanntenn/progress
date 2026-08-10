/**
 * CheckboxWidget: boolean fields, rendered inline with their label (the
 * FieldTemplate skips the outer label because RJSF sets displayLabel=false
 * for booleans without an explicit ui:widget).
 */

import type { WidgetProps } from '@rjsf/utils'
import {
  ariaDescribedByIds,
  descriptionId,
  getTemplate,
  labelValue,
  schemaRequiresTrueValue,
} from '@rjsf/utils'
import { Checkbox } from '@/components/ui/Checkbox'
import { Label } from '@/components/ui/Label'

export function CheckboxWidget(props: WidgetProps) {
  const {
    id,
    htmlName,
    value,
    disabled,
    readonly,
    label,
    hideLabel,
    schema,
    autofocus,
    options,
    onChange,
    onBlur,
    onFocus,
    registry,
    uiSchema,
  } = props
  const required = schemaRequiresTrueValue(schema)
  const DescriptionFieldTemplate = getTemplate<'DescriptionFieldTemplate'>(
    'DescriptionFieldTemplate',
    registry,
    options,
  )
  const description = options.description || schema.description

  return (
    <div className={cnGroup(disabled || readonly)} aria-describedby={ariaDescribedByIds(id)}>
      {!hideLabel && description && (
        <DescriptionFieldTemplate
          id={descriptionId(id)}
          description={description}
          schema={schema}
          uiSchema={uiSchema ?? {}}
          registry={registry}
        />
      )}
      <div className="flex items-center gap-2">
        <Checkbox
          id={id}
          name={htmlName || id}
          checked={typeof value === 'undefined' ? false : Boolean(value)}
          required={required}
          disabled={disabled || readonly}
          autoFocus={autofocus}
          onChange={(e) => onChange(e.currentTarget.checked)}
          onBlur={() => onBlur(id, value)}
          onFocus={() => onFocus(id, value)}
        />
        <Label className="text-foreground cursor-pointer leading-tight" htmlFor={id}>
          {labelValue(label, hideLabel || !label)}
        </Label>
      </div>
    </div>
  )
}

function cnGroup(disabled: boolean | undefined): string {
  return disabled ? 'cursor-not-allowed opacity-50' : ''
}

export default CheckboxWidget
