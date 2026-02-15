import { Button } from '@/components/ui/button'
import { Card, CardContent, CardHeader } from '@/components/ui/card'
import VisualConfigEditor from '@/components/config/VisualConfigEditor'
import { Dialog } from '@/components/ui/dialog'
import { Tabs, TabsContent, TabsList, TabsTrigger } from '@/components/ui/tabs'
import { Textarea } from '@/components/ui/textarea'
import { useToast } from '@/components/ui/toast'
import {
  saveConfigData,
  saveConfigToml,
  useConfig,
  useConfigSchema,
  validateConfig,
  validateConfigData,
} from '@/hooks/api'
import { useEffect, useState } from 'react'
import { Link } from 'react-router-dom'

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
      <div className="mx-auto my-8 max-w-6xl px-8 py-10">
        <p className="text-gray-600 dark:text-gray-400">Loading...</p>
      </div>
    )
  }

  if (error) {
    return (
      <div className="mx-auto my-8 max-w-6xl px-8 py-10">
        <Card>
          <CardContent>
            <p className="text-red-500">Failed to load configuration</p>
            <Link
              to="/"
              className="text-blue-600 hover:underline dark:text-blue-400"
            >
              Back to list
            </Link>
          </CardContent>
        </Card>
      </div>
    )
  }

  return (
    <div className="mx-auto my-8 max-w-6xl px-8 py-10 lg:my-10">
      <Card>
        <CardHeader>
          <div className="flex items-center justify-between">
            <Link to="/" className="text-xl font-bold text-gray-900 dark:text-white">
              Progress
            </Link>
            <div className="flex items-center gap-3">
              {tab === 'toml' && (
                <>
                  <Button variant="outline" onClick={handleResetToml}>
                    Reset
                  </Button>
                  <Button onClick={handleSaveToml} disabled={!isTomlModified || isSaving}>
                    {isSaving ? 'Saving...' : 'Save'}
                  </Button>
                </>
              )}
            </div>
          </div>
        </CardHeader>
        <CardContent>
          <div className="mb-4">
            <h2 className="mb-2 text-lg font-semibold text-gray-900 dark:text-white">
              Configuration Editor
            </h2>
            <p className="text-sm text-gray-600 dark:text-gray-400">
              Path: {data?.path}
            </p>
          </div>

          <Tabs value={tab} onValueChange={(v) => setTab(v as 'visual' | 'toml')}>
            <TabsList className="mb-6">
              <TabsTrigger value="visual">Visual</TabsTrigger>
              <TabsTrigger value="toml">TOML</TabsTrigger>
            </TabsList>

            <TabsContent value="visual">
              {schemaLoading && (
                <p className="text-gray-600 dark:text-gray-400">Loading schema...</p>
              )}
              {schemaError && (
                <p className="text-red-500">Failed to load config schema</p>
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
                className="h-[calc(100vh-340px)]"
                spellCheck={false}
              />
              <div className="mt-4 flex items-center gap-2 text-sm">
                <span className={`h-2 w-2 rounded-full ${isTomlModified ? 'bg-yellow-500' : 'bg-green-500'}`} />
                <span className="text-gray-600 dark:text-gray-400">
                  {isTomlModified ? 'Unsaved changes' : 'No changes'}
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
        <pre className="whitespace-pre-wrap break-words text-sm text-gray-900 dark:text-gray-100">
          {validationError}
        </pre>
      </Dialog>
    </div>
  )
}
