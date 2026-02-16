import { Dialog } from '@/components/ui/dialog'
import { Textarea } from '@/components/ui/textarea'
import { useToast } from '@/components/ui/toast'
import { Skeleton } from '@/components/ui/skeleton'
import { Button } from '@/components/ui/button'
import { Header, PageContainer } from '@/components/layout'
import { SectionNav } from '@/components/config/SectionNav'
import { ConfigSections } from '@/components/config/ConfigSections'
import {
  saveConfigData,
  saveConfigToml,
  useConfig,
  useConfigSchema,
  validateConfig,
  validateConfigData,
} from '@/hooks/api'
import { useScrollSpy } from '@/hooks/useScrollSpy'
import { cn } from '@/lib/utils'
import { useEffect, useMemo, useState } from 'react'
import { RotateCcw, Save, Check, AlertCircle, FileCode, Settings2 } from 'lucide-react'

export default function Config() {
  const { data, error, isLoading, mutate } = useConfig()
  const { data: schema, error: schemaError, isLoading: schemaLoading } = useConfigSchema()
  const [tomlContent, setTomlContent] = useState('')
  const [editorMode, setEditorMode] = useState<'visual' | 'toml'>('visual')
  const [isTomlModified, setIsTomlModified] = useState(false)
  const [isSaving, setIsSaving] = useState(false)
  const [configDraft, setConfigDraft] = useState<Record<string, unknown>>({})
  const [validationError, setValidationError] = useState<string | null>(null)
  const [showValidationDialog, setShowValidationDialog] = useState(false)
  const { showToast } = useToast()

  const sectionIds = useMemo(() => schema?.sections.map((s) => s.id) ?? [], [schema?.sections])
  const activeSection = useScrollSpy(editorMode === 'visual' ? sectionIds : [])

  useEffect(() => {
    if (data?.toml) {
      setTomlContent(data.toml)
      setIsTomlModified(false)
    }
    if (data?.data) {
      setConfigDraft(data.data as Record<string, unknown>)
    }
  }, [data?.toml, data?.data])

  const handleTomlChange = (value: string) => {
    setTomlContent(value)
    setIsTomlModified(value !== (data?.toml || ''))
  }

  const handleSaveToml = async () => {
    setIsSaving(true)
    try {
      const validation = await validateConfig(tomlContent)
      if (!validation.success) {
        setValidationError(validation.error || 'Unknown validation error')
        setShowValidationDialog(true)
        showToast('Validation failed', 'error')
        return
      }

      const result = await saveConfigToml(tomlContent)
      if (result.success) {
        showToast('Configuration saved successfully!', 'success')
        setIsTomlModified(false)
        mutate()
      } else {
        showToast('Save failed: ' + (result.error || ''), 'error')
      }
    } catch (e) {
      showToast('Save error: ' + (e as Error).message, 'error')
    } finally {
      setIsSaving(false)
    }
  }

  const handleResetToml = () => {
    if (window.confirm('Reset to original configuration? Unsaved changes will be lost.')) {
      setTomlContent(data?.toml || '')
      setIsTomlModified(false)
    }
  }

  const isVisualModified =
    JSON.stringify(configDraft) !== JSON.stringify((data?.data || {}) as Record<string, unknown>)

  const handleResetVisual = () => {
    if (window.confirm('Reset to original configuration? Unsaved changes will be lost.')) {
      setConfigDraft((data?.data || {}) as Record<string, unknown>)
    }
  }

  const handleValidateVisual = async () => {
    try {
      const validation = await validateConfigData(configDraft)
      if (!validation.success) {
        setValidationError(validation.error || 'Unknown validation error')
        setShowValidationDialog(true)
        showToast('Validation failed', 'error')
        return
      }
      showToast('Configuration is valid', 'success')
    } catch (e) {
      showToast('Validation error: ' + (e as Error).message, 'error')
    }
  }

  const handleValidateToml = async () => {
    try {
      const validation = await validateConfig(tomlContent)
      if (!validation.success) {
        setValidationError(validation.error || 'Unknown validation error')
        setShowValidationDialog(true)
        showToast('Validation failed', 'error')
        return
      }
      showToast('Configuration is valid', 'success')
    } catch (e) {
      showToast('Validation error: ' + (e as Error).message, 'error')
    }
  }

  const handleSaveVisual = async () => {
    setIsSaving(true)
    try {
      const validation = await validateConfigData(configDraft)
      if (!validation.success) {
        setValidationError(validation.error || 'Unknown validation error')
        setShowValidationDialog(true)
        showToast('Validation failed', 'error')
        return
      }

      const result = await saveConfigData(configDraft)
      if (result.success) {
        showToast('Configuration saved successfully!', 'success')
        mutate()
      } else {
        showToast('Save failed: ' + (result.error || ''), 'error')
      }
    } catch (e) {
      showToast('Save error: ' + (e as Error).message, 'error')
    } finally {
      setIsSaving(false)
    }
  }

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
    )
  }

  if (error) {
    return (
      <>
        <Header />
        <PageContainer size="medium">
          <div className="py-12 text-center">
            <div className="text-error mb-4 text-lg font-medium">Failed to load configuration</div>
            <p className="text-muted-foreground">Unable to load the configuration file.</p>
          </div>
        </PageContainer>
      </>
    )
  }

  const handleSectionClick = (sectionId: string) => {
    const el = document.getElementById(sectionId)
    if (el) {
      el.scrollIntoView({ behavior: 'smooth', block: 'start' })
    }
  }

  return (
    <>
      <Header />
      <PageContainer size="medium">
        <div className="mb-6">
          <div className="flex flex-col gap-4 sm:flex-row sm:items-center sm:justify-between">
            <div>
              <h1 className="text-xl font-bold text-foreground">Configuration Editor</h1>
              <p className="mt-1 text-sm text-muted-foreground">{data?.path}</p>
            </div>

            <div className="flex items-center gap-2">
              <Button
                variant="ghost"
                size="icon-sm"
                type="button"
                onClick={() => setEditorMode((m) => (m === 'visual' ? 'toml' : 'visual'))}
                title={editorMode === 'visual' ? 'Switch to TOML editor' : 'Switch to Visual editor'}
              >
                {editorMode === 'visual' ? (
                  <FileCode className="h-4 w-4" />
                ) : (
                  <Settings2 className="h-4 w-4" />
                )}
              </Button>

              <Button
                variant="outline"
                size="sm"
                type="button"
                onClick={editorMode === 'visual' ? handleResetVisual : handleResetToml}
                leftIcon={<RotateCcw className="h-4 w-4" />}
              >
                Reset
              </Button>

              <Button
                variant="outline"
                size="sm"
                type="button"
                onClick={editorMode === 'visual' ? handleValidateVisual : handleValidateToml}
              >
                Validate
              </Button>

              <Button
                size="sm"
                type="button"
                onClick={editorMode === 'visual' ? handleSaveVisual : handleSaveToml}
                disabled={editorMode === 'visual' ? !isVisualModified || isSaving : !isTomlModified || isSaving}
                loading={isSaving}
                leftIcon={<Save className="h-4 w-4" />}
              >
                {isSaving ? 'Saving...' : 'Save'}
              </Button>
            </div>
          </div>
        </div>

        {editorMode === 'visual' ? (
          <div className="grid grid-cols-1 gap-6 lg:grid-cols-[220px_1fr]">
            <aside className="hidden lg:block">
              <div className="sticky top-24">
                <div className="mb-3 text-sm font-semibold text-foreground">Sections</div>
                {schema && (
                  <SectionNav
                    sections={schema.sections}
                    activeSection={activeSection}
                    onSectionClick={handleSectionClick}
                  />
                )}
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
              {schema && (
                <ConfigSections
                  sections={schema.sections}
                  configDraft={configDraft}
                  onConfigChange={setConfigDraft}
                />
              )}
            </main>
          </div>
        ) : (
          <div>
            <Textarea
              value={tomlContent}
              onChange={(e) => handleTomlChange(e.target.value)}
              className="h-[calc(100vh-280px)] min-h-[400px] font-mono text-sm"
              spellCheck={false}
            />
            <div className="mt-4 flex items-center gap-2 text-sm">
              <span
                className={cn(
                  'inline-flex items-center gap-1.5',
                  isTomlModified
                    ? 'text-warning-600 dark:text-warning-500'
                    : 'text-success-600 dark:text-success-500',
                )}
              >
                {isTomlModified ? (
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
          </div>
        )}

        <Dialog
          open={showValidationDialog}
          onClose={() => setShowValidationDialog(false)}
          title="Validation Errors"
        >
          <pre className="whitespace-pre-wrap break-words text-sm text-foreground bg-muted p-4 rounded-lg overflow-auto max-h-[60vh]">
            {validationError}
          </pre>
        </Dialog>
      </PageContainer>
    </>
  )
}
