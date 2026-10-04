/**
 * ConfigForm: RJSF <Form> wrapper for one config section.
 *
 * - Renders the section schema with the base-ui theme + AJV8 validator.
 * - Builds the uiSchema: ``ui:emptyValue: ""`` on every ``format: password``
 *   field (spec 7.2), and hides the built-in submit button (the page header's
 *   Save button drives ``Form.submit()``).
 * - Computes group labels (root + nested objects) from the schema for the
 *   ObjectFieldTemplate cards (spec 4.4 layout).
 * - Exposes ``liveData`` via onChange so the page can compute dirty state
 *   against the initial (default-merged) data (spec 4.9).
 * - Accepts ``extraErrors`` (parsed backend 422) to surface server-side
 *   validation at field level (spec 4.10).
 */

import { forwardRef, useMemo } from 'react'
import Form, { withTheme } from '@rjsf/core'
import type { IChangeEvent } from '@rjsf/core'
import type { RJSFSchema, RJSFValidationError, UiSchema } from '@rjsf/utils'
import validator from '@rjsf/validator-ajv8'
import { generateTheme } from '@/lib/rjsf-theme'

const ThemedForm = withTheme(generateTheme())

export interface ConfigFormProps {
  sectionName: string
  schema: RJSFSchema
  formData: Record<string, unknown>
  extraErrors?: Record<string, unknown>
  onChange: (data: Record<string, unknown>) => void
  onSubmit: (data: Record<string, unknown>) => void
  onError?: (errors: RJSFValidationError[]) => void
}

function humanize(key: string): string {
  return key.replace(/_/g, ' ').replace(/\b\w/g, (c) => c.toUpperCase())
}

function resolveLocalRef(node: RJSFSchema | undefined, root: RJSFSchema): RJSFSchema | undefined {
  const ref = node?.$ref
  if (typeof ref !== 'string' || !ref.startsWith('#/')) return node
  let cursor: unknown = root
  for (const part of ref.slice(2).split('/')) {
    if (cursor && typeof cursor === 'object') {
      cursor = (cursor as Record<string, unknown>)[part]
    } else {
      return undefined
    }
  }
  return (cursor as RJSFSchema) ?? undefined
}

/**
 * Walk the (ref-resolved) schema, setting ``ui:emptyValue: ''`` on every
 * ``format: password`` leaf. uiSchema paths follow property names only —
 * array items nest under ``items``, oneOf members keep the item path.
 */
function buildUiSchema(schema: RJSFSchema): UiSchema {
  const uiSchema: UiSchema = {}

  const setAtPath = (path: string[], value: Record<string, unknown>) => {
    let cursor: UiSchema = uiSchema
    for (const segment of path) {
      const next = cursor[segment]
      if (typeof next !== 'object' || next === null) {
        cursor[segment] = {}
      }
      cursor = cursor[segment] as UiSchema
    }
    Object.assign(cursor, value)
  }

  const walk = (node: RJSFSchema | undefined, path: string[]) => {
    const resolved = resolveLocalRef(node, schema)
    if (!resolved || typeof resolved !== 'object') return
    if (resolved.format === 'password') {
      setAtPath(path, { 'ui:emptyValue': '' })
    }
    if (resolved.type === 'array') {
      const propName = path[path.length - 1] as string | undefined
      if (propName) {
        const singular = humanize(propName).replace(/s$/, '')
        // label:false hides the redundant item label (the raw oneOf item
        // schema has no type, so RJSF's getDisplayLabel wrongly defaults true)
        setAtPath([...path, 'items'], { 'ui:title': singular, 'ui:options': { label: false } })
      }
    }
    if (Array.isArray(resolved.oneOf)) {
      const discriminator = ((resolved.discriminator as { propertyName?: string } | undefined)
        ?.propertyName ?? 'type') as string
      const labels = resolved.oneOf.map((member) => {
        const memberSchema = resolveLocalRef(member as RJSFSchema, schema)
        const constSchema = memberSchema?.properties?.[discriminator]
        const constValue =
          constSchema && typeof constSchema === 'object' ? constSchema.const : undefined
        if (typeof constValue === 'string') return { 'ui:title': humanize(constValue) }
        const memberTitle = memberSchema?.title
        return {
          'ui:title':
            typeof memberTitle === 'string'
              ? humanize(memberTitle.replace(/(Integration)?Config$/, ''))
              : '',
        }
      })
      setAtPath(path, { oneOf: labels })
    }
    if (resolved.properties && typeof resolved.properties === 'object') {
      for (const [key, child] of Object.entries(resolved.properties)) {
        walk(child as RJSFSchema, [...path, key])
      }
    }
    const items = resolved.items
    if (items && typeof items === 'object' && !Array.isArray(items)) {
      walk(items as RJSFSchema, [...path, 'items'])
    }
    if (Array.isArray(resolved.oneOf)) {
      for (const member of resolved.oneOf) {
        walk(member as RJSFSchema, path)
      }
    }
  }

  walk(schema, [])
  return uiSchema
}

function groupLabelFromTitle(title: string | undefined, fallback: string): string {
  if (!title) return humanize(fallback)
  return humanize(title.replace(/(Integration)?Config$/, ''))
}

function buildGroupLabels(
  sectionName: string,
  schema: RJSFSchema,
): {
  rootLabel: string
  groupLabels: Record<string, string>
} {
  const groupLabels: Record<string, string> = {}
  for (const [name, raw] of Object.entries(schema.properties ?? {})) {
    const resolved = resolveLocalRef(raw as RJSFSchema, schema)
    if (resolved?.type === 'object' || resolved?.properties) {
      groupLabels[name] = groupLabelFromTitle(resolved.title, name)
    }
  }
  return { rootLabel: humanize(sectionName), groupLabels }
}

export const ConfigForm = forwardRef<Form, ConfigFormProps>(function ConfigForm(
  { sectionName, schema, formData, extraErrors, onChange, onSubmit, onError },
  ref,
) {
  const uiSchema = useMemo(() => buildUiSchema(schema), [schema])
  const formContext = useMemo(() => buildGroupLabels(sectionName, schema), [sectionName, schema])

  return (
    <ThemedForm
      schema={schema}
      uiSchema={{ ...uiSchema, 'ui:submitButtonOptions': { norender: true } }}
      validator={validator}
      formData={formData}
      formContext={formContext}
      extraErrors={extraErrors as never}
      onChange={(e: IChangeEvent) => onChange((e.formData ?? {}) as Record<string, unknown>)}
      onSubmit={(e: IChangeEvent) => onSubmit((e.formData ?? {}) as Record<string, unknown>)}
      onError={onError ?? (() => undefined)}
      showErrorList={false}
      ref={ref}
    />
  )
})

export default ConfigForm
