/**
 * RJSF base-ui theme templates.
 */

import { BaseInputTemplate } from './BaseInputTemplate'
import { FieldTemplate } from './FieldTemplate'
import { ObjectFieldTemplate } from './ObjectFieldTemplate'
import { ArrayFieldTemplate } from './ArrayFieldTemplate'
import { ArrayFieldItemTemplate } from './ArrayFieldItemTemplate'
import { TitleFieldTemplate } from './TitleFieldTemplate'
import { DescriptionFieldTemplate } from './DescriptionFieldTemplate'
import { FieldErrorTemplate } from './FieldErrorTemplate'
import { FieldHelpTemplate } from './FieldHelpTemplate'
import { ErrorListTemplate } from './ErrorListTemplate'
import { ButtonTemplates } from '../Buttons/ButtonTemplates'

export function generateTemplates() {
  return {
    BaseInputTemplate,
    FieldTemplate,
    ObjectFieldTemplate,
    ArrayFieldTemplate,
    ArrayFieldItemTemplate,
    TitleFieldTemplate,
    DescriptionFieldTemplate,
    FieldErrorTemplate,
    FieldHelpTemplate,
    ErrorListTemplate,
    ButtonTemplates,
  }
}

export default generateTemplates()
