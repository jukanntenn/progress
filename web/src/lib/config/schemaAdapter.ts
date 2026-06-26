/**
 * Convert the pydantic-generated JSON Schema (served by GET /api/v1/config/schema)
 * into the flat SectionSchema/FieldSchema shapes the existing ConfigSections
 * renderer expects. The JSON Schema is the single source of truth; this adapter
 * only reshapes it for rendering.
 */

import type { FieldSchema, JsonSchema, SectionSchema } from "@/lib/api";

type SchemaNode = Record<string, unknown>;

const SECTION_ORDER = [
  "general",
  "github",
  "analysis",
  "report",
  "markpost",
  "notification",
  "repos",
  "owners",
  "proposal_trackers",
  "changelog_trackers",
];

const SECTION_TITLES: Record<string, string> = {
  general: "General",
  github: "GitHub",
  analysis: "Analysis",
  report: "Report",
  markpost: "Markpost",
  notification: "Notification",
  repos: "Repositories",
  owners: "Owners",
  proposal_trackers: "Proposal Trackers",
  changelog_trackers: "Changelog Trackers",
};

const ITEM_LABELS: Record<string, string> = {
  repos: "Repository",
  owners: "Owner",
  changelog_trackers: "Tracker",
};

function asNode(value: unknown): SchemaNode | undefined {
  return value && typeof value === "object" ? (value as SchemaNode) : undefined;
}

function resolveRef(node: unknown, root: SchemaNode): SchemaNode | undefined {
  const obj = asNode(node);
  if (!obj || !obj.$ref) return obj;
  const parts = String(obj.$ref).replace(/^#\/?/, "").split("/");
  let cur: unknown = root;
  for (const part of parts) cur = (asNode(cur) ?? {})?.[part];
  return asNode(cur) ?? obj;
}

function unwrapAnyOf(node: unknown): SchemaNode | undefined {
  const obj = asNode(node);
  if (!obj || !Array.isArray(obj.anyOf)) return obj;
  const nonNull = (obj.anyOf as SchemaNode[]).find((v) => v.type !== "null");
  if (!nonNull) return obj;
  const rest = Object.fromEntries(
    Object.entries(obj).filter(([key]) => key !== "anyOf"),
  );
  return { ...rest, ...nonNull };
}

function humanize(key: string): string {
  return key
    .replace(/_/g, " ")
    .replace(/\b\w/g, (c) => c.toUpperCase());
}

function scalarField(
  name: string,
  node: SchemaNode,
  path: string,
  required: boolean,
): FieldSchema {
  const label = (node.title as string) || humanize(name);
  const help_text = (node.description as string) || null;
  const def = node.default;

  if (Array.isArray(node.enum)) {
    return {
      type: "select",
      path,
      label,
      help_text,
      required,
      default: def,
      options: node.enum as string[],
    };
  }

  if (node.type === "integer" || node.type === "number") {
    const validation: Record<string, unknown> = {};
    if (typeof node.minimum === "number") validation.min = node.minimum;
    if (typeof node.maximum === "number") validation.max = node.maximum;
    return { type: "number", path, label, help_text, required, default: def, validation };
  }

  if (node.type === "boolean") {
    return { type: "boolean", path, label, help_text, required, default: def };
  }

  if (node.writeOnly === true || node.format === "password") {
    return { type: "password", path, label, help_text, required, default: def };
  }

  if (node.format === "timezone") {
    return { type: "timezone", path, label, help_text, required, default: def };
  }

  return { type: "text", path, label, help_text, required, default: def };
}

function objectFields(objNode: SchemaNode, root: SchemaNode): FieldSchema[] {
  const props = (objNode.properties ?? {}) as Record<string, unknown>;
  const required = new Set((objNode.required ?? []) as string[]);
  return Object.entries(props).map(([name, raw]) => {
    const node = unwrapAnyOf(resolveRef(raw, root))!;
    const path = name;
    if (node.type === "array") {
      return arrayField(name, node, root, path);
    }
    return scalarField(name, node, path, required.has(name));
  });
}

function arrayField(
  name: string,
  arrayNode: SchemaNode,
  root: SchemaNode,
  path: string,
): FieldSchema {
  const label = humanize(name);
  const items = unwrapAnyOf(resolveRef(arrayNode.items, root))!;
  const item_label = ITEM_LABELS[name] || "Item";

  if (Array.isArray(items.oneOf) || items.discriminator) {
    const discriminator = ((items.discriminator as SchemaNode)?.propertyName as string) || "type";
    const branches = (items.oneOf ?? []) as unknown[];
    const variants: Record<string, FieldSchema[]> = {};
    for (const branch of branches) {
      const resolved = resolveRef(branch, root)!;
      const props = (resolved.properties ?? {}) as Record<string, unknown>;
      const keyProp = asNode(props[discriminator]);
      const variantKey = keyProp?.const as string;
      if (variantKey) variants[variantKey] = objectFields(resolved, root);
    }
    return {
      type: "discriminated_object_list",
      path,
      label,
      item_label,
      discriminator,
      variants,
    };
  }

  if (items.type === "object") {
    return {
      type: "object_list",
      path,
      label,
      item_label,
      item_fields: objectFields(items, root),
    };
  }

  return {
    type: "string_list",
    path,
    label,
    options: Array.isArray(items.enum) ? (items.enum as string[]) : undefined,
  };
}

export function jsonSchemaToSections(schema: JsonSchema): SectionSchema[] {
  const root = schema as SchemaNode;
  const props = (root.properties ?? {}) as Record<string, unknown>;
  const generalFields: FieldSchema[] = [];
  const sections: SectionSchema[] = [];

  for (const [key, raw] of Object.entries(props)) {
    const node = unwrapAnyOf(resolveRef(raw, root))!;
    if (node.type === "array") {
      sections.push({
        id: key,
        title: SECTION_TITLES[key] || humanize(key),
        fields: [arrayField(key, node, root, key)],
      });
    } else if (node.type === "object") {
      sections.push({
        id: key,
        title: SECTION_TITLES[key] || humanize(key),
        fields: objectFields(node, root).map((f) => ({ ...f, path: `${key}.${f.path}` })),
      });
    } else {
      generalFields.push(scalarField(key, node, key, false));
    }
  }

  if (generalFields.length) {
    sections.unshift({
      id: "general",
      title: SECTION_TITLES.general,
      fields: generalFields,
    });
  }

  return sections.sort((a, b) => {
    const ia = SECTION_ORDER.indexOf(a.id);
    const ib = SECTION_ORDER.indexOf(b.id);
    return (ia === -1 ? 999 : ia) - (ib === -1 ? 999 : ib);
  });
}
