/**
 * RangeWidget: number fields rendered as a base-ui slider.
 */

import { Slider } from '@base-ui/react/slider'
import type { WidgetProps } from '@rjsf/utils'
import { ariaDescribedByIds } from '@rjsf/utils'
import { cn } from '@/lib/utils'

export function RangeWidget(props: WidgetProps) {
  const { id, value, disabled, readonly, schema, onChange, onBlur, rawErrors = [] } = props
  const min = typeof schema.minimum === 'number' ? schema.minimum : 0
  const max = typeof schema.maximum === 'number' ? schema.maximum : 100
  const step = typeof schema.multipleOf === 'number' ? schema.multipleOf : 1

  return (
    <div className="flex items-center gap-3">
      <Slider.Root
        className="flex w-full items-center"
        min={min}
        max={max}
        step={step}
        value={typeof value === 'number' ? value : min}
        onValueChange={(next: number | number[]) => {
          onChange(Array.isArray(next) ? next[0] : next)
        }}
        onValueCommitted={() => onBlur(id, value)}
        disabled={disabled || readonly}
        aria-describedby={ariaDescribedByIds(id)}
      >
        <Slider.Track
          className={cn(
            'bg-border/60 relative h-1.5 w-full rounded-full',
            rawErrors.length > 0 && 'bg-error/30',
          )}
        >
          <Slider.Indicator className="bg-primary absolute rounded-full" />
          <Slider.Thumb className="bg-primary border-background focus-visible:ring-ring/50 block h-4 w-4 cursor-grab rounded-full border-2 shadow-sm transition-transform focus-visible:ring-2 focus-visible:outline-none active:cursor-grabbing" />
        </Slider.Track>
      </Slider.Root>
      <span className="text-muted-foreground min-w-10 text-right text-sm tabular-nums">
        {typeof value === 'number' ? value : min}
      </span>
    </div>
  )
}

export default RangeWidget
