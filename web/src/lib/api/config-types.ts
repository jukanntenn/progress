/**
 * Editor field/section shapes produced by the JSON-Schema -> editor adapter
 * (see lib/config/schemaAdapter.ts) and consumed by the ConfigSections
 * renderer. These are NOT the raw JSON Schema types.
 */

export interface FieldSchema {
  type:
    | "text"
    | "password"
    | "number"
    | "boolean"
    | "select"
    | "timezone"
    | "string_list"
    | "object_list"
    | "discriminated_object_list";
  path: string;
  label: string;
  help_text?: string | null;
  required?: boolean;
  default?: unknown;
  options?: string[];
  validation?: Record<string, unknown>;
  item_label?: string | null;
  item_fields?: FieldSchema[] | null;
  discriminator?: string | null;
  variants?: Record<string, FieldSchema[]> | null;
}

export interface SectionSchema {
  id: string;
  title: string;
  description?: string;
  fields: FieldSchema[];
}
