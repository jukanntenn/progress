"use client";

import { Dialog } from "@/components/ui/dialog";
import { Skeleton } from "@/components/ui/skeleton";
import { Button } from "@/components/ui/button";
import { Header, PageContainer } from "@/components/layout";
import { SectionNav } from "@/components/config/SectionNav";
import { ConfigSections } from "@/components/config/ConfigSections";
import { TableListSection } from "@/components/config/TableListSection";
import { showToast } from "@/components/providers";
import {
  saveConfig,
  validateConfig,
  replaceRepos,
  replaceOwners,
  configKeys,
  type FieldSchema,
  type RepoInput,
  type OwnerInput,
} from "@/lib/api";
import { jsonSchemaToSections } from "@/lib/config/schemaAdapter";
import { useConfig, useConfigSchema, useRepos, useOwners, useScrollSpy } from "@/hooks";
import { useQueryClient } from "@tanstack/react-query";
import { useEffect, useMemo, useState } from "react";
import { RotateCcw, Save, Check, AlertCircle } from "lucide-react";
import { cn } from "@/lib/utils";

const REPOS_FIELD: FieldSchema = {
  type: "object_list",
  path: "repos",
  label: "Repositories",
  item_label: "Repository",
  item_fields: [
    {
      type: "text",
      path: "url",
      label: "URL",
      required: true,
      help_text: "owner/repo, https://..., or git@...",
    },
    { type: "text", path: "branch", label: "Branch", default: "main" },
    { type: "boolean", path: "enabled", label: "Enabled", default: true },
  ],
};

const OWNERS_FIELD: FieldSchema = {
  type: "object_list",
  path: "owners",
  label: "Owners",
  item_label: "Owner",
  item_fields: [
    {
      type: "select",
      path: "owner_type",
      label: "Type",
      required: true,
      options: ["user", "organization"],
    },
    { type: "text", path: "name", label: "Name", required: true },
    { type: "boolean", path: "enabled", label: "Enabled", default: true },
  ],
};

export default function ConfigPage() {
  const { data, error, isLoading } = useConfig();
  const { data: schema, error: schemaError, isLoading: schemaLoading } = useConfigSchema();
  const { data: reposData } = useRepos();
  const { data: ownersData } = useOwners();
  const queryClient = useQueryClient();

  const [isSaving, setIsSaving] = useState(false);
  const [configDraft, setConfigDraft] = useState<Record<string, unknown>>({});
  const [version, setVersion] = useState<number>(0);
  const [validationError, setValidationError] = useState<string | null>(null);
  const [showValidationDialog, setShowValidationDialog] = useState(false);

  const [reposDraft, setReposDraft] = useState<Record<string, unknown>[]>([]);
  const [ownersDraft, setOwnersDraft] = useState<Record<string, unknown>[]>([]);
  const [savingRepos, setSavingRepos] = useState(false);
  const [savingOwners, setSavingOwners] = useState(false);

  const sections = useMemo(() => (schema ? jsonSchemaToSections(schema) : []), [schema]);
  const navSections = useMemo(
    () => [
      ...sections.map((s) => ({ id: s.id, title: s.title })),
      { id: "repositories", title: "Repositories" },
      { id: "owners", title: "Owners" },
    ],
    [sections],
  );
  const sectionIds = useMemo(() => navSections.map((s) => s.id), [navSections]);
  const activeSection = useScrollSpy(sectionIds);

  useEffect(() => {
    if (data) {
      setConfigDraft(data.data);
      setVersion(data.version);
    }
  }, [data]);

  useEffect(() => {
    if (reposData) setReposDraft(reposData as unknown as Record<string, unknown>[]);
  }, [reposData]);

  useEffect(() => {
    if (ownersData) setOwnersDraft(ownersData as unknown as Record<string, unknown>[]);
  }, [ownersData]);

  const isModified = JSON.stringify(configDraft) !== JSON.stringify(data?.data ?? {});
  const reposModified = JSON.stringify(reposDraft) !== JSON.stringify(reposData ?? []);
  const ownersModified = JSON.stringify(ownersDraft) !== JSON.stringify(ownersData ?? []);

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

  const handleSaveRepos = async () => {
    setSavingRepos(true);
    try {
      const result = await replaceRepos(reposDraft as unknown as RepoInput[]);
      queryClient.setQueryData(configKeys.repos(), result);
      showToast("Repositories saved", "success");
    } catch (e) {
      showToast("Save failed: " + (e as Error).message, "error");
    } finally {
      setSavingRepos(false);
    }
  };

  const handleSaveOwners = async () => {
    setSavingOwners(true);
    try {
      const result = await replaceOwners(ownersDraft as unknown as OwnerInput[]);
      queryClient.setQueryData(configKeys.owners(), result);
      showToast("Owners saved", "success");
    } catch (e) {
      showToast("Save failed: " + (e as Error).message, "error");
    } finally {
      setSavingOwners(false);
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
                sections={navSections}
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

            <TableListSection
              id="repositories"
              title="Repositories"
              description="Repositories to track. Stored in the database."
              field={REPOS_FIELD}
              items={reposDraft}
              onItemsChange={setReposDraft}
              modified={reposModified}
              onSave={handleSaveRepos}
              saving={savingRepos}
            />

            <TableListSection
              id="owners"
              title="Owners"
              description="GitHub users/organizations to monitor for new repositories."
              field={OWNERS_FIELD}
              items={ownersDraft}
              onItemsChange={setOwnersDraft}
              modified={ownersModified}
              onSave={handleSaveOwners}
              saving={savingOwners}
            />
          </main>
        </div>

        <div className="mt-4 flex items-center gap-2 text-sm">
          <span
            className={cn(
              "inline-flex items-center gap-1.5",
              isModified || reposModified || ownersModified
                ? "text-warning-600 dark:text-warning-500"
                : "text-success-600 dark:text-success-500",
            )}
          >
            {isModified || reposModified || ownersModified ? (
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
