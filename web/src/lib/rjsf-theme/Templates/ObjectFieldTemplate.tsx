/**
 * ObjectFieldTemplate: renders each config object as a group card with a
 * heading, mirroring the previous schema-driven group UI.
 *
 * - The root object (the section itself) renders a card titled from
 *   ``formContext.rootLabel`` (humanized section name: "Core" / "Repo" …).
 * - Nested objects (github / analysis / …) render cards titled from
 *   ``formContext.groupLabels`` (humanized property name) — the old adapter's
 *   label scheme.
 * - Objects inside array items (notification.channels[0], repos[0]) render
 *   bare (the ArrayFieldItemTemplate provides the card).
 */

import { Plus } from 'lucide-react'
import type { ObjectFieldTemplateProps } from '@rjsf/utils'
import { buttonId, canExpand } from '@rjsf/utils'
import { Button } from '@/components/ui/Button'
import { Card, CardContent } from '@/components/ui/Card'
import { cn } from '@/lib/utils'

interface ConfigFormContext {
  rootLabel?: string
  groupLabels?: Record<string, string>
}

export function ObjectFieldTemplate(props: ObjectFieldTemplateProps) {
  const {
    title,
    properties,
    required,
    uiSchema,
    fieldPathId,
    schema,
    formData,
    disabled,
    readonly,
    registry,
    onAddProperty,
  } = props

  const name = fieldPathId.path[fieldPathId.path.length - 1] as string | undefined
  const isArrayItem = fieldPathId.path.some((p) => typeof p === 'number')
  const formContext = (registry.formContext ?? {}) as ConfigFormContext

  const heading =
    formContext.groupLabels?.[name ?? ''] ??
    (name === undefined ? formContext.rootLabel : prettifyTitle(title))

  const body = (
    <>
      {properties.map((element) => (
        <div key={element.name} className={cn(element.hidden && 'hidden')}>
          {element.content}
        </div>
      ))}
      {canExpand(schema, uiSchema, formData) && (
        <div className="mt-2 flex justify-end">
          <Button
            type="button"
            id={buttonId(fieldPathId, 'add')}
            variant="outline"
            size="sm"
            onClick={onAddProperty}
            disabled={disabled || readonly}
          >
            <Plus className="h-4 w-4" />
            Add
          </Button>
        </div>
      )}
    </>
  )

  if (isArrayItem) {
    return <div className="space-y-3">{body}</div>
  }

  return (
    <section className="scroll-mt-20">
      {heading && (
        <h2 className="text-foreground mb-4 text-xl font-bold">
          {heading}
          {required && <span className="text-destructive ml-1">*</span>}
        </h2>
      )}
      <Card>
        <CardContent className="space-y-6 pt-6">{body}</CardContent>
      </Card>
    </section>
  )
}

function prettifyTitle(title?: string): string {
  if (!title) return 'Item'
  return title.replace(/Config$/, '').trim()
}

export default ObjectFieldTemplate
