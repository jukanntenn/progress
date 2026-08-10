/**
 * FieldHelpTemplate: help text under a field.
 */

import type { FieldHelpProps } from '@rjsf/utils'

export function FieldHelpTemplate(props: FieldHelpProps) {
  const { fieldPathId, help } = props
  if (!help) return null
  return (
    <p
      id={`${fieldPathId.$id}__help`}
      className="text-muted-foreground mt-1 text-xs leading-relaxed"
    >
      {help}
    </p>
  )
}

export default FieldHelpTemplate
