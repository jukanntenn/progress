import { describe, expect, it } from 'vitest'
import { adaptSectionSchema, buildItemDefault, buildVariantDefault } from './schemaAdapter'
import type { FieldSchema, FieldGroup } from './schemaAdapter'

describe('adaptSectionSchema', () => {
  it('expands object sub-schemas into separate groups', () => {
    const schema = {
      $schema: 'https://json-schema.org/draft/2020-12/schema',
      type: 'object',
      properties: {
        language: { type: 'string', title: 'Language', default: 'en' },
        timezone: { type: 'string', title: 'Timezone', default: 'UTC' },
        analysis: {
          type: 'object',
          title: 'Analysis',
          properties: {
            model: { type: 'string', title: 'Model' },
            concurrency: { type: 'integer', minimum: 1, default: 1 },
            api_key: { type: 'string', writeOnly: true },
          },
          required: ['model'],
        },
      },
      required: ['language'],
    }

    const groups = adaptSectionSchema('core', schema)
    // standalone scalars land in a synthetic _general group; object sub-schemas
    // each become their own group.
    const analysis = groups.find((g) => g.name === 'analysis')
    expect(analysis).toBeDefined()
    if (!analysis) return
    expect(analysis.label).toBe('Analysis')
    const fieldsByPath = Object.fromEntries(analysis.fields.map((f) => [f.path, f])) as Record<
      string,
      { type: string; required?: boolean; min?: number }
    >
    expect(fieldsByPath.model?.type).toBe('text')
    expect(fieldsByPath.model?.required).toBe(true)
    expect(fieldsByPath.concurrency?.type).toBe('number')
    expect(fieldsByPath.concurrency?.min).toBe(1)
    expect(fieldsByPath.api_key?.type).toBe('password')

    // standalone scalars (language/timezone) land in a synthetic _general group
    expect(groups.length).toBeGreaterThanOrEqual(1)
  })

  it('detects timezone fields by key', () => {
    const groups = adaptSectionSchema('core', {
      type: 'object',
      properties: { timezone: { type: 'string', title: 'Timezone', default: 'UTC' } },
    })
    const group = groups[0] as FieldGroup
    const tz = group.fields[0] as FieldSchema
    expect(tz.type).toBe('timezone')
  })

  it('treats a plain array of objects as an object_list', () => {
    const groups = adaptSectionSchema('repo', {
      type: 'object',
      properties: {
        repos: {
          type: 'array',
          items: {
            type: 'object',
            properties: {
              url: { type: 'string', title: 'Url' },
              enabled: { type: 'boolean', default: true },
            },
          },
        },
      },
    })
    const group = groups[0] as FieldGroup
    const field = group.fields[0] as FieldSchema
    expect(field.type).toBe('object_list')
    if (field.type === 'object_list') {
      expect(field.item_label).toBe('Repo')
      expect(field.item_fields.length).toBe(2)
    }
  })

  it('detects discriminated unions keyed by type', () => {
    const schema = {
      $schema: 'https://json-schema.org/draft/2020-12/schema',
      type: 'object',
      $defs: {
        ConsoleConfig: {
          type: 'object',
          properties: { type: { const: 'console' }, enabled: { type: 'boolean' } },
        },
        EmailConfig: {
          type: 'object',
          properties: { type: { const: 'email' }, host: { type: 'string' } },
        },
      },
      properties: {
        channels: {
          type: 'array',
          items: {
            discriminator: { propertyName: 'type' },
            oneOf: [{ $ref: '#/$defs/EmailConfig' }, { $ref: '#/$defs/ConsoleConfig' }],
          },
        },
      },
    }

    const groups = adaptSectionSchema('core', schema)
    const group = groups[0] as FieldGroup
    const field = group.fields[0] as FieldSchema
    expect(field.type).toBe('discriminated_object_list')
    if (field.type === 'discriminated_object_list') {
      expect(field.discriminator).toBe('type')
      const variantNames = field.variants.map((v) => v.name).sort()
      expect(variantNames).toEqual(['console', 'email'])
    }
  })

  it('skips state_home (Ansible-owned, read-only)', () => {
    const groups = adaptSectionSchema('core', {
      type: 'object',
      properties: { state_home: { type: 'string' }, language: { type: 'string' } },
    })
    const paths = groups.flatMap((g) => g.fields.map((f) => f.path))
    expect(paths).not.toContain('state_home')
  })
})

describe('default builders', () => {
  it('buildItemDefault fills scalar defaults', () => {
    const item = buildItemDefault([
      {
        type: 'text',
        path: 'url',
        label: 'Url',
        help_text: null,
        required: false,
        default: 'https://example.com',
      },
      { type: 'boolean', path: 'enabled', label: 'Enabled', help_text: null, required: false },
    ])
    expect(item).toEqual({ url: 'https://example.com', enabled: false })
  })

  it('buildVariantDefault stamps the discriminator', () => {
    const item = buildVariantDefault('type', 'email', [
      { type: 'text', path: 'host', label: 'Host', help_text: null, required: false },
    ])
    expect(item).toEqual({ host: '', type: 'email' })
  })
})
