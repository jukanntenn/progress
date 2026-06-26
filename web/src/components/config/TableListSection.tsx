"use client";

import type { FieldSchema } from "@/lib/api";
import { Button } from "@/components/ui/button";
import { Card, CardContent } from "@/components/ui/card";
import { ObjectListField } from "./ConfigSections";

interface TableListSectionProps {
  id: string;
  title: string;
  description?: string;
  field: FieldSchema;
  items: Record<string, unknown>[];
  onItemsChange: (items: Record<string, unknown>[]) => void;
  modified: boolean;
  onSave: () => void;
  saving?: boolean;
}

/**
 * Renders a table-backed list (repos / owners) with a per-section Save button.
 * Unlike the blob sections, these persist via a dedicated replace endpoint
 * (PUT) rather than the blob POST.
 */
export function TableListSection({
  id,
  title,
  description,
  field,
  items,
  onItemsChange,
  modified,
  onSave,
  saving,
}: TableListSectionProps) {
  return (
    <section id={id} className="scroll-mt-20 py-6 first:pt-0">
      <div className="mb-1 flex items-center justify-between">
        <h2 className="text-xl font-bold text-foreground">{title}</h2>
        <Button size="sm" type="button" onClick={onSave} disabled={!modified || saving} loading={saving}>
          {saving ? "Saving..." : "Save"}
        </Button>
      </div>
      {description && <p className="mb-4 text-sm text-muted-foreground">{description}</p>}
      <Card>
        <CardContent className="pt-6">
          <ObjectListField
            field={field}
            value={items}
            onChange={(v) => onItemsChange(v as Record<string, unknown>[])}
          />
        </CardContent>
      </Card>
    </section>
  );
}
