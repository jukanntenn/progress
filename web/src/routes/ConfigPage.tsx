import { useEffect, useMemo, useState } from 'react'
import { useTranslation } from 'react-i18next'
import { useBlocker } from 'react-router'
import { RotateCcw, Save, Check, AlertCircle, RefreshCw, Send } from 'lucide-react'
import { PageContainer } from '@/components/PageContainer'
import { Card, CardContent } from '@/components/ui/Card'
import { Button } from '@/components/ui/Button'
import { Skeleton } from '@/components/ui/Skeleton'
import { Spinner } from '@/components/ui/Spinner'
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle,
} from '@/components/ui/Dialog'
import { ConfigSections } from '@/components/config/ConfigSections'
import { SectionNav } from '@/components/config/SectionNav'
import { adaptSectionSchema, type FieldGroup } from '@/lib/config/schemaAdapter'
import { useScrollSpy } from '@/hooks/useScrollSpy'
import { useToast } from '@/components/providers/useToast'
import { changeLocale } from '@/i18n'
import { cn } from '@/lib/utils'
import { $api } from '@/api/client'

type JsonSchema = Record<string, unknown>

interface SectionState {
  name: string
  title: string
  groups: FieldGroup[]
  draft: Record<string, unknown>
  saved: Record<string, unknown>
}

export default function ConfigPage() {
  const { t } = useTranslation()
  const { toast } = useToast()

  const configQuery = $api.useQuery('get', '/api/v1/config')
  const schemaQuery = $api.useQuery('get', '/api/v1/config/schema')
  const reloadMutation = $api.useMutation('post', '/api/v1/config/reload')
  const updateMutation = $api.useMutation('put', '/api/v1/config/{section}')
  const testMutation = $api.useMutation('post', '/api/v1/config/notifications/test')

  const [sections, setSections] = useState<SectionState[]>([])
  const [savingSection, setSavingSection] = useState<string | null>(null)
  const [validationError, setValidationError] = useState<{ section: string; error: string } | null>(
    null,
  )
  const [resetTarget, setResetTarget] = useState<SectionState | null>(null)

  const isDirty = (s: SectionState) => JSON.stringify(s.draft) !== JSON.stringify(s.saved)
  const anyDirty = sections.some(isDirty)

  // Block in-app navigation when there are unsaved changes; the leave dialog
  // (rendered below) lets the user confirm or cancel. useBlocker from
  // react-router v8 powers this without window.confirm.
  const blocker = useBlocker(() => anyDirty)

  // Rebuild section state whenever config + schema data arrive.
  useEffect(() => {
    if (!configQuery.data || !schemaQuery.data?.schemas) return
    const coreData = configQuery.data.core ?? {}
    const plugins = configQuery.data.plugins ?? {}
    const schemas = schemaQuery.data.schemas as Record<string, JsonSchema>
    const next: SectionState[] = []
    const buildSection = (name: string, title: string, data: Record<string, unknown>) => {
      const schema = schemas[name]
      if (!schema) return
      next.push({
        name,
        title,
        groups: adaptSectionSchema(name, schema),
        draft: data,
        saved: data,
      })
    }
    buildSection('core', t('config.coreSection'), coreData)
    for (const [name, data] of Object.entries(plugins)) {
      buildSection(name, `${t('config.pluginsSection')}: ${name}`, data as Record<string, unknown>)
    }
    // Schema-driven: add sections for integrations that have schemas but no DB data yet
    for (const name of Object.keys(schemas)) {
      if (name === 'core' || name in plugins) continue
      buildSection(name, `${t('config.pluginsSection')}: ${name}`, {})
    }
    setSections(next)
  }, [configQuery.data, schemaQuery.data, t])

  const navSections = useMemo(
    () =>
      sections
        .filter((s) => s.groups.length > 0)
        .flatMap((s) => s.groups.map((g) => ({ id: `${s.name}__${g.name}`, title: g.label }))),
    [sections],
  )
  const activeSection = useScrollSpy(navSections.map((s) => s.id))

  const handleSectionClick = (id: string) => {
    document.getElementById(id)?.scrollIntoView({ behavior: 'smooth', block: 'start' })
  }

  const updateDraft = (sectionName: string, next: Record<string, unknown>) => {
    setSections((prev) => prev.map((s) => (s.name === sectionName ? { ...s, draft: next } : s)))
  }

  const handleSave = async (section: SectionState) => {
    setSavingSection(section.name)
    try {
      await updateMutation.mutateAsync({
        params: { path: { section: section.name } },
        body: { data: section.draft },
      })
      setSections((prev) =>
        prev.map((s) => (s.name === section.name ? { ...s, saved: s.draft } : s)),
      )
      // When the core section's language changes, sync the running SPA so the
      // UI switches immediately instead of waiting for a reload — and persist
      // it to localStorage so it survives the next boot (matches the switcher).
      if (section.name === 'core') {
        const before = (section.saved.language as string) ?? ''
        const after = (section.draft.language as string) ?? ''
        if (after && before !== after) {
          changeLocale(after)
        }
      }
      toast({ title: t('config.saved'), variant: 'success' })
    } catch (e) {
      const err = e as { message?: string; detail?: string }
      setValidationError({
        section: section.name,
        error: err.detail ?? err.message ?? t('config.saveFailed'),
      })
      toast({ title: t('config.saveFailed'), variant: 'error' })
    } finally {
      setSavingSection(null)
    }
  }

  const handleReset = (section: SectionState) => {
    setResetTarget(section)
  }

  const confirmReset = () => {
    if (resetTarget) {
      const target = resetTarget
      setSections((prev) =>
        prev.map((s) => (s.name === target.name ? { ...s, draft: s.saved } : s)),
      )
    }
    setResetTarget(null)
  }

  const handleReload = async () => {
    try {
      await reloadMutation.mutateAsync({})
      toast({ title: t('config.reloaded'), variant: 'success' })
      void configQuery.refetch()
    } catch (e) {
      const err = e as { message?: string }
      toast({
        title: t('config.reloadFailed'),
        description: err.message ?? '',
        variant: 'error',
      })
    }
  }

  const handleTestNotifications = async () => {
    try {
      const data = await testMutation.mutateAsync({})
      if (!data) return
      if (data.summary === 'no_channels') {
        toast({ title: t('config.testNoChannels'), variant: 'info' })
      } else if (data.summary === 'ok') {
        toast({ title: t('config.testSuccess'), variant: 'success' })
      } else {
        const failed = data.results
          .filter((r) => !r.ok)
          .map((r) => `${r.channel}: ${r.error ?? ''}`)
          .join('; ')
        toast({ title: t('config.testPartialFailure'), description: failed, variant: 'error' })
      }
    } catch (e) {
      const err = e as { message?: string }
      toast({
        title: t('config.testFailed'),
        description: err.message ?? '',
        variant: 'error',
      })
    }
  }

  const isPending = configQuery.isPending || schemaQuery.isPending

  if (isPending) {
    return (
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
    )
  }

  if (configQuery.error || schemaQuery.error) {
    return (
      <PageContainer size="medium">
        <Card>
          <CardContent className="py-12 text-center">
            <AlertCircle className="text-destructive mx-auto mb-3 h-8 w-8" />
            <p className="text-destructive font-medium">{t('config.loadFailed')}</p>
          </CardContent>
        </Card>
      </PageContainer>
    )
  }

  return (
    <PageContainer size="medium">
      <div className="mb-6 flex flex-col gap-4 sm:flex-row sm:items-center sm:justify-between">
        <div>
          <h1 className="text-foreground text-xl font-bold">{t('config.title')}</h1>
          <p className="text-muted-foreground mt-1 text-sm">{t('config.description')}</p>
        </div>
        <div className="flex items-center gap-2">
          <Button
            variant="outline"
            size="sm"
            onClick={handleReload}
            disabled={reloadMutation.isPending}
          >
            <RefreshCw className={reloadMutation.isPending ? 'h-4 w-4 animate-spin' : 'h-4 w-4'} />
            {t('config.reload')}
          </Button>
          <Button
            variant="outline"
            size="sm"
            onClick={handleTestNotifications}
            disabled={testMutation.isPending}
          >
            {testMutation.isPending ? (
              <Spinner className="h-4 w-4" />
            ) : (
              <Send className="h-4 w-4" />
            )}
            {t('config.testNotification')}
          </Button>
        </div>
      </div>

      {/* Mobile: horizontal-scrolling section chips strip (desktop nav is below). */}
      <div className="-mx-4 mb-4 flex gap-2 overflow-x-auto px-4 pb-2 lg:hidden">
        {navSections.map((section) => (
          <button
            key={section.id}
            type="button"
            onClick={() => handleSectionClick(section.id)}
            className={cn(
              'flex-shrink-0 rounded-full border px-3 py-1.5 text-xs font-medium whitespace-nowrap transition-colors',
              activeSection === section.id
                ? 'bg-primary/10 border-primary/30 text-primary'
                : 'border-border text-muted-foreground hover:bg-accent',
            )}
          >
            {section.title}
          </button>
        ))}
      </div>

      <div className="grid grid-cols-1 gap-6 lg:grid-cols-[220px_1fr]">
        <aside className="hidden lg:block">
          <div className="sticky top-24">
            <div className="text-foreground mb-3 text-sm font-semibold">{t('config.sections')}</div>
            <SectionNav
              sections={navSections}
              activeSection={activeSection}
              onSectionClick={handleSectionClick}
            />
          </div>
        </aside>

        <main className="space-y-10">
          {sections.map((section) => {
            if (section.groups.length === 0) return null
            const modified = JSON.stringify(section.draft) !== JSON.stringify(section.saved)
            const saving = savingSection === section.name
            return (
              <div key={section.name} className="space-y-4">
                <div className="flex items-center justify-between">
                  <h2 className="text-muted-foreground font-mono text-sm font-semibold tracking-wide uppercase">
                    {section.title}
                  </h2>
                  <div className="flex items-center gap-2">
                    <Button
                      variant="outline"
                      size="sm"
                      type="button"
                      onClick={() => handleReset(section)}
                      disabled={!modified}
                    >
                      <RotateCcw className="h-4 w-4" />
                      {t('config.reset')}
                    </Button>
                    <Button
                      size="sm"
                      type="button"
                      onClick={() => handleSave(section)}
                      disabled={!modified || saving}
                    >
                      <Save className="h-4 w-4" />
                      {saving ? t('common.loading') : t('config.save')}
                    </Button>
                  </div>
                </div>

                <ConfigSections
                  sectionName={section.name}
                  sections={section.groups}
                  configDraft={section.draft}
                  onConfigChange={(next) => updateDraft(section.name, next)}
                />

                <div
                  className={cn(
                    'flex items-center gap-1.5 text-sm',
                    modified ? 'text-warning' : 'text-success',
                  )}
                >
                  {modified ? (
                    <>
                      <span className="bg-warning h-2 w-2 animate-pulse rounded-full" />
                      {t('config.unsavedChanges')}
                    </>
                  ) : (
                    <>
                      <Check className="h-4 w-4" />
                      {t('config.noChanges')}
                    </>
                  )}
                </div>
              </div>
            )
          })}
        </main>
      </div>

      <Dialog
        open={validationError !== null}
        onOpenChange={(open) => !open && setValidationError(null)}
      >
        <DialogContent>
          <DialogHeader>
            <DialogTitle>{t('config.validationErrors')}</DialogTitle>
          </DialogHeader>
          <pre className="bg-muted text-foreground max-h-[60vh] overflow-auto rounded-lg p-4 text-sm break-words whitespace-pre-wrap">
            {validationError?.error}
          </pre>
        </DialogContent>
      </Dialog>

      <Dialog open={resetTarget !== null} onOpenChange={(open) => !open && setResetTarget(null)}>
        <DialogContent>
          <DialogHeader>
            <DialogTitle>{t('config.resetTitle')}</DialogTitle>
            <DialogDescription>{t('config.resetConfirm')}</DialogDescription>
          </DialogHeader>
          <DialogFooter>
            <Button variant="outline" onClick={() => setResetTarget(null)}>
              {t('common.cancel')}
            </Button>
            <Button variant="destructive" onClick={confirmReset}>
              {t('config.reset')}
            </Button>
          </DialogFooter>
        </DialogContent>
      </Dialog>

      <Dialog
        open={blocker.state === 'blocked'}
        onOpenChange={(open) => !open && blocker.reset?.()}
      >
        <DialogContent>
          <DialogHeader>
            <DialogTitle>{t('config.leaveTitle')}</DialogTitle>
            <DialogDescription>{t('config.leaveDescription')}</DialogDescription>
          </DialogHeader>
          <DialogFooter>
            <Button variant="outline" onClick={() => blocker.reset?.()}>
              {t('common.cancel')}
            </Button>
            <Button variant="destructive" onClick={() => blocker.proceed?.()}>
              {t('config.confirmLeave')}
            </Button>
          </DialogFooter>
        </DialogContent>
      </Dialog>
    </PageContainer>
  )
}
