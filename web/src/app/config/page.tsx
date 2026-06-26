"use client";

import { Dialog } from "@/components/ui/dialog";
import { Skeleton } from "@/components/ui/skeleton";
import { Button } from "@/components/ui/button";
import { Header, PageContainer } from "@/components/layout";
import { SectionNav } from "@/components/config/SectionNav";
import { ConfigSections } from "@/components/config/ConfigSections";
import { showToast } from "@/components/providers";
import { saveConfig, validateConfig } from "@/lib/api";
import { jsonSchemaToSections } from "@/lib/config/schemaAdapter";
import { useConfig, useConfigSchema, useScrollSpy } from "@/hooks";
import { useQueryClient } from "@tanstack/react-query";
import { configKeys } from "@/lib/api";
import { useEffect, useMemo, useState } from "react";
import { RotateCcw, Save, Check, AlertCircle } from "lucide-react";
import { cn } from "@/lib/utils";

export default function ConfigPage() {
  const { data, error, isLoading } = useConfig();
  const { data: schema, error: schemaError, isLoading: schemaLoading } = useConfigSchema();
  const queryClient = useQueryClient();

  const [isSaving, setIsSaving] = useState(false);
  const [configDraft, setConfigDraft] = useState<Record<string, unknown>>({});
  const [version, setVersion] = useState<number>(0);
  const [validationError, setValidationError] = useState<string | null>(null);
  const [showValidationDialog, setShowValidationDialog] = useState(false);

  const sections = useMemo(
    () => (schema ? jsonSchemaToSections(schema) : []),
    [schema],
  );
  const sectionIds = useMemo(() => sections.map((s) => s.id), [sections]);
  const activeSection = useScrollSpy(sectionIds);

  useEffect(() => {
    if (data) {
      setConfigDraft(data.data);
      setVersion(data.version);
    }
  }, [data]);

  const isModified =
    JSON.stringify(configDraft) !== JSON.stringify(data?.data ?? {});

  const handleReset = () => {
    if (window.confirm("Reset to saved configuration? Unsaved changes will be lost.")) {
      setConfigDraft(data?.data ?? {});
      setVersion(data?.version ?? 0);
    }
  };

  const handleValidate = async () => {
    try {
      const validation = await validateConfig(configDraft);
      if (!validation.success) {
        setValidationError(validation.error || "Unknown validation error");
        setShowValidationDialog(true);
        showToast("Validation failed", "error");
        return;
      }
      showToast("Configuration is valid", "success");
    } catch (e) {
      showToast("Validation error: " + (e as Error).message, "error");
    }
  };

  const handleSave = async () => {
    setIsSaving(true);
    try {
      const validation = await validateConfig(configDraft);
      if (!validation.success) {
        setValidationError(validation.error || "Unknown validation error");
        setShowValidationDialog(true);
        showToast("Validation failed", "error");
        return;
      }

      const result = await saveConfig(configDraft, version);
      setConfigDraft(result.data);
      setVersion(result.version);
      queryClient.setQueryData(configKeys.data(), {
        data: result.data,
        version: result.version,
      });
      showToast("Configuration saved successfully!", "success");
    } catch (e) {
      const err = e as Error & { status?: number };
      if (err.status === 409) {
        showToast("Configuration was modified elsewhere; refreshing.", "error");
        queryClient.invalidateQueries({ queryKey: configKeys.data() });
      } else {
        showToast("Save failed: " + err.message, "error");
      }
    } finally {
      setIsSaving(false);
    }
  };

  if (isLoading) {
    return (
      <>
        <Header />
        <PageContainer size="medium">
          <div className="space-y-4">
            <Skeleton className="h-7 w-48" />
            <div className="flex gap-2">
              <Skeleton className="h-9 w-20" />
              <Skeleton className="h-9 w-24" />
            </div>
            <Skeleton className="h-96 w-full" />
          </div>
        </PageContainer>
      </>
    );
  }

  if (error) {
    return (
      <>
        <Header />
        <PageContainer size="medium">
          <div className="py-12 text-center">
            <div className="text-error mb-4 text-lg font-medium">Failed to load configuration</div>
            <p className="text-muted-foreground">Unable to load the configuration from the server.</p>
          </div>
        </PageContainer>
      </>
    );
  }

  const handleSectionClick = (sectionId: string) => {
    const el = document.getElementById(sectionId);
    if (el) {
      el.scrollIntoView({ behavior: "smooth", block: "start" });
    }
  };

  return (
    <>
      <Header />
      <PageContainer size="medium">
        <div className="mb-6">
          <div className="flex flex-col gap-4 sm:flex-row sm:items-center sm:justify-between">
            <div>
              <h1 className="text-xl font-bold text-foreground">Configuration Editor</h1>
              <p className="mt-1 text-sm text-muted-foreground">
                Stored in the database (version {version})
              </p>
            </div>

            <div className="flex items-center gap-2">
              <Button
                variant="outline"
                size="sm"
                type="button"
                onClick={handleReset}
                leftIcon={<RotateCcw className="h-4 w-4" />}
              >
                Reset
              </Button>
              <Button variant="outline" size="sm" type="button" onClick={handleValidate}>
                Validate
              </Button>
              <Button
                size="sm"
                type="button"
                onClick={handleSave}
                disabled={!isModified || isSaving}
                loading={isSaving}
                leftIcon={<Save className="h-4 w-4" />}
              >
                {isSaving ? "Saving..." : "Save"}
              </Button>
            </div>
          </div>
        </div>

        <div className="grid grid-cols-1 gap-6 lg:grid-cols-[220px_1fr]">
          <aside className="hidden lg:block">
            <div className="sticky top-24">
              <div className="mb-3 text-sm font-semibold text-foreground">Sections</div>
              <SectionNav
                sections={sections}
                activeSection={activeSection}
                onSectionClick={handleSectionClick}
              />
            </div>
          </aside>

          <main>
            {schemaLoading && (
              <div className="animate-pulse space-y-4">
                <Skeleton className="h-4 w-32" />
                <Skeleton className="h-10 w-full" />
                <Skeleton className="h-10 w-full" />
                <Skeleton className="h-10 w-full" />
              </div>
            )}
            {schemaError && (
              <div className="py-8 text-center">
                <AlertCircle className="mx-auto mb-3 h-8 w-8 text-error" />
                <p className="font-medium text-error">Failed to load config schema</p>
              </div>
            )}
            {sections.length > 0 && (
              <ConfigSections
                sections={sections}
                configDraft={configDraft}
                onConfigChange={setConfigDraft}
              />
            )}
          </main>
        </div>

        <div className="mt-4 flex items-center gap-2 text-sm">
          <span
            className={cn(
              "inline-flex items-center gap-1.5",
              isModified
                ? "text-warning-600 dark:text-warning-500"
                : "text-success-600 dark:text-success-500",
            )}
          >
            {isModified ? (
              <>
                <span className="h-2 w-2 animate-pulse rounded-full bg-warning-500" />
                Unsaved changes
              </>
            ) : (
              <>
                <Check className="h-4 w-4" />
                No changes
              </>
            )}
          </span>
        </div>

        <Dialog
          open={showValidationDialog}
          onClose={() => setShowValidationDialog(false)}
          title="Validation Errors"
        >
          <pre className="whitespace-pre-wrap break-words bg-muted p-4 text-sm text-foreground rounded-lg overflow-auto max-h-[60vh]">
            {validationError}
          </pre>
        </Dialog>
      </PageContainer>
    </>
  );
}
