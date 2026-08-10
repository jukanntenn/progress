/**
 * CheckboxesWidget: multi-select enums rendered as a checkbox grid.
 */

import type { WidgetProps } from '@rjsf/utils'
import {
  ariaDescribedByIds,
  enumOptionValueDecoder,
  enumOptionValueEncoder,
  enumOptionsIsSelected,
  getOptionValueFormat,
  optionId,
} from '@rjsf/utils'
import { Checkbox } from '@/components/ui/Checkbox'
import { Label } from '@/components/ui/Label'
import { cn } from '@/lib/utils'

export function CheckboxesWidget(props: WidgetProps) {
  const { id, options, value, disabled, readonly, onChange, onBlur, onFocus, className } = props
  const { enumOptions, enumDisabled, emptyValue } = options
  const optionValueFormat = getOptionValueFormat(options)

  const handleChange = (checked: boolean, index: number) => {
    if (!enumOptions) return
    const optionValue = enumOptionValueEncoder(enumOptions[index]?.value, index, optionValueFormat)
    const selected = Array.isArray(value) ? value.map((v) => String(v)) : []
    const next = checked ? [...selected, optionValue] : selected.filter((v) => v !== optionValue)
    onChange(enumOptionValueDecoder(next, enumOptions, optionValueFormat, emptyValue))
  }

  return (
    <div className={cn('space-y-2', className)}>
      {enumOptions?.map(({ value: enumValue, label: enumLabel }, index: number) => {
        const checked = enumOptionsIsSelected(String(enumValue), value as string[])
        const itemDisabled =
          disabled || readonly || (Array.isArray(enumDisabled) && enumDisabled.includes(enumValue))
        return (
          <div key={index} className="flex items-center gap-2">
            <Checkbox
              id={optionId(id, index)}
              checked={checked}
              disabled={itemDisabled}
              onChange={(e) => handleChange(e.currentTarget.checked, index)}
              onBlur={() => onBlur(id, value)}
              onFocus={() => onFocus(id, value)}
              aria-describedby={ariaDescribedByIds(id)}
            />
            <Label
              className="text-foreground cursor-pointer leading-tight"
              htmlFor={optionId(id, index)}
            >
              {enumLabel}
            </Label>
          </div>
        )
      })}
    </div>
  )
}

export default CheckboxesWidget
