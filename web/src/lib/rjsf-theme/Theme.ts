/**
 * RJSF theme aggregate (spec 4.2): ``{ templates, widgets }``.
 */

import { generateTemplates } from './Templates/Templates'
import { generateWidgets } from './Widgets/Widgets'

export function generateTheme() {
  return {
    templates: generateTemplates(),
    widgets: generateWidgets(),
  }
}

export default generateTheme()
