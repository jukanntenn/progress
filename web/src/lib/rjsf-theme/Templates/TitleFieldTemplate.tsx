/**
 * TitleFieldTemplate: heading for object/array groups (rendered by
 * ArrayFieldTemplate; ObjectFieldTemplate draws its own card headings).
 */

import type { TitleFieldProps } from '@rjsf/utils'

export function TitleFieldTemplate(props: TitleFieldProps) {
  const { id, title } = props
  if (!title) return null
  return (
    <h3 id={id} className="text-foreground text-sm font-semibold">
      {title}
    </h3>
  )
}

export default TitleFieldTemplate
