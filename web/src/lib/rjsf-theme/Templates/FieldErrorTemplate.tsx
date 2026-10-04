/**
 * FieldErrorTemplate: per-field validation errors.
 */

import type { FieldErrorProps } from '@rjsf/utils'

export function FieldErrorTemplate(props: FieldErrorProps) {
  const { errors, fieldPathId } = props
  if (!errors || errors.length === 0) return null
  return (
    <ul id={`${fieldPathId.$id}__error`} className="text-destructive mt-1 space-y-0.5 text-xs">
      {errors.map((error, i) => (
        <li key={i}>{error}</li>
      ))}
    </ul>
  )
}

export default FieldErrorTemplate
