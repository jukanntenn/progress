/**
 * Inline schema-driven config form renderer (spec 13: schema-driven form).
 *
 * Re-creates the pre-refactor UX: each section renders inline (no dialog),
 * with SimpleField / StringListField / ObjectListField /
 * DiscriminatedObjectListField dispatching on the field schema. Object lists
 * render one glass card per row with a responsive 2-column field grid, add and
 * remove per row, and (for discriminated lists) a variant selector that
 * rebuilds the row. State is mutated immutably via dot-path helpers so React
 * re-renders and JSON.stringify diffing both work.
 */

import { Plus, Trash2 } from 'lucide-react'
import { Button } from '@/components/ui/Button'
import { Card, CardContent, CardHeader } from '@/components/ui/Card'
import { Checkbox } from '@/components/ui/Checkbox'
import { Input } from '@/components/ui/Input'
import { Label } from '@/components/ui/Label'
import { Select } from '@/components/ui/Select'
import {
  buildItemDefault,
  buildVariantDefault,
  type FieldGroup,
  type FieldSchema,
} from '@/lib/config/schemaAdapter'

const COMMON_TIMEZONES = [
  'UTC',
  'Asia/Shanghai',
  'Asia/Singapore',
  'Asia/Tokyo',
  'Europe/London',
  'Europe/Paris',
  'America/New_York',
  'America/Los_Angeles',
]

function getAtPath(obj: unknown, path: string): unknown {
  return path.split('.').reduce<unknown>((acc, key) => {
    if (acc && typeof acc === 'object') return (acc as Record<string, unknown>)[key]
    return undefined
  }, obj)
}

function setAtPath(
  obj: Record<string, unknown>,
  path: string,
  value: unknown,
): Record<string, unknown> {
  const parts = path.split('.')
  const root: Record<string, unknown> = { ...obj }
  let cur: Record<string, unknown> = root
  for (let i = 0; i < parts.length - 1; i++) {
    const key = parts[i] as string
    const next = cur[key]
    const copy: Record<string, unknown> =
      next && typeof next === 'object' && !Array.isArray(next)
        ? { ...(next as Record<string, unknown>) }
        : {}
    cur[key] = copy
    cur = copy
  }
  cur[parts[parts.length - 1] as string] = value
  return root
}

function toBoolean(v: unknown): boolean {
  return v === true || v === 'true' || v === 1
}

function toNumber(v: unknown): number {
  if (typeof v === 'number') return v
  const n = Number(v)
  return Number.isFinite(n) ? n : 0
}

function ensureArray(v: unknown): unknown[] {
  return Array.isArray(v) ? v : []
}

function ensureObject(v: unknown): Record<string, unknown> {
  if (v && typeof v === 'object' && !Array.isArray(v)) return v as Record<string, unknown>
  return {}
}

function FieldHelp({ text }: { text: string | null }) {
  if (!text) return null
  return <p className="text-muted-foreground mt-1 text-xs">{text}</p>
}

function LabelText({ label, required }: { label: string; required?: boolean }) {
  return (
    <>
      {label}
      {required && <span className="text-destructive ml-1">*</span>}
    </>
  )
}

function SimpleField({
  field,
  value,
  onChange,
}: {
  field: Extract<
    FieldSchema,
    { type: 'text' | 'password' | 'number' | 'boolean' | 'select' | 'timezone' }
  >
  value: unknown
  onChange: (value: unknown) => void
}) {
  if (field.type === 'boolean') {
    return (
      <div className="flex items-center gap-2">
        <Checkbox checked={toBoolean(value)} onChange={(e) => onChange(e.currentTarget.checked)} />
        <span className="text-foreground text-sm">{field.label}</span>
      </div>
    )
  }

  if (field.type === 'select') {
    return (
      <div>
        <Label>
          <LabelText label={field.label} required={field.required} />
        </Label>
        <Select value={(value as string) ?? ''} onChange={(e) => onChange(e.target.value)}>
          <option value="" disabled>
            Select...
          </option>
          {field.options.map((opt) => (
            <option key={opt} value={opt}>
              {opt}
            </option>
          ))}
        </Select>
        <FieldHelp text={field.help_text} />
      </div>
    )
  }

  if (field.type === 'timezone') {
    return (
      <div>
        <Label>
          <LabelText label={field.label} required={field.required} />
        </Label>
        <Select value={(value as string) ?? 'UTC'} onChange={(e) => onChange(e.target.value)}>
          {COMMON_TIMEZONES.map((tz) => (
            <option key={tz} value={tz}>
              {tz}
            </option>
          ))}
        </Select>
        <FieldHelp text={field.help_text} />
      </div>
    )
  }

  if (field.type === 'number') {
    return (
      <div>
        <Label>
          <LabelText label={field.label} required={field.required} />
        </Label>
        <Input
          type="number"
          value={value === undefined || value === null ? '' : toNumber(value)}
          min={field.min}
          max={field.max}
          onChange={(e) => onChange(e.target.value === '' ? '' : toNumber(e.target.value))}
        />
        <FieldHelp text={field.help_text} />
      </div>
    )
  }

  return (
    <div>
      <Label>
        <LabelText label={field.label} required={field.required} />
      </Label>
      <Input
        type={field.type === 'password' ? 'password' : 'text'}
        autoComplete={field.type === 'password' ? 'off' : undefined}
        value={(value as string) ?? ''}
        onChange={(e) => onChange(e.target.value)}
        placeholder={field.type === 'password' ? '••••••••' : undefined}
      />
      <FieldHelp text={field.help_text} />
    </div>
  )
}

function ObjectListField({
  field,
  value,
  onChange,
}: {
  field: Extract<FieldSchema, { type: 'object_list' }>
  value: unknown
  onChange: (value: unknown) => void
}) {
  const items = ensureArray(value).map(ensureObject)
  const itemFields = field.item_fields

  const setItem = (idx: number, next: Record<string, unknown>) => {
    onChange(items.map((it, i) => (i === idx ? next : it)))
  }
  const remove = (idx: number) => onChange(items.filter((_, i) => i !== idx))
  const add = () => onChange([...items, buildItemDefault(itemFields)])

  return (
    <div className="space-y-1.5">
      <div className="flex items-center justify-between">
        <Label>{field.label}</Label>
        <Button type="button" variant="outline" size="sm" onClick={add}>
          <Plus className="h-4 w-4" />
          {field.item_label}
        </Button>
      </div>
      <FieldHelp text={field.help_text} />
      <div className="space-y-3">
        {items.map((item, idx) => (
          <Card key={idx}>
            <CardHeader className="flex flex-row items-center justify-between pb-2">
              <span className="text-foreground text-sm font-medium">
                {field.item_label} #{idx + 1}
              </span>
              <Button
                type="button"
                variant="ghost"
                size="icon-sm"
                onClick={() => remove(idx)}
                aria-label="Remove"
                className="text-muted-foreground hover:text-destructive"
              >
                <Trash2 className="h-4 w-4" />
              </Button>
            </CardHeader>
            <CardContent className="grid grid-cols-1 gap-4 pt-0 md:grid-cols-2">
              {itemFields.map((f) => (
                <FieldRenderer
                  key={f.path}
                  field={f}
                  value={item[f.path]}
                  onChange={(v) => setItem(idx, { ...item, [f.path]: v })}
                />
              ))}
            </CardContent>
          </Card>
        ))}
      </div>
    </div>
  )
}

function DiscriminatedObjectListField({
  field,
  value,
  onChange,
}: {
  field: Extract<FieldSchema, { type: 'discriminated_object_list' }>
  value: unknown
  onChange: (value: unknown) => void
}) {
  const items = ensureArray(value).map(ensureObject)
  const discriminator = field.discriminator

  const setItem = (idx: number, next: Record<string, unknown>) => {
    onChange(items.map((it, i) => (i === idx ? next : it)))
  }
  const remove = (idx: number) => onChange(items.filter((_, i) => i !== idx))
  const switchVariant = (idx: number, variantName: string) => {
    const variant = field.variants.find((v) => v.name === variantName)
    if (!variant) return
    setItem(idx, buildVariantDefault(discriminator, variantName, variant.fields))
  }
  const add = (variantName: string) => {
    const variant = field.variants.find((v) => v.name === variantName)
    if (!variant) return
    onChange([...items, buildVariantDefault(discriminator, variantName, variant.fields)])
  }

  return (
    <div className="space-y-1.5">
      <div className="flex items-center justify-between">
        <Label>{field.label}</Label>
        <div className="flex flex-wrap gap-2">
          {field.variants.map((v) => (
            <Button
              key={v.name}
              type="button"
              variant="outline"
              size="sm"
              onClick={() => add(v.name)}
            >
              <Plus className="h-4 w-4" />
              {v.label}
            </Button>
          ))}
        </div>
      </div>
      <FieldHelp text={field.help_text} />
      <div className="space-y-3">
        {items.map((item, idx) => {
          const currentType = String(item[discriminator] ?? field.variants[0]?.name ?? '')
          const variant = field.variants.find((v) => v.name === currentType)
          return (
            <Card key={idx}>
              <CardHeader className="flex flex-row items-center justify-between gap-2 pb-2">
                <div className="min-w-[10rem] flex-1">
                  <Select value={currentType} onChange={(e) => switchVariant(idx, e.target.value)}>
                    {field.variants.map((v) => (
                      <option key={v.name} value={v.name}>
                        {v.label}
                      </option>
                    ))}
                  </Select>
                </div>
                <Button
                  type="button"
                  variant="ghost"
                  size="icon-sm"
                  onClick={() => remove(idx)}
                  aria-label="Remove"
                  className="text-muted-foreground hover:text-destructive"
                >
                  <Trash2 className="h-4 w-4" />
                </Button>
              </CardHeader>
              <CardContent className="grid grid-cols-1 gap-4 pt-0 md:grid-cols-2">
                {variant?.fields.map((f) => (
                  <FieldRenderer
                    key={f.path}
                    field={f}
                    value={item[f.path]}
                    onChange={(v) =>
                      setItem(idx, { ...item, [discriminator]: currentType, [f.path]: v })
                    }
                  />
                ))}
              </CardContent>
            </Card>
          )
        })}
      </div>
    </div>
  )
}

function FieldRenderer({
  field,
  value,
  onChange,
}: {
  field: FieldSchema
  value: unknown
  onChange: (value: unknown) => void
}) {
  if (field.type === 'object_list') {
    return <ObjectListField field={field} value={value} onChange={onChange} />
  }
  if (field.type === 'discriminated_object_list') {
    return <DiscriminatedObjectListField field={field} value={value} onChange={onChange} />
  }
  return <SimpleField field={field} value={value} onChange={onChange} />
}

export function ConfigSections({
  sectionName,
  sections,
  configDraft,
  onConfigChange,
}: {
  sectionName: string
  sections: FieldGroup[]
  configDraft: Record<string, unknown>
  onConfigChange: (next: Record<string, unknown>) => void
}) {
  return (
    <div className="space-y-8">
      {sections.map((group) => {
        // A group's fields are either top-level scalars (group.name === "_general",
        // field paths are config-root keys like "language") or members of a nested
        // object (group.name is the object key, field paths are relative like "model").
        const isNested = group.name !== '_general'
        const groupRoot: Record<string, unknown> = isNested
          ? (ensureObject(configDraft[group.name]) as Record<string, unknown>)
          : configDraft
        // DOM id must be unique across the whole page (every section can have a
        // "_general" group), so namespace it with the section name.
        const groupId = `${sectionName}__${group.name}`
        return (
          <section key={groupId} id={groupId} className="scroll-mt-20 py-6 first:pt-0">
            <h2 className="text-foreground mb-4 text-xl font-bold">{group.label}</h2>
            <Card>
              <CardContent className="space-y-6 pt-6">
                {group.fields.map((field) => (
                  <FieldRenderer
                    key={field.path}
                    field={field}
                    value={getAtPath(groupRoot, field.path)}
                    onChange={(v) => {
                      const updatedRoot = setAtPath(groupRoot, field.path, v)
                      onConfigChange(
                        isNested ? { ...configDraft, [group.name]: updatedRoot } : updatedRoot,
                      )
                    }}
                  />
                ))}
              </CardContent>
            </Card>
          </section>
        )
      })}
    </div>
  )
}
