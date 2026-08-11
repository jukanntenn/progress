import { useCallback, useEffect, useMemo, useRef, useState } from 'react'
import { useBlocker, useOutletContext, useParams } from 'react-router'
import { useTranslation } from 'react-i18next'
import { Check, PanelLeft, RefreshCw, RotateCcw, Save, Send } from 'lucide-react'
import Form from '@rjsf/core'
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
import { ConfigForm } from '@/components/config/ConfigForm'
import { mergeInitialData } from '@/lib/rjsf-theme/mergeInitialData'
import { useToast } from '@/components/providers/useToast'
import { changeLocale } from '@/i18n'
import type { SettingsOutletContext } from './SettingsLayout'
import { cn } from '@/lib/utils'
import { $api } from '@/api/client'

type JsonSchema = Record<string, unknown>

/**
 * Server 422 detail lines look like "  - github.gh_token: Input should be a
 * valid string". Parse them into RJSF extraErrors so each message lands on
 * its field. Unparseable lines surface in the top error list instead.
 */
// eslint-disable-next-line react-refresh/only-export-components
export function parseServerErrors(detail: string): {
  extraErrors: Record<string, unknown>
  general: string[]
} {
  const extraErrors: Record<string, unknown> = {}
  const general: string[] = []
  for (const line of detail.split('\n')) {
    const match = line.match(/^\s*-\s+([\w.]+):\s+(.+)$/)
    if (match) {
      const path = (match[1] as string).split('.')
      let node: Record<string, unknown> = extraErrors
      for (const segment of path) {
        const existing = node[segment]
        if (typeof existing !== 'object' || existing === null) {
          node[segment] = {}
        }
        node = node[segment] as Record<string, unknown>
      }
      node.__errors = [match[2]]
    } else if (line.trim()) {
      general.push(line.trim())
    }
  }
  return { extraErrors, general }
}

/**
 * Unwrap the backend error envelope ("{error: {code, message, details}}",
 * spec 12) plus the raw network Error into the human-readable detail string.
 */
// eslint-disable-next-line react-refresh/only-export-components
export function extractServerDetail(e: unknown): string | null {
  if (typeof e === 'string' && e) return e
  const envelope = e as { error?: { message?: string }; message?: string; detail?: string } | null
  if (envelope?.error?.message) return envelope.error.message
  if (envelope?.detail) return envelope.detail
  if (envelope?.message) return envelope.message
  return null
}

function errorSchemaFor(lines: string[]): Record<string, unknown> {
  const detail = lines.join('\n')
  return parseServerErrors(detail).extraErrors
}

export function SettingsConfigSection() {
  const { t } = useTranslation()
  const { toast } = useToast()
  const { section: sectionName } = useParams<{ section: string }>()
  const { currentLabel, onOpenDrawer } = useOutletContext<SettingsOutletContext>()
  const formRef = useRef<Form>(null)

  const configQuery = $api.useQuery('get', '/api/v1/config')
  const schemaQuery = $api.useQuery('get', '/api/v1/config/schema')
  const reloadMutation = $api.useMutation('post', '/api/v1/config/reload')
  const updateMutation = $api.useMutation('put', '/api/v1/config/{section}')
  const testMutation = $api.useMutation('post', '/api/v1/config/notifications/test')

  const schema = useMemo(() => {
    const schemas = schemaQuery.data?.schemas as Record<string, JsonSchema> | undefined
    return (schemas?.[sectionName ?? ''] ?? null) as JsonSchema | null
  }, [schemaQuery.data, sectionName])

  const serverData = useMemo(() => {
    if (!configQuery.data) return null
    return (
      sectionName === 'core'
        ? configQuery.data.core
        : (configQuery.data.plugins?.[sectionName ?? ''] ?? {})
    ) as Record<string, unknown>
  }, [configQuery.data, sectionName])

  const initialData = useMemo(() => {
    if (!schema || !serverData) return null
    return mergeInitialData(schema as never, serverData)
  }, [schema, serverData])

  const [liveData, setLiveData] = useState<Record<string, unknown> | null>(null)
  const [baseline, setBaseline] = useState<Record<string, unknown> | null>(null)
  const [saving, setSaving] = useState(false)
  const [serverErrors, setServerErrors] = useState<string[]>([])
  const [confirmReset, setConfirmReset] = useState(false)

  useEffect(() => {
    if (initialData) {
      setLiveData(initialData)
      setBaseline(initialData)
    }
  }, [initialData])

  const isDirty = useMemo(() => {
    if (!liveData || !baseline) return false
    return JSON.stringify(liveData) !== JSON.stringify(baseline)
  }, [liveData, baseline])

  const blocker = useBlocker(useCallback(() => isDirty, [isDirty]))
  const leaveBlocked = blocker.state === 'blocked'

  const confirmLeaveAction = () => {
    blocker.proceed?.()
  }

  const handleSave = () => {
    formRef.current?.submit()
  }

  const handleSubmit = async (data: Record<string, unknown>) => {
    if (!sectionName) return
    setSaving(true)
    setServerErrors([])
    try {
      const saved = await updateMutation.mutateAsync({
        params: { path: { section: sectionName } },
        body: { data },
      })
      const normalized = (saved.data ?? {}) as Record<string, unknown>
      setLiveData(normalized)
      setBaseline(normalized)
      setServerErrors([])
      if (sectionName === 'core') {
        const before = (initialData?.language as string) ?? ''
        const after = (normalized.language as string) ?? ''
        if (after && before !== after) changeLocale(after)
      }
      toast({ title: t('config.saved'), variant: 'success' })
    } catch (e) {
      const message = extractServerDetail(e) ?? t('config.saveFailed')
      const { extraErrors } = parseServerErrors(message)
      setServerErrors([message])
      if (Object.keys(extraErrors).length === 0) {
        toast({ title: t('config.saveFailed'), variant: 'error' })
      }
    } finally {
      setSaving(false)
    }
  }

  const confirmResetAction = () => {
    if (baseline) setLiveData(baseline)
    setServerErrors([])
    setConfirmReset(false)
  }

  const handleReload = async () => {
    try {
      await reloadMutation.mutateAsync({})
      toast({ title: t('config.reloaded'), variant: 'success' })
      void configQuery.refetch()
    } catch (e) {
      const err = e as { message?: string }
      toast({ title: t('config.reloadFailed'), description: err.message ?? '', variant: 'error' })
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
      toast({ title: t('config.testFailed'), description: err.message ?? '', variant: 'error' })
    }
  }

  const isPending = configQuery.isPending || schemaQuery.isPending

  if (isPending) {
    return (
      <div className="space-y-4">
        <Skeleton className="h-7 w-48" />
        <div className="flex gap-2">
          <Skeleton className="h-9 w-20" />
          <Skeleton className="h-9 w-24" />
        </div>
        <Skeleton className="h-96 w-full" />
      </div>
    )
  }

  if (!schema || !initialData || !sectionName) {
    return (
      <div className="py-12 text-center">
        <p className="text-muted-foreground text-sm">{t('config.loadFailed')}</p>
      </div>
    )
  }

  const PLUGIN_SECTIONS = ['repo', 'changelog', 'proposal', 'feed']
  const isPlugin = sectionName ? PLUGIN_SECTIONS.includes(sectionName) : false
  const sectionLabel = isPlugin
    ? (sectionName ?? '')
    : sectionName
      ? t(`settings.nav.${sectionName}`)
      : ''

  return (
    <div className="space-y-4">
      <div className="glass-card border-border sticky top-14 z-20 mb-2 flex items-center justify-between gap-2 rounded-xl border px-6 py-3">
        <div className="flex min-w-0 items-center gap-2">
          <h2 className="text-foreground hidden text-sm font-semibold capitalize lg:block">
            {sectionLabel}
          </h2>
          <button
            type="button"
            onClick={onOpenDrawer}
            className="text-foreground hover:bg-accent/10 flex items-center gap-1.5 rounded-lg text-sm font-semibold capitalize lg:hidden"
          >
            <PanelLeft className="h-4 w-4" />
            <span className="truncate">{currentLabel}</span>
          </button>
          <span
            className={cn(
              'flex items-center gap-1 text-xs',
              isDirty ? 'text-warning' : 'text-success',
            )}
          >
            {isDirty ? (
              <>
                <span className="bg-warning h-2 w-2 animate-pulse rounded-full" />
                {t('config.unsavedChanges')}
              </>
            ) : (
              <>
                <Check className="h-3.5 w-3.5" />
                {t('config.noChanges')}
              </>
            )}
          </span>
        </div>
        <div className="flex items-center gap-2">
          <Button
            variant="outline"
            size="sm"
            onClick={handleReload}
            disabled={reloadMutation.isPending}
          >
            <RefreshCw className={reloadMutation.isPending ? 'h-4 w-4 animate-spin' : 'h-4 w-4'} />
            <span className="hidden sm:inline">{t('config.reload')}</span>
          </Button>
          {sectionName === 'core' && (
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
              <span className="hidden md:inline">{t('config.testNotification')}</span>
            </Button>
          )}
          <Button
            variant="outline"
            size="sm"
            onClick={() => setConfirmReset(true)}
            disabled={!isDirty}
          >
            <RotateCcw className="h-4 w-4" />
            <span className="hidden sm:inline">{t('config.reset')}</span>
          </Button>
          <Button size="sm" onClick={handleSave} disabled={!isDirty || saving}>
            <Save className="h-4 w-4" />
            {saving ? t('common.loading') : t('config.save')}
          </Button>
        </div>
      </div>

      <ConfigForm
        ref={formRef}
        sectionName={sectionName}
        schema={schema as never}
        formData={liveData ?? {}}
        extraErrors={serverErrors.length > 0 ? errorSchemaFor(serverErrors) : ({} as never)}
        onChange={(data) => {
          setLiveData(data)
          if (serverErrors.length > 0) setServerErrors([])
        }}
        onSubmit={handleSubmit}
      />

      <Dialog open={leaveBlocked} onOpenChange={(open) => !open && blocker.reset?.()}>
        <DialogContent>
          <DialogHeader>
            <DialogTitle>{t('config.leaveTitle')}</DialogTitle>
            <DialogDescription>{t('config.leaveDescription')}</DialogDescription>
          </DialogHeader>
          <DialogFooter>
            <Button variant="outline" onClick={() => blocker.reset?.()}>
              {t('common.cancel')}
            </Button>
            <Button variant="destructive" onClick={confirmLeaveAction}>
              {t('config.confirmLeave')}
            </Button>
          </DialogFooter>
        </DialogContent>
      </Dialog>

      <Dialog open={confirmReset} onOpenChange={setConfirmReset}>
        <DialogContent>
          <DialogHeader>
            <DialogTitle>{t('config.resetTitle')}</DialogTitle>
            <DialogDescription>{t('config.resetConfirm')}</DialogDescription>
          </DialogHeader>
          <DialogFooter>
            <Button variant="outline" onClick={() => setConfirmReset(false)}>
              {t('common.cancel')}
            </Button>
            <Button variant="destructive" onClick={confirmResetAction}>
              {t('config.reset')}
            </Button>
          </DialogFooter>
        </DialogContent>
      </Dialog>
    </div>
  )
}
