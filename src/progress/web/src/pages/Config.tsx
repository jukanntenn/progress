import { Card, CardContent, CardHeader } from '@/components/ui/card'
import VisualConfigEditor from '@/components/config/VisualConfigEditor'
import { Dialog } from '@/components/ui/dialog'
import { Tabs, TabsContent, TabsList, TabsTrigger } from '@/components/ui/tabs'
import { Textarea } from '@/components/ui/textarea'
import { useToast } from '@/components/ui/toast'
import { Skeleton } from '@/components/ui/skeleton'
import { Button } from '@/components/ui/button'
import { Header, PageContainer } from '@/components/layout'
import {
  saveConfigData,
  saveConfigToml,
  useConfig,
  useConfigSchema,
  validateConfig,
  validateConfigData,
} from '@/hooks/api'
import { useEffect, useState } from 'react'
import { RotateCcw, Save, Check, AlertCircle, FileCode, Settings2 } from 'lucide-react'

export default function Config() {
  const { data, error, isLoading, mutate } = useConfig()
  const { data: schema, error: schemaError, isLoading: schemaLoading } = useConfigSchema()
  const [tomlContent, setTomlContent] = useState('')
  const [tab, setTab] = useState<'visual' | 'toml'>('visual')
  const [isTomlModified, setIsTomlModified] = useState(false)
  const [isSaving, setIsSaving] = useState(false)
  const [configDraft, setConfigDraft] = useState<Record<string, unknown>>({})
  const [validationError, setValidationError] = useState<string | null>(null)
  const [showValidationDialog, setShowValidationDialog] = useState(false)
  const { showToast } = useToast()

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
        <PageContainer size="wide">
          <Card>
            <CardHeader className="border-b border-border/30">
              <div className="flex items-center justify-between">
                <Skeleton className="h-7 w-48" />
                <div className="flex gap-2">
                  <Skeleton className="h-9 w-20" />
                  <Skeleton className="h-9 w-24" />
                </div>
              </div>
            </CardHeader>
            <CardContent className="py-6">
              <div className="space-y-4">
                <Skeleton className="h-10 w-48" />
                <Skeleton className="h-96 w-full" />
              </div>
            </CardContent>
          </Card>
        </PageContainer>
      </>
    )
  }

  if (error) {
    return (
      <>
        <Header />
        <PageContainer size="wide">
          <Card>
            <CardContent className="py-12 text-center">
              <div className="text-error mb-4 text-lg font-medium">Failed to load configuration</div>
              <p className="text-muted-foreground">Unable to load the configuration file.</p>
            </CardContent>
          </Card>
        </PageContainer>
      </>
    )
  }

  return (
    <>
      <Header />
      <PageContainer size="wide">
        <Card>
          <CardHeader className="border-b border-border/30">
            <div className="flex flex-col sm:flex-row sm:items-center sm:justify-between gap-4">
              <div>
                <h1 className="text-xl font-bold text-foreground">Configuration Editor</h1>
                <p className="text-sm text-muted-foreground mt-1">{data?.path}</p>
              </div>

              {tab === 'toml' && (
                <div className="flex items-center gap-2">
                  <Button
                    variant="outline"
                    size="sm"
                    onClick={handleResetToml}
                    leftIcon={<RotateCcw className="h-4 w-4" />}
                  >
                    Reset
                  </Button>
                  <Button
                    size="sm"
                    onClick={handleSaveToml}
                    disabled={!isTomlModified || isSaving}
                    loading={isSaving}
                    leftIcon={<Save className="h-4 w-4" />}
                  >
                    {isSaving ? 'Saving...' : 'Save'}
                  </Button>
                </div>
              )}
            </div>
          </CardHeader>

          <CardContent className="py-6">
            <Tabs value={tab} onValueChange={(v) => setTab(v as 'visual' | 'toml')}>
              <TabsList className="mb-6">
                <TabsTrigger value="visual">
                  <Settings2 className="h-4 w-4 mr-2" />
                  Visual
                </TabsTrigger>
                <TabsTrigger value="toml">
                  <FileCode className="h-4 w-4 mr-2" />
                  TOML
                </TabsTrigger>
              </TabsList>

              <TabsContent value="visual">
                {schemaLoading && (
                  <div className="space-y-4 animate-pulse">
                    <Skeleton className="h-4 w-32" />
                    <Skeleton className="h-10 w-full" />
                    <Skeleton className="h-10 w-full" />
                    <Skeleton className="h-10 w-full" />
                  </div>
                )}
                {schemaError && (
                  <div className="py-8 text-center">
                    <AlertCircle className="h-8 w-8 text-error mx-auto mb-3" />
                    <p className="text-error font-medium">Failed to load config schema</p>
                  </div>
                )}
                {schema && (
                  <VisualConfigEditor
                    schema={schema}
                    configDraft={configDraft}
                    onConfigChange={setConfigDraft}
                    onSave={handleSaveVisual}
                    onValidate={handleValidateVisual}
                    isSaving={isSaving}
                    isModified={isVisualModified}
                  />
                )}
              </TabsContent>

              <TabsContent value="toml">
                <Textarea
                  value={tomlContent}
                  onChange={(e) => handleTomlChange(e.target.value)}
                  className="h-[calc(100vh-340px)] min-h-[400px] font-mono text-sm"
                  spellCheck={false}
                />
                <div className="mt-4 flex items-center gap-2 text-sm">
                  <span
                    className={`inline-flex items-center gap-1.5 ${
                      isTomlModified
                        ? 'text-warning-600 dark:text-warning-500'
                        : 'text-success-600 dark:text-success-500'
                    }`}
                  >
                    {isTomlModified ? (
                      <>
                        <span className="h-2 w-2 rounded-full bg-warning-500 animate-pulse" />
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
              </TabsContent>
            </Tabs>
          </CardContent>
        </Card>

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
