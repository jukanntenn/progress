/**
 * RJSF base-ui theme: { templates, widgets } aggregate consumed by
 * ``withTheme`` — the config editor renders every section through this.
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
