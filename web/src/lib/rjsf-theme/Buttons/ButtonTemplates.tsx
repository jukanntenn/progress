/**
 * ButtonTemplates: RJSF array/object item buttons (add / move / remove) and
 * the form submit button. The submit button is hidden (norender) — saving is
 * driven by the page header's Save button, which calls ``Form.submit()``.
 */

import { ArrowDown, ArrowUp, Plus, Trash2 } from 'lucide-react'
import type { IconButtonProps, SubmitButtonProps } from '@rjsf/utils'
import { getSubmitButtonOptions } from '@rjsf/utils'
import { Button } from '@/components/ui/Button'
import { useTranslation } from 'react-i18next'

export function SubmitButton(props: SubmitButtonProps) {
  const { uiSchema } = props
  const { norender } = getSubmitButtonOptions(uiSchema)
  if (norender) return null
  return null
}

export function AddButton(props: IconButtonProps) {
  const { t } = useTranslation()
  const { id, disabled, onClick } = props
  return (
    <Button id={id} type="button" variant="outline" size="sm" disabled={disabled} onClick={onClick}>
      <Plus className="h-4 w-4" />
      {t('config.addItem', { item: '' })}
    </Button>
  )
}

export function RemoveButton(props: IconButtonProps) {
  const { id, disabled, onClick } = props
  return (
    <Button
      id={id}
      type="button"
      variant="ghost"
      size="icon-sm"
      aria-label="Remove"
      disabled={disabled}
      onClick={onClick}
      className="text-muted-foreground hover:text-destructive"
    >
      <Trash2 className="h-4 w-4" />
    </Button>
  )
}

export function MoveUpButton(props: IconButtonProps) {
  const { id, disabled, onClick } = props
  return (
    <Button
      id={id}
      type="button"
      variant="ghost"
      size="icon-sm"
      aria-label="Move up"
      disabled={disabled}
      onClick={onClick}
      className="text-muted-foreground"
    >
      <ArrowUp className="h-4 w-4" />
    </Button>
  )
}

export function MoveDownButton(props: IconButtonProps) {
  const { id, disabled, onClick } = props
  return (
    <Button
      id={id}
      type="button"
      variant="ghost"
      size="icon-sm"
      aria-label="Move down"
      disabled={disabled}
      onClick={onClick}
      className="text-muted-foreground"
    >
      <ArrowDown className="h-4 w-4" />
    </Button>
  )
}

// eslint-disable-next-line react-refresh/only-export-components
export const ButtonTemplates = {
  SubmitButton,
  AddButton,
  RemoveButton,
  MoveUpButton,
  MoveDownButton,
}

export default ButtonTemplates
