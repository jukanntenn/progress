/**
 * ArrayFieldTemplate: container for list fields (notification.channels,
 * repo.repos, changelog.trackers, …). Renders the field title + description
 * above the items and an "Add" button at the bottom.
 */

import type { ArrayFieldTemplateProps } from '@rjsf/utils'
import { buttonId, getTemplate, getUiOptions } from '@rjsf/utils'

export function ArrayFieldTemplate(props: ArrayFieldTemplateProps) {
  const {
    canAdd,
    disabled,
    fieldPathId,
    uiSchema,
    items,
    onAddClick,
    readonly,
    required,
    schema,
    title,
    registry,
  } = props
  const uiOptions = getUiOptions(uiSchema)
  const ArrayFieldTitleTemplate = getTemplate<'ArrayFieldTitleTemplate'>(
    'ArrayFieldTitleTemplate',
    registry,
    uiOptions,
  )
  const ArrayFieldDescriptionTemplate = getTemplate<'ArrayFieldDescriptionTemplate'>(
    'ArrayFieldDescriptionTemplate',
    registry,
    uiOptions,
  )
  const { AddButton } = registry.templates.ButtonTemplates

  return (
    <div className="space-y-3">
      <ArrayFieldTitleTemplate
        fieldPathId={fieldPathId}
        title={uiOptions.title || title || ''}
        schema={schema}
        uiSchema={uiSchema ?? {}}
        required={required ?? false}
        registry={registry}
      />
      <ArrayFieldDescriptionTemplate
        fieldPathId={fieldPathId}
        description={uiOptions.description || schema.description || ''}
        schema={schema}
        uiSchema={uiSchema ?? {}}
        registry={registry}
      />
      {items}
      {canAdd && (
        <div className="flex justify-end">
          <AddButton
            id={buttonId(fieldPathId, 'add')}
            onClick={onAddClick}
            disabled={disabled || readonly}
            uiSchema={uiSchema ?? {}}
            registry={registry}
          />
        </div>
      )}
    </div>
  )
}

export default ArrayFieldTemplate
