/**
 * RJSF base-ui theme widgets.
 *
 * 6 widgets per the config-system redesign spec 4.2, plus the password widget
 * (format:"password" → PasswordWidget with the eye toggle) wired through the
 * theme so every SecretStr field gets browser-native masking + reveal.
 */

import { WidgetProps } from '@rjsf/utils'

import { SelectWidget } from './SelectWidget'
import { CheckboxWidget } from './CheckboxWidget'
import { CheckboxesWidget } from './CheckboxesWidget'
import { RadioWidget } from './RadioWidget'
import { RangeWidget } from './RangeWidget'
import { TextareaWidget } from './TextareaWidget'
import { PasswordWidget } from '@/components/config/PasswordWidget'

export {
  SelectWidget,
  CheckboxWidget,
  CheckboxesWidget,
  RadioWidget,
  RangeWidget,
  TextareaWidget,
  PasswordWidget,
}

export function generateWidgets(): Record<string, (props: WidgetProps) => React.ReactNode> {
  return {
    SelectWidget,
    CheckboxWidget,
    CheckboxesWidget,
    RadioWidget,
    RangeWidget,
    TextareaWidget,
    password: PasswordWidget,
  }
}

export default generateWidgets()
