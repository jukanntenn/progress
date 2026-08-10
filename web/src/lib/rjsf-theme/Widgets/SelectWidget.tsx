/**
 * SelectWidget: enum single-select (base-ui Select) + multi-select fallback
 * (native <select multiple>, since base-ui Select has no multiple mode).
 */

import { Select } from '@base-ui/react/select'
import { Check, ChevronDown } from 'lucide-react'
import type { WidgetProps } from '@rjsf/utils'
import {
  ariaDescribedByIds,
  enumOptionSelectedValue,
  enumOptionValueDecoder,
  enumOptionValueEncoder,
  getOptionValueFormat,
} from '@rjsf/utils'
import { cn } from '@/lib/utils'

export function SelectWidget(props: WidgetProps) {
  const {
    id,
    options,
    required,
    disabled,
    readonly,
    value,
    multiple,
    autofocus,
    onChange,
    onBlur,
    onFocus,
    placeholder,
    rawErrors = [],
    className,
  } = props
  const { enumOptions, enumDisabled, emptyValue: optEmptyValue } = options
  const optionValueFormat = getOptionValueFormat(options)
  const items =
    enumOptions?.map(({ value: enumValue, label: enumLabel }, index: number) => ({
      value: multiple
        ? String(enumValue)
        : enumOptionValueEncoder(enumValue, index, optionValueFormat),
      label: enumLabel,
      disabled: Array.isArray(enumDisabled) && enumDisabled.includes(enumValue),
    })) ?? []

  const errorClasses = rawErrors.length > 0 ? 'border-error/50' : ''
  const baseClasses = cn(className, errorClasses)

  if (multiple) {
    return (
      <select
        id={id}
        multiple
        autoFocus={autofocus}
        disabled={disabled || readonly}
        required={required}
        className={cn(
          'glass-input flex min-h-[40px] w-full rounded-md px-3 py-2 text-sm',
          'focus-visible:ring-ring/50 focus-visible:border-ring/50 focus-visible:ring-2 focus-visible:outline-none',
          'disabled:cursor-not-allowed disabled:opacity-50',
          baseClasses,
        )}
        value={Array.isArray(value) ? value.map(String) : []}
        onChange={(e) =>
          onChange(
            enumOptionValueDecoder(
              Array.from(e.target.selectedOptions, (o) => o.value),
              enumOptions,
              optionValueFormat,
              optEmptyValue,
            ),
          )
        }
        onBlur={() => onBlur(id, value)}
        onFocus={() => onFocus(id, value)}
        aria-describedby={ariaDescribedByIds(id)}
      >
        {items.map((item) => (
          <option key={item.value} value={item.value} disabled={item.disabled}>
            {item.label}
          </option>
        ))}
      </select>
    )
  }

  const selected = enumOptionSelectedValue(value, enumOptions, false, optionValueFormat, '')
  const selectedKey =
    selected === '' || selected === undefined || selected === null ? '' : String(selected)
  const openItem = items.find((item) => item.value === selectedKey)

  return (
    <Select.Root
      value={selectedKey}
      onValueChange={(next) => {
        onChange(enumOptionValueDecoder(next ?? '', enumOptions, optionValueFormat, optEmptyValue))
      }}
      disabled={disabled || readonly}
    >
      <Select.Trigger
        id={id}
        className={cn(
          'glass-input flex h-10 w-full cursor-pointer items-center justify-between gap-2 rounded-md px-3 py-2 text-sm',
          'ring-offset-background',
          'transition-all duration-200 ease-out',
          'hover:border-ring/40',
          'focus-visible:ring-ring/50 focus-visible:border-ring/50 focus-visible:ring-2 focus-visible:outline-none',
          'disabled:cursor-not-allowed disabled:opacity-50',
          'data-popup-open:border-ring/50 data-popup-open:ring-ring/50 data-popup-open:ring-2',
          baseClasses,
        )}
        aria-describedby={ariaDescribedByIds(id)}
      >
        <Select.Value className="data-placeholder:text-muted-foreground text-foreground truncate">
          {placeholder || openItem?.label || ''}
        </Select.Value>
        <Select.Icon>
          <ChevronDown className="text-muted-foreground h-4 w-4" />
        </Select.Icon>
      </Select.Trigger>
      <Select.Portal>
        <Select.Positioner className="z-50" sideOffset={4}>
          <Select.Popup className="glass-modal shadow-glass-elevated min-w-[var(--anchor-width)] rounded-md py-1">
            <Select.List className="max-h-[var(--available-height)] overflow-y-auto py-0.5">
              {items.map((item) => (
                <Select.Item
                  key={item.value}
                  value={item.value}
                  className="text-foreground data-highlighted:bg-accent/60 grid cursor-pointer grid-cols-[1rem_1fr] items-center gap-2 py-1.5 pr-3 pl-2.5 text-sm outline-none select-none data-disabled:cursor-not-allowed data-disabled:opacity-50"
                >
                  <Select.ItemIndicator className="col-start-1">
                    <Check className="h-3.5 w-3.5" />
                  </Select.ItemIndicator>
                  <Select.ItemText className="col-start-2">{item.label}</Select.ItemText>
                </Select.Item>
              ))}
            </Select.List>
          </Select.Popup>
        </Select.Positioner>
      </Select.Portal>
    </Select.Root>
  )
}

export default SelectWidget
