import { useMemo, useState } from 'react'
import { NavLink, Outlet, useLocation } from 'react-router'
import { useTranslation } from 'react-i18next'
import { ChevronRight, Settings as SettingsIcon, User } from 'lucide-react'
import { PageContainer } from '@/components/PageContainer'
import { $api } from '@/api/client'
import { cn } from '@/lib/utils'

export interface SidebarItem {
  section: string
  title: string
  group: string
  order: number
}

export interface SidebarGroup {
  id: string
  items: SidebarItem[]
  order: number
}

function humanize(key: string): string {
  return key.replace(/_/g, ' ').replace(/\b\w/g, (c) => c.toUpperCase())
}

/**
 * Build the sidebar groups from the backend JSON Schemas' ``ui_group`` /
 * ``ui_order`` annotations (single source of truth):
 *
 * - ``core``: root scalars (language/timezone) form one entry under their
 *   root-level ``ui_group``; each ``$defs`` sub-model with a ``ui_group``
 *   becomes an entry under that group (spec 4.4).
 * - plugin sections: their schema-root ``ui_group`` / ``ui_order`` drive the
 *   entry (D4 — plugin sections carry the annotation at the root, not in
 *   ``$defs``).
 *
 * Every core entry navigates to ``/settings/config/core`` (one Form per
 * section; the page renders all groups), matching the pre-refactor sidebar.
 */
// eslint-disable-next-line react-refresh/only-export-components
export function buildSidebarGroups(
  schemas: Record<string, Record<string, unknown>>,
  coreLabel: string,
): SidebarGroup[] {
  const items: SidebarItem[] = []

  const core = schemas.core
  if (core) {
    const rootScalarGroup = findRootGroup(core)
    if (rootScalarGroup) {
      items.push({
        section: 'core',
        title: coreLabel,
        group: rootScalarGroup.group,
        order: rootScalarGroup.order,
      })
    }
    for (const def of Object.values(
      (core['$defs'] as Record<string, Record<string, unknown>>) ?? {},
    )) {
      if (typeof def !== 'object' || def === null) continue
      const group = def.ui_group as string | undefined
      if (!group) continue
      items.push({
        section: 'core',
        title: humanize(
          (def.title as string | undefined)?.replace(/(Integration)?Config$/, '') ?? '',
        ),
        group,
        order: typeof def.ui_order === 'number' ? def.ui_order : 999,
      })
    }
  }

  for (const [name, schema] of Object.entries(schemas)) {
    if (name === 'core' || typeof schema !== 'object' || schema === null) continue
    const group = schema.ui_group as string | undefined
    if (!group) continue
    items.push({
      section: name,
      title: humanize(
        (schema.title as string | undefined)?.replace(/(Integration)?Config$/, '') ?? name,
      ),
      group,
      order: typeof schema.ui_order === 'number' ? schema.ui_order : 999,
    })
  }

  const byGroup = new Map<string, SidebarItem[]>()
  for (const item of items) {
    const list = byGroup.get(item.group) ?? []
    list.push(item)
    byGroup.set(item.group, list)
  }
  const groupOrder = ['preferences', 'integrations', 'notifications', 'system']
  return [...byGroup.entries()]
    .map(([id, list]) => ({
      id,
      items: [...list].sort((a, b) => a.order - b.order),
      order: groupOrder.indexOf(id) === -1 ? 99 : groupOrder.indexOf(id),
    }))
    .sort((a, b) => a.order - b.order)
}

/** The root-level ui_group of a section's own scalar properties (core →
 * preferences on language/timezone). */
function findRootGroup(schema: Record<string, unknown>): { group: string; order: number } | null {
  const props = (schema.properties as Record<string, Record<string, unknown>> | undefined) ?? {}
  for (const prop of Object.values(props)) {
    if (typeof prop === 'object' && prop !== null && typeof prop.ui_group === 'string') {
      return {
        group: prop.ui_group as string,
        order: typeof prop.ui_order === 'number' ? (prop.ui_order as number) : 999,
      }
    }
  }
  return null
}

export function SettingsLayout() {
  const { t } = useTranslation()
  const location = useLocation()
  const [mobileNavOpen, setMobileNavOpen] = useState(false)

  const schemaQuery = $api.useQuery('get', '/api/v1/config/schema')

  const groups = useMemo(() => {
    const schemas = schemaQuery.data?.schemas as Record<string, Record<string, unknown>> | undefined
    if (!schemas) return []
    return buildSidebarGroups(schemas, t('config.coreSection'))
  }, [schemaQuery.data, t])

  const navItem = (to: string, label: string, active: boolean) => (
    <NavLink
      to={to}
      onClick={() => setMobileNavOpen(false)}
      className={cn(
        'flex items-center gap-2 rounded-lg px-3 py-2 text-sm font-medium transition-colors',
        active
          ? 'bg-glass-bg-primary/80 text-foreground shadow-sm'
          : 'text-muted-foreground hover:bg-glass-bg-primary/40 hover:text-foreground',
      )}
    >
      <span className="flex-1">{label}</span>
      <ChevronRight className="h-3.5 w-3.5 opacity-50" />
    </NavLink>
  )

  const isActive = (prefix: string) =>
    location.pathname === prefix || location.pathname.startsWith(`${prefix}/`)

  return (
    <PageContainer size="medium">
      <div className="mb-6 flex items-center gap-2">
        <SettingsIcon className="text-muted-foreground h-5 w-5" />
        <h1 className="text-foreground text-xl font-bold">{t('settings.title')}</h1>
      </div>

      {/* Mobile: collapsible nav trigger */}
      <button
        type="button"
        className="glass-chip mb-4 flex w-full items-center justify-between rounded-lg px-4 py-2.5 text-sm font-medium lg:hidden"
        onClick={() => setMobileNavOpen((v) => !v)}
      >
        <span>{t('settings.sections')}</span>
        <ChevronRight
          className={cn('h-4 w-4 transition-transform', mobileNavOpen && 'rotate-90')}
        />
      </button>

      <div className="grid grid-cols-1 gap-6 lg:grid-cols-[200px_1fr]">
        {/* Desktop sidebar + mobile collapsible */}
        <aside className={cn(mobileNavOpen ? 'block' : 'hidden', 'lg:block')}>
          <nav className="space-y-4 lg:sticky lg:top-24">
            {groups.map((group) => {
              const groupLabel = t(`settings.group.${group.id}`, group.id)
              return (
                <div key={group.id}>
                  <h2 className="text-muted-foreground mb-1.5 px-3 text-xs font-semibold tracking-wide uppercase">
                    {groupLabel}
                  </h2>
                  <div className="space-y-0.5">
                    {group.items.map((item) =>
                      navItem(
                        `/settings/config/${item.section}`,
                        item.title,
                        isActive(`/settings/config/${item.section}`),
                      ),
                    )}
                  </div>
                </div>
              )
            })}

            {/* Account group — front-end only, not schema-driven */}
            <div>
              <h2 className="text-muted-foreground mb-1.5 px-3 text-xs font-semibold tracking-wide uppercase">
                {t('settings.group.account')}
              </h2>
              <div className="space-y-0.5">
                <NavLink
                  to="/settings/account"
                  onClick={() => setMobileNavOpen(false)}
                  className={cn(
                    'flex items-center gap-2 rounded-lg px-3 py-2 text-sm font-medium transition-colors',
                    isActive('/settings/account')
                      ? 'bg-glass-bg-primary/80 text-foreground shadow-sm'
                      : 'text-muted-foreground hover:bg-glass-bg-primary/40 hover:text-foreground',
                  )}
                >
                  <User className="h-4 w-4" />
                  <span className="flex-1">{t('settings.changePassword')}</span>
                </NavLink>
              </div>
            </div>
          </nav>
        </aside>

        <main className="min-w-0">
          <Outlet />
        </main>
      </div>
    </PageContainer>
  )
}
