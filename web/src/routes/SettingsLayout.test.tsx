/**
 * Unit tests for the Settings two-level navigation builder.
 */

import { describe, expect, it } from 'vitest'
import { buildNavGroups, type NavGroup } from './SettingsLayout'

const coreSchema = {
  type: 'object',
  properties: {
    language: { type: 'string', ui_group: 'preferences', ui_order: 10 },
    timezone: { type: 'string', ui_group: 'preferences', ui_order: 20 },
  },
  $defs: {
    GitHubConfig: { title: 'GitHubConfig', ui_group: 'integrations', ui_order: 10 },
    AnalysisConfig: { title: 'AnalysisConfig', ui_group: 'integrations', ui_order: 20 },
    NotificationConfig: { title: 'NotificationConfig', ui_group: 'notifications', ui_order: 10 },
    MarkpostConfig: { title: 'MarkpostConfig', ui_group: 'system', ui_order: 10 },
    WebConfig: { title: 'WebConfig', ui_group: 'system', ui_order: 40 },
    AuthConfig: { title: 'AuthConfig', ui_group: 'system', ui_order: 50 },
    ObservabilityConfig: { title: 'ObservabilityConfig', ui_group: 'system', ui_order: 110 },
  },
}

const pluginSchema = { type: 'object', properties: {} }
const schemas = {
  core: coreSchema,
  repo: pluginSchema,
  changelog: pluginSchema,
  proposal: pluginSchema,
  feed: pluginSchema,
  v2ex: pluginSchema,
}

function groupById(groups: NavGroup[], id: NavGroup['id']): NavGroup {
  const g = groups.find((x) => x.id === id)
  if (!g) throw new Error(`group ${id} not found`)
  return g
}

describe('buildNavGroups', () => {
  it('produces three groups: core, integrations, account', () => {
    const groups = buildNavGroups(schemas)
    expect(groups.map((g) => g.id)).toEqual(['core', 'integrations', 'account'])
  })

  it('core group has one top-level route item plus anchor sub-items', () => {
    const groups = buildNavGroups(schemas)
    const core = groupById(groups, 'core')
    const top = core.items.filter((i) => !i.anchorId)
    const anchors = core.items.filter((i) => i.anchorId)
    expect(top).toHaveLength(1)
    expect(top[0]?.section).toBe('core')
    expect(top[0]?.navKey).toBe('nav.core')
    expect(anchors.length).toBe(8)
  })

  it('core anchor items are sorted by ui_order and derive anchorId from def name', () => {
    const groups = buildNavGroups(schemas)
    const anchors = groupById(groups, 'core').items.filter((i) => i.anchorId)
    expect(anchors.map((i) => i.anchorId)).toEqual([
      'preferences',
      'github',
      'notification',
      'markpost',
      'analysis',
      'web',
      'auth',
      'observability',
    ])
    expect(anchors.map((i) => i.order)).toEqual(
      [...anchors.map((i) => i.order)].sort((a, b) => a - b),
    )
  })

  it('integrations group derives plugin sections from schema keys (excluding core)', () => {
    const groups = buildNavGroups(schemas)
    const plugins = groupById(groups, 'integrations')
    expect(plugins.items.map((i) => i.section)).toEqual([
      'repo',
      'changelog',
      'proposal',
      'feed',
      'v2ex',
    ])
    expect(plugins.items.every((i) => !i.anchorId)).toBe(true)
  })

  it('account group has one item pointing to account route', () => {
    const groups = buildNavGroups(schemas)
    const account = groupById(groups, 'account')
    expect(account.items).toHaveLength(1)
    expect(account.items[0]?.section).toBe('account')
    expect(account.items[0]?.navKey).toBe('nav.account')
  })

  it('handles undefined schemas gracefully', () => {
    const groups = buildNavGroups(undefined)
    expect(groups.map((g) => g.id)).toEqual(['core', 'integrations', 'account'])
    const core = groupById(groups, 'core')
    expect(core.items).toHaveLength(1)
    expect(core.items[0]?.navKey).toBe('nav.core')
    expect(groupById(groups, 'integrations').items).toHaveLength(0)
  })
})
