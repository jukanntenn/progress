import { useEffect, useMemo, useState } from 'react'
import { NavLink, Outlet, useLocation } from 'react-router'
import { useTranslation } from 'react-i18next'
import { Settings as SettingsIcon } from 'lucide-react'
import { Dialog } from '@base-ui/react'
import { PageContainer } from '@/components/PageContainer'
import { $api } from '@/api/client'
import { cn } from '@/lib/utils'

export interface SettingsOutletContext {
  currentLabel: string
  onOpenDrawer: () => void
}

type JsonSchema = Record<string, unknown>

export interface NavItem {
  section: string
  navKey: string
  order: number
  anchorId?: string
  rawLabel?: string
}

export interface NavGroup {
  id: 'core' | 'integrations' | 'account'
  items: NavItem[]
}

const PLUGIN_SECTIONS = ['repo', 'changelog', 'proposal', 'feed'] as const

// eslint-disable-next-line react-refresh/only-export-components
export function buildNavGroups(coreSchema: JsonSchema | undefined): NavGroup[] {
  const coreTopItem: NavItem = { section: 'core', navKey: 'nav.core', order: 0 }
  const anchors: NavItem[] = []

  if (coreSchema) {
    const rootGroup = findRootGroup(coreSchema)
    if (rootGroup) {
      anchors.push({
        section: 'core',
        navKey: 'nav.preferences',
        order: rootGroup.order,
        anchorId: 'preferences',
      })
    }
    const defs = (coreSchema.$defs as Record<string, JsonSchema> | undefined) ?? {}
    for (const [defName, def] of Object.entries(defs)) {
      if (typeof def !== 'object' || def === null) continue
      const group = (def as JsonSchema).ui_group as string | undefined
      if (!group) continue
      const anchorId = defName
        .replace(/IntegrationConfig$/, '')
        .replace(/Config$/, '')
        .toLowerCase()
      anchors.push({
        section: 'core',
        navKey: `nav.${anchorId}`,
        order:
          typeof (def as JsonSchema).ui_order === 'number'
            ? ((def as JsonSchema).ui_order as number)
            : 999,
        anchorId,
      })
    }
  }

  const pluginItems: NavItem[] = PLUGIN_SECTIONS.map((section, i) => ({
    section,
    navKey: `nav.${section}`,
    rawLabel: section,
    order: 100 + i * 10,
  }))

  const accountItems: NavItem[] = [{ section: 'account', navKey: 'nav.account', order: 0 }]

  return [
    { id: 'core', items: [coreTopItem, ...anchors.sort((a, b) => a.order - b.order)] },
    { id: 'integrations', items: pluginItems },
    { id: 'account', items: accountItems },
  ]
}

function findRootGroup(schema: JsonSchema): { order: number } | null {
  const props = (schema.properties as Record<string, JsonSchema> | undefined) ?? {}
  for (const prop of Object.values(props)) {
    if (typeof prop === 'object' && prop !== null && typeof prop.ui_group === 'string') {
      return { order: typeof prop.ui_order === 'number' ? (prop.ui_order as number) : 999 }
    }
  }
  return null
}

export function SettingsLayout() {
  const { t } = useTranslation()
  const location = useLocation()
  const [drawerOpen, setDrawerOpen] = useState(false)
  const [activeAnchor, setActiveAnchor] = useState<string>('')

  const schemaQuery = $api.useQuery('get', '/api/v1/config/schema')
  const configQuery = $api.useQuery('get', '/api/v1/config')

  const groups = useMemo(() => {
    const schemas = schemaQuery.data?.schemas as Record<string, JsonSchema> | undefined
    return buildNavGroups(schemas?.core)
  }, [schemaQuery.data])

  const activeSection = useMemo(() => {
    const match = location.pathname.match(/^\/settings\/(?:config\/([^/]+)|account)/)
    if (!match) return 'core'
    return match[1] ?? 'account'
  }, [location.pathname])

  const isCoreActive = activeSection === 'core'

  useEffect(() => {
    if (!isCoreActive) {
      setActiveAnchor('')
      return
    }
    const sections = document.querySelectorAll<HTMLElement>('[data-section-anchor]')
    if (sections.length === 0) return
    const observer = new IntersectionObserver(
      (entries) => {
        const visible = entries
          .filter((e) => e.isIntersecting)
          .sort((a, b) => b.intersectionRatio - a.intersectionRatio)
        if (visible.length > 0) {
          const target = visible[0]?.target
          if (target) setActiveAnchor(target.id)
        }
      },
      { rootMargin: '-80px 0px -60% 0px', threshold: [0, 0.25, 0.5, 1] },
    )
    sections.forEach((s) => observer.observe(s))
    return () => observer.disconnect()
  }, [isCoreActive, configQuery.data, schemaQuery.data])

  const handleAnchorClick = (anchorId: string) => {
    const el = document.getElementById(anchorId)
    if (el) {
      el.scrollIntoView({ behavior: 'smooth', block: 'start' })
      setActiveAnchor(anchorId)
    }
    setDrawerOpen(false)
  }

  const handleNavigate = () => setDrawerOpen(false)

  const renderItem = (item: NavItem) => {
    if (item.anchorId) {
      const isActive = activeAnchor === item.anchorId
      return (
        <button
          key={`${item.section}-${item.anchorId}`}
          type="button"
          onClick={() => item.anchorId && handleAnchorClick(item.anchorId)}
          className={cn(
            'flex w-full items-center rounded-lg py-1.5 pr-3 pl-9 text-left text-sm transition-colors',
            isActive
              ? 'bg-accent/10 text-foreground font-medium'
              : 'text-muted-foreground hover:bg-accent/5 hover:text-foreground',
          )}
        >
          {t(`settings.${item.navKey}`)}
        </button>
      )
    }

    const to = item.section === 'account' ? '/settings/account' : `/settings/config/${item.section}`
    const isActive = activeSection === item.section
    return (
      <NavLink
        key={item.section}
        to={to}
        onClick={handleNavigate}
        className={cn(
          'relative flex items-center gap-2 rounded-lg px-3 py-2 text-sm font-medium transition-colors',
          isActive
            ? 'bg-accent/10 text-foreground'
            : 'text-muted-foreground hover:bg-accent/5 hover:text-foreground',
        )}
      >
        {isActive && (
          <span className="bg-primary absolute top-1/2 left-0 h-5 w-1 -translate-y-1/2 rounded-r-full" />
        )}
        <span className="flex-1 capitalize">{item.rawLabel ?? t(`settings.${item.navKey}`)}</span>
      </NavLink>
    )
  }

  const renderGroup = (group: NavGroup) => {
    const topLevelItems = group.items.filter((i) => !i.anchorId)
    const anchorItems = group.items.filter((i) => i.anchorId)
    const showAnchors = group.id === 'core' && isCoreActive && anchorItems.length > 0

    return (
      <div key={group.id} className="space-y-0.5">
        <h2 className="text-muted-foreground mb-1.5 px-3 text-xs font-semibold tracking-wide uppercase">
          {t(`settings.group.${group.id}`)}
        </h2>
        {topLevelItems.map(renderItem)}
        {showAnchors && (
          <div className="border-border/40 ml-2 border-l pl-1">{anchorItems.map(renderItem)}</div>
        )}
      </div>
    )
  }

  const sidebarContent = <nav className="space-y-4">{groups.map(renderGroup)}</nav>

  const currentLabel = useMemo(() => {
    for (const group of groups) {
      const item = group.items.find((i) => !i.anchorId && i.section === activeSection)
      if (item) return item.rawLabel ?? t(`settings.${item.navKey}`)
    }
    return t('settings.nav.core')
  }, [groups, activeSection, t])

  const outletContext: SettingsOutletContext = {
    currentLabel,
    onOpenDrawer: () => setDrawerOpen(true),
  }

  return (
    <PageContainer size="wide">
      <div className="mb-6 flex items-center gap-2">
        <SettingsIcon className="text-muted-foreground h-5 w-5" />
        <h1 className="text-foreground text-xl font-bold">{t('settings.title')}</h1>
      </div>

      <div className="grid grid-cols-1 gap-6 lg:grid-cols-[240px_1fr]">
        <aside className="hidden lg:block">
          <div className="sticky top-24">{sidebarContent}</div>
        </aside>

        <main className="min-w-0">
          <Outlet context={outletContext} />
        </main>
      </div>

      <Dialog.Root open={drawerOpen} onOpenChange={setDrawerOpen}>
        <Dialog.Portal>
          <Dialog.Backdrop className="animate-fade-in fixed inset-0 z-40 bg-black/40 backdrop-blur-sm" />
          <Dialog.Popup className="glass-popover animate-slide-in-left fixed inset-y-0 left-0 z-50 w-[280px] max-w-[75vw] overflow-y-auto p-4">
            <div className="mb-4 flex items-center gap-2">
              <SettingsIcon className="text-muted-foreground h-5 w-5" />
              <span className="text-foreground font-semibold">{t('settings.title')}</span>
            </div>
            {sidebarContent}
          </Dialog.Popup>
        </Dialog.Portal>
      </Dialog.Root>
    </PageContainer>
  )
}
