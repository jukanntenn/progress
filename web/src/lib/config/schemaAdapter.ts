/**
 * Convert the Pydantic-generated JSON Schema (served by
 * ``GET /api/v1/config/schema``) into flat, render-oriented field descriptors
 * the config editor consumes. The JSON Schema is the single source of truth;
 * this adapter only reshapes it — no type information is hand-written.
 *
 * Field model (spec 13: schema-driven form via React Hook Form + Zod):
 * - ``text`` / ``password`` / ``number`` / ``boolean`` / ``select``
 * - ``timezone``  — a ``type:"string"`` field whose key/title implies a timezone
 * - ``object_list`` — array of homogeneous objects (e.g. ``repos``, ``owners``)
 * - ``discriminated_object_list`` — array whose items are a oneOf union keyed
 *   by a discriminator (e.g. ``notification.channels`` keyed by ``type``)
 */

export type FieldSchema =
  | {
      type: 'text'
      path: string
      label: string
      help_text: string | null
      required: boolean
      default?: unknown
    }
  | {
      type: 'password'
      path: string
      label: string
      help_text: string | null
      required: boolean
      default?: unknown
    }
  | {
      type: 'number'
      path: string
      label: string
      help_text: string | null
      required: boolean
      default?: unknown
      min?: number
      max?: number
    }
  | {
      type: 'boolean'
      path: string
      label: string
      help_text: string | null
      required: boolean
      default?: unknown
    }
  | {
      type: 'select'
      path: string
      label: string
      help_text: string | null
      required: boolean
      default?: unknown
      options: string[]
    }
  | {
      type: 'timezone'
      path: string
      label: string
      help_text: string | null
      required: boolean
      default?: unknown
    }
  | {
      type: 'object_list'
      path: string
      label: string
      help_text: string | null
      item_label: string
      item_fields: FieldSchema[]
    }
  | {
      type: 'discriminated_object_list'
      path: string
      label: string
      help_text: string | null
      item_label: string
      discriminator: string
      variants: { name: string; label: string; fields: FieldSchema[] }[]
    }

type SchemaNode = Record<string, unknown>

const TIMEZONE_KEYS = new Set(['timezone'])

function asNode(value: unknown): SchemaNode | undefined {
  return value && typeof value === 'object' ? (value as SchemaNode) : undefined
}

function resolveRef(node: unknown, root: SchemaNode): SchemaNode | undefined {
  const obj = asNode(node)
  if (!obj || !obj.$ref) return obj
  const parts = String(obj.$ref).replace(/^#\/?/, '').split('/')
  let cur: unknown = root
  for (const part of parts) cur = (asNode(cur) ?? {})[part]
  return asNode(cur) ?? obj
}

function unwrapAnyOf(node: unknown): SchemaNode | undefined {
  const obj = asNode(node)
  if (!obj || !Array.isArray(obj.anyOf)) return obj
  const nonNull = (obj.anyOf as SchemaNode[]).find((v) => v.type !== 'null')
  if (!nonNull) return obj
  const rest = Object.fromEntries(Object.entries(obj).filter(([key]) => key !== 'anyOf'))
  return { ...rest, ...nonNull }
}

function humanize(key: string): string {
  return key.replace(/_/g, ' ').replace(/\b\w/g, (c) => c.toUpperCase())
}

function buildScalar(name: string, node: SchemaNode, path: string, required: boolean): FieldSchema {
  const label = (node.title as string) || humanize(name)
  const help_text = (node.description as string) || null
  const def = node.default

  if (Array.isArray(node.enum)) {
    return {
      type: 'select',
      path,
      label,
      help_text,
      required,
      default: def,
      options: node.enum as string[],
    }
  }

  if (node.type === 'integer' || node.type === 'number') {
    const min = typeof node.minimum === 'number' ? node.minimum : undefined
    const max = typeof node.maximum === 'number' ? node.maximum : undefined
    return {
      type: 'number',
      path,
      label,
      help_text,
      required,
      default: def,
      ...(min !== undefined && { min }),
      ...(max !== undefined && { max }),
    }
  }

  if (node.type === 'boolean') {
    return { type: 'boolean', path, label, help_text, required, default: def }
  }

  if (node.writeOnly === true || node.format === 'password') {
    return { type: 'password', path, label, help_text, required, default: def }
  }

  if (TIMEZONE_KEYS.has(name)) {
    return { type: 'timezone', path, label, help_text, required, default: def }
  }

  return { type: 'text', path, label, help_text, required, default: def }
}

function defaultValue(field: FieldSchema): unknown {
  if (field.type === 'boolean') return field.default ?? false
  if (field.type === 'number') return field.default ?? 0
  if (field.type === 'object_list') return []
  if (field.type === 'discriminated_object_list') return []
  if (field.type === 'select') return field.default ?? field.options[0] ?? ''
  return field.default ?? ''
}

function objectFields(objNode: SchemaNode, root: SchemaNode): FieldSchema[] {
  const props = (objNode.properties ?? {}) as Record<string, unknown>
  const required = new Set((objNode.required ?? []) as string[])
  const fields: FieldSchema[] = []
  for (const [name, raw] of Object.entries(props)) {
    if (name === 'type') continue
    const resolved = unwrapAnyOf(resolveRef(raw, root))
    if (!resolved) continue
    fields.push(buildField(name, resolved, name, required.has(name), root))
  }
  return fields
}

function buildField(
  name: string,
  node: SchemaNode,
  path: string,
  required: boolean,
  root: SchemaNode,
): FieldSchema {
  const label = (node.title as string) || humanize(name)
  const help_text = (node.description as string) || null

  if (node.type === 'array') {
    const items = asNode(node.items) ?? {}
    const discriminator = items.discriminator as
      { propertyName: string; mapping?: Record<string, string> } | undefined
    if (discriminator && Array.isArray(items.oneOf)) {
      const variants = (items.oneOf as SchemaNode[])
        .map((branch) => {
          const resolved = resolveRef(branch, root)
          if (!resolved) return null
          const props = asNode(resolved.properties) ?? {}
          const typeField = asNode(props.type) ?? {}
          const variantName = (typeField.const as string) ?? humanize(name)
          return {
            name: variantName,
            label: variantName.charAt(0).toUpperCase() + variantName.slice(1),
            fields: objectFields(resolved, root),
          }
        })
        .filter((v): v is { name: string; label: string; fields: FieldSchema[] } => v !== null)
      return {
        type: 'discriminated_object_list',
        path,
        label,
        help_text,
        item_label: humanize(name).replace(/s$/, ''),
        discriminator: discriminator.propertyName,
        variants,
      }
    }
    const itemNode = resolveRef(items, root) ?? items
    return {
      type: 'object_list',
      path,
      label,
      help_text,
      item_label: humanize(name).replace(/s$/, ''),
      item_fields: objectFields(itemNode, root),
    }
  }

  if (node.type === 'object') {
    return {
      type: 'object_list',
      path,
      label,
      help_text,
      item_label: humanize(name).replace(/s$/, ''),
      item_fields: objectFields(node, root),
    }
  }

  return buildScalar(name, node, path, required)
}

/**
 * Flatten a section's JSON Schema into render fields.
 *
 * Object-typed sub-schemas (e.g. ``core.github``, ``core.analysis``) are
 * expanded into their own field group so the form shows nested sections.
 */
export interface FieldGroup {
  name: string
  label: string
  fields: FieldSchema[]
}

/** Pick a human-friendly label for a sub-object group.
 *
 * Pydantic emits the model class name as JSON Schema ``title`` (e.g.
 * ``"GitHubConfig"``), which is ugly in a nav. Prefer the property key
 * humanized ("github" → "Github") unless the title is clearly a real
 * human-written label (has spaces / is not PascalCase). */
function friendlyGroupLabel(name: string, title: string | undefined): string {
  if (title && /\s/.test(title)) return title
  return humanize(name)
}

export function adaptSectionSchema(sectionName: string, schema: SchemaNode): FieldGroup[] {
  const props = (schema.properties ?? {}) as Record<string, unknown>
  const required = new Set((schema.required ?? []) as string[])
  const groups: FieldGroup[] = []

  for (const [name, raw] of Object.entries(props)) {
    if (name === 'state_home') continue
    const node = unwrapAnyOf(resolveRef(raw, schema)) ?? {}
    if (node.type === 'object') {
      groups.push({
        name,
        label: friendlyGroupLabel(name, node.title as string | undefined),
        fields: objectFields(node, schema),
      })
    } else {
      const standalone = buildField(name, node, name, required.has(name), schema)
      if (!groups.length)
        groups.push({ name: '_general', label: humanize(sectionName), fields: [] })
      const general = groups[0] as FieldGroup
      general.fields.push(standalone)
    }
  }

  return groups.filter((g) => g.fields.length > 0)
}

/** Build a fresh default value object for a variant (used by "add item"). */
export function buildVariantDefault(
  discriminator: string,
  variant: string,
  fields: FieldSchema[],
): Record<string, unknown> {
  const item: Record<string, unknown> = {}
  for (const f of fields) item[f.path] = defaultValue(f)
  item[discriminator] = variant
  return item
}

/** Build a fresh default value object for an object_list item. */
export function buildItemDefault(fields: FieldSchema[]): Record<string, unknown> {
  const item: Record<string, unknown> = {}
  for (const f of fields) item[f.path] = defaultValue(f)
  return item
}
