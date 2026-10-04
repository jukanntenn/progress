/**
 * ArrayFieldItemTemplate: one card per list item (channel / repo / tracker),
 * with the item index header and the move-up / move-down / remove toolbar,
 * mirroring the previous object-list card UI.
 */

import type { ArrayFieldItemTemplateProps } from '@rjsf/utils'
import { getTemplate, getUiOptions } from '@rjsf/utils'
import { Card, CardContent, CardHeader } from '@/components/ui/Card'

export function ArrayFieldItemTemplate(props: ArrayFieldItemTemplateProps) {
  const { children, index, hasToolbar, buttonsProps, uiSchema, schema, registry } = props
  const uiOptions = getUiOptions(uiSchema)
  const ArrayFieldItemButtonsTemplate = getTemplate<'ArrayFieldItemButtonsTemplate'>(
    'ArrayFieldItemButtonsTemplate',
    registry,
    uiOptions,
  )
  const title = uiOptions.title || schema.title || 'Item'
  const itemLabel = title.replace(/s$/, '')

  return (
    <Card>
      <CardHeader className="flex flex-row items-center justify-between gap-2 pb-2">
        <span className="text-foreground text-sm font-medium">
          {itemLabel} #{index + 1}
        </span>
        {hasToolbar && <ArrayFieldItemButtonsTemplate {...buttonsProps} />}
      </CardHeader>
      <CardContent className="space-y-4 pt-0">{children}</CardContent>
    </Card>
  )
}

export default ArrayFieldItemTemplate
