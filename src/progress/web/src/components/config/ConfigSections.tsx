import type { FieldSchema, SectionSchema } from '@/hooks/api'
import { useTimezones } from '@/hooks/api'
import { getAtPath, setAtPath } from '@/lib/path'
import { Button } from '@/components/ui/button'
import { Card, CardContent, CardHeader } from '@/components/ui/card'
import { Checkbox } from '@/components/ui/checkbox'
import { Input } from '@/components/ui/input'
import { Label } from '@/components/ui/label'
import { Select } from '@/components/ui/select'

function toBoolean(v: unknown): boolean {
  return v === true || v === 'true' || v === 1
}

function toNumber(v: unknown): number {
  if (typeof v === 'number') return v
  const n = Number(v)
  return Number.isFinite(n) ? n : 0
}

function defaultValueForField(field: FieldSchema): unknown {
  if (field.default !== undefined) return field.default
  if (field.type === 'boolean') return false
  if (field.type === 'number') return 0
  if (field.type === 'timezone') return 'UTC'
  if (field.type === 'string_list') return []
  if (field.type === 'object_list') return []
  if (field.type === 'discriminated_object_list') return []
  return ''
}

function ensureObject(v: unknown): Record<string, unknown> {
  if (v && typeof v === 'object' && !Array.isArray(v)) return v as Record<string, unknown>
  return {}
}

function ensureArray(v: unknown): unknown[] {
  if (Array.isArray(v)) return v
  return []
}

function buildItemDefault(fields: FieldSchema[]): Record<string, unknown> {
  const item: Record<string, unknown> = {}
  for (const f of fields) {
    item[f.path] = defaultValueForField(f)
  }
  return item
}

function buildVariantDefault(
  discriminator: string,
  variant: string,
  fields: FieldSchema[],
): Record<string, unknown> {
  const item = buildItemDefault(fields)
  item[discriminator] = variant
  return item
}

function FieldHelp({ text }: { text?: string | null }) {
  if (!text) return null
  return <div className="mt-1 text-xs text-muted-foreground">{text}</div>
}

function LabelText({ label, required }: { label: string; required?: boolean }) {
  return (
    <>
      {label}
      {required && <span className="ml-1 text-destructive">*</span>}
    </>
  )
}

function SimpleField({
  field,
  value,
  onChange,
}: {
  field: FieldSchema
  value: unknown
  onChange: (value: unknown) => void
}) {
  const { data: tzData } = useTimezones()

  if (field.type === 'boolean') {
    return (
      <div className="flex items-center gap-2">
        <Checkbox checked={toBoolean(value)} onChange={(e) => onChange(e.currentTarget.checked)} />
        <span className="text-sm text-foreground">{field.label}</span>
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
          {(field.options || []).map((opt) => (
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
          {(tzData?.timezones || ['UTC']).map((tz) => (
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
          value={toNumber(value)}
          min={typeof field.validation?.min === 'number' ? (field.validation.min as number) : undefined}
          max={typeof field.validation?.max === 'number' ? (field.validation.max as number) : undefined}
          onChange={(e) => onChange(e.target.value === '' ? '' : toNumber(e.target.value))}
        />
        <FieldHelp text={field.help_text} />
      </div>
    )
  }

  const type = field.type === 'password' ? 'password' : 'text'
  return (
    <div>
      <Label>
        <LabelText label={field.label} required={field.required} />
      </Label>
      <Input type={type} value={(value as string) ?? ''} onChange={(e) => onChange(e.target.value)} />
      <FieldHelp text={field.help_text} />
    </div>
  )
}

function StringListField({
  field,
  value,
  onChange,
}: {
  field: FieldSchema
  value: unknown
  onChange: (value: unknown) => void
}) {
  const items = ensureArray(value).map((v) => (typeof v === 'string' ? v : String(v)))

  const update = (idx: number, next: string) => {
    const copy = [...items]
    copy[idx] = next
    onChange(copy.filter((x) => x !== ''))
  }

  const remove = (idx: number) => {
    const copy = items.filter((_, i) => i !== idx)
    onChange(copy)
  }

  const add = () => onChange([...items, ''])

  return (
    <div>
      <div className="flex items-center justify-between">
        <Label>
          <LabelText label={field.label} required={field.required} />
        </Label>
        <Button variant="outline" size="sm" type="button" onClick={add}>
          Add
        </Button>
      </div>
      <FieldHelp text={field.help_text} />
      <div className="mt-2 space-y-2">
        {items.map((item, idx) => (
          <div key={idx} className="flex items-center gap-2">
            <Input value={item} onChange={(e) => update(idx, e.target.value)} />
            <Button variant="ghost" size="sm" type="button" onClick={() => remove(idx)}>
              Remove
            </Button>
          </div>
        ))}
      </div>
    </div>
  )
}

function ObjectListField({
  field,
  value,
  onChange,
}: {
  field: FieldSchema
  value: unknown
  onChange: (value: unknown) => void
}) {
  const items = ensureArray(value).map((v) => ensureObject(v))
  const itemFields = field.item_fields || []

  const add = () => {
    onChange([...items, buildItemDefault(itemFields)])
  }

  const remove = (idx: number) => onChange(items.filter((_, i) => i !== idx))

  const setItem = (idx: number, next: Record<string, unknown>) => {
    const copy = items.map((it, i) => (i === idx ? next : it))
    onChange(copy)
  }

  return (
    <div>
      <div className="flex items-center justify-between">
        <div>
          <Label>
            <LabelText label={field.label} required={field.required} />
          </Label>
          <FieldHelp text={field.help_text} />
        </div>
        <Button variant="outline" size="sm" type="button" onClick={add}>
          Add {field.item_label || 'Item'}
        </Button>
      </div>

      <div className="mt-4 space-y-4">
        {items.map((item, idx) => (
          <Card key={idx}>
            <CardHeader>
              <div className="flex items-center justify-between">
                <div className="text-sm font-semibold text-foreground">
                  {field.item_label || 'Item'} #{idx + 1}
                </div>
                <Button variant="destructive" size="sm" type="button" onClick={() => remove(idx)}>
                  Remove
                </Button>
              </div>
            </CardHeader>
            <CardContent>
              <div className="grid grid-cols-1 gap-4 md:grid-cols-2">
                {itemFields.map((f) => (
                  <div key={f.path}>
                    {f.type === 'string_list' ? (
                      <StringListField
                        field={f}
                        value={item[f.path]}
                        onChange={(v) => setItem(idx, { ...item, [f.path]: v })}
                      />
                    ) : (
                      <SimpleField
                        field={f}
                        value={item[f.path]}
                        onChange={(v) => setItem(idx, { ...item, [f.path]: v })}
                      />
                    )}
                  </div>
                ))}
              </div>
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
  field: FieldSchema
  value: unknown
  onChange: (value: unknown) => void
}) {
  const items = ensureArray(value).map((v) => ensureObject(v))
  const discriminator = field.discriminator || 'type'
  const variants = field.variants || {}
  const variantKeys = Object.keys(variants)

  const add = () => {
    const first = variantKeys[0]
    if (!first) return
    onChange([...items, buildVariantDefault(discriminator, first, variants[first] || [])])
  }

  const remove = (idx: number) => onChange(items.filter((_, i) => i !== idx))

  const setItem = (idx: number, next: Record<string, unknown>) => {
    const copy = items.map((it, i) => (i === idx ? next : it))
    onChange(copy)
  }

  const switchVariant = (idx: number, nextType: string) => {
    const fields = variants[nextType] || []
    setItem(idx, buildVariantDefault(discriminator, nextType, fields))
  }

  return (
    <div>
      <div className="flex items-center justify-between">
        <div>
          <Label>
            <LabelText label={field.label} required={field.required} />
          </Label>
          <FieldHelp text={field.help_text} />
        </div>
        <Button variant="outline" size="sm" type="button" onClick={add}>
          Add {field.item_label || 'Item'}
        </Button>
      </div>

      <div className="mt-4 space-y-4">
        {items.map((item, idx) => {
          const currentType = (item[discriminator] as string) || variantKeys[0] || ''
          const currentFields = variants[currentType] || []

          return (
            <Card key={idx}>
              <CardHeader>
                <div className="flex items-center justify-between gap-3">
                  <div className="flex items-center gap-3">
                    <div className="text-sm font-semibold text-foreground">
                      {field.item_label || 'Item'} #{idx + 1}
                    </div>
                    <Select
                      value={currentType}
                      onChange={(e) => switchVariant(idx, e.target.value)}
                    >
                      {variantKeys.map((k) => (
                        <option key={k} value={k}>
                          {k}
                        </option>
                      ))}
                    </Select>
                  </div>
                  <Button variant="destructive" size="sm" type="button" onClick={() => remove(idx)}>
                    Remove
                  </Button>
                </div>
              </CardHeader>
              <CardContent>
                <div className="grid grid-cols-1 gap-4 md:grid-cols-2">
                  {currentFields.map((f) => (
                    <div key={f.path}>
                      {f.type === 'string_list' ? (
                        <StringListField
                          field={f}
                          value={item[f.path]}
                          onChange={(v) =>
                            setItem(idx, {
                              ...item,
                              [discriminator]: currentType,
                              [f.path]: v,
                            })
                          }
                        />
                      ) : (
                        <SimpleField
                          field={f}
                          value={item[f.path]}
                          onChange={(v) =>
                            setItem(idx, {
                              ...item,
                              [discriminator]: currentType,
                              [f.path]: v,
                            })
                          }
                        />
                      )}
                    </div>
                  ))}
                </div>
              </CardContent>
            </Card>
          )
        })}
      </div>
    </div>
  )
}

interface ConfigSectionsProps {
  sections: SectionSchema[]
  configDraft: Record<string, unknown>
  onConfigChange: (next: Record<string, unknown>) => void
}

export function ConfigSections({
  sections,
  configDraft,
  onConfigChange,
}: ConfigSectionsProps) {
  return (
    <div className="space-y-8">
      {sections.map((section) => (
        <section key={section.id} id={section.id} className="scroll-mt-20 py-6 first:pt-0">
          <h2 className="mb-1 text-xl font-bold text-foreground">{section.title}</h2>
          {section.description && (
            <p className="mb-4 text-sm text-muted-foreground">{section.description}</p>
          )}
          <Card>
            <CardContent className="space-y-6 pt-6">
              {section.fields.map((field) => {
              const value = getAtPath(configDraft, field.path)
              const setValue = (v: unknown) => onConfigChange(setAtPath(configDraft, field.path, v))

              if (field.type === 'object_list') {
                return <ObjectListField key={field.path} field={field} value={value} onChange={setValue} />
              }

              if (field.type === 'discriminated_object_list') {
                return (
                  <DiscriminatedObjectListField
                    key={field.path}
                    field={field}
                    value={value}
                    onChange={setValue}
                  />
                )
              }

              if (field.type === 'string_list') {
                return <StringListField key={field.path} field={field} value={value} onChange={setValue} />
              }

              return <SimpleField key={field.path} field={field} value={value} onChange={setValue} />
            })}
            </CardContent>
          </Card>
        </section>
      ))}
    </div>
  )
}
