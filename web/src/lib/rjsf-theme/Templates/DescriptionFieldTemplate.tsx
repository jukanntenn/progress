/**
 * DescriptionFieldTemplate: muted helper text under group headings.
 */

import type { DescriptionFieldProps } from '@rjsf/utils'

export function DescriptionFieldTemplate(props: DescriptionFieldProps) {
  const { id, description } = props
  if (!description) return null
  return (
    <p id={id} className="text-muted-foreground text-xs leading-relaxed">
      {description}
    </p>
  )
}

export default DescriptionFieldTemplate
