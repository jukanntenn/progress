/**
 * RadioWidget: enum fields rendered as a base-ui radio group.
 */

import { Radio } from '@base-ui/react/radio'
import { RadioGroup } from '@base-ui/react/radio-group'
import type { WidgetProps } from '@rjsf/utils'
import {
  ariaDescribedByIds,
  enumOptionValueDecoder,
  enumOptionValueEncoder,
  getOptionValueFormat,
  optionId,
} from '@rjsf/utils'
import { Label } from '@/components/ui/Label'
import { cn } from '@/lib/utils'

export function RadioWidget(props: WidgetProps) {
  const { id, options, value, required, disabled, readonly, onChange, onBlur, onFocus, className } =
    props
  const { enumOptions, enumDisabled, emptyValue } = options
  const optionValueFormat = getOptionValueFormat(options)

  const inline = Boolean(options?.inline)

  return (
    <RadioGroup
      value={value?.toString() ?? ''}
      required={required}
      disabled={disabled || readonly}
      onValueChange={(next) => {
        onChange(enumOptionValueDecoder(next, enumOptions, optionValueFormat, emptyValue))
      }}
      onBlur={() => onBlur(id, value)}
      onFocus={() => onFocus(id, value)}
      aria-describedby={ariaDescribedByIds(id)}
      className={cn('flex', inline ? 'flex-row flex-wrap gap-4' : 'flex-col gap-2', className)}
    >
      {enumOptions?.map(({ value: enumValue, label: enumLabel }, index: number) => {
        const itemValue = enumOptionValueEncoder(enumValue, index, optionValueFormat)
        const itemDisabled = Array.isArray(enumDisabled) && enumDisabled.includes(enumValue)
        return (
          <div key={itemValue} className="flex items-center gap-2">
            <Radio.Root
              id={optionId(id, index)}
              value={itemValue}
              disabled={itemDisabled}
              className="focus-visible:ring-ring/50 border-border/60 data-checked:border-primary data-checked:ring-primary/40 h-4 w-4 cursor-pointer rounded-full border transition-all focus-visible:ring-2 focus-visible:outline-none data-checked:ring-2"
            >
              <Radio.Indicator className="bg-primary m-0.5 block h-2.5 w-2.5 rounded-full" />
            </Radio.Root>
            <Label
              className="text-foreground cursor-pointer leading-tight"
              htmlFor={optionId(id, index)}
            >
              {enumLabel}
            </Label>
          </div>
        )
      })}
    </RadioGroup>
  )
}

export default RadioWidget
