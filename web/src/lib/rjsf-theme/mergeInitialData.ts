/**
 * Default-merge server config data against its JSON Schema so the form's
 * initial formData and the dirty baseline are identical. RJSF fills schema
 * defaults into missing keys; comparing raw GET data against merged formData
 * would falsely flag "unsaved changes" on load (spec 4.9, decision D3).
 */

import type { RJSFSchema } from '@rjsf/utils'
import { getDefaultFormState } from '@rjsf/utils'
import validator from '@rjsf/validator-ajv8'

export function mergeInitialData(
  schema: RJSFSchema,
  data: Record<string, unknown>,
): Record<string, unknown> {
  return getDefaultFormState(validator, schema, data, schema) as Record<string, unknown>
}
