/**
 * Unit tests for the Settings sidebar grouping (spec 4.4 / D4).
 */

import { describe, expect, it } from 'vitest'
import { buildSidebarGroups } from './SettingsLayout'

const coreSchema = {
  type: 'object',
  properties: {
    language: { type: 'string', ui_group: 'preferences', ui_order: 10 },
    timezone: { type: 'string', ui_group: 'preferences', ui_order: 20 },
    github: { $ref: '#/$defs/GitHubConfig' },
    analysis: { $ref: '#/$defs/AnalysisConfig' },
    notification: { $ref: '#/$defs/NotificationConfig' },
    markpost: { $ref: '#/$defs/MarkpostConfig' },
    web: { $ref: '#/$defs/WebConfig' },
    auth: { $ref: '#/$defs/AuthConfig' },
    observability: { $ref: '#/$defs/ObservabilityConfig' },
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

const schemas = {
  core: coreSchema,
  repo: { title: 'RepoIntegrationConfig', ui_group: 'integrations', ui_order: 90 },
  changelog: { title: 'ChangelogIntegrationConfig', ui_group: 'integrations', ui_order: 100 },
  proposal: { title: 'ProposalIntegrationConfig', ui_group: 'integrations', ui_order: 110 },
  feed: { title: 'FeedIntegrationConfig', ui_group: 'integrations', ui_order: 120 },
}

describe('buildSidebarGroups', () => {
  it('places core root scalars under their root-level ui_group', () => {
    const groups = buildSidebarGroups(schemas, 'Core')
    const preferences = groups.find((g) => g.id === 'preferences')
    expect(preferences?.items.map((i) => [i.title, i.section])).toEqual([['Core', 'core']])
  })

  it('maps core $defs sub-models into their groups (spec 4.4)', () => {
    const groups = buildSidebarGroups(schemas, 'Core')
    const byGroup = new Map(groups.map((g) => [g.id, g.items.map((i) => i.title)]))
    expect(byGroup.get('integrations')?.slice(0, 2)).toEqual(['GitHub', 'Analysis'])
    expect(byGroup.get('notifications')).toEqual(['Notification'])
    expect(byGroup.get('system')).toEqual(['Markpost', 'Web', 'Auth', 'Observability'])
  })

  it('maps plugin sections from their schema-root ui_group (D4)', () => {
    const groups = buildSidebarGroups(schemas, 'Core')
    const integrations = groups.find((g) => g.id === 'integrations')
    expect(integrations?.items.map((i) => i.title)).toEqual([
      'GitHub',
      'Analysis',
      'Repo',
      'Changelog',
      'Proposal',
      'Feed',
    ])
    expect(integrations?.items.map((i) => i.section)).toEqual([
      'core',
      'core',
      'repo',
      'changelog',
      'proposal',
      'feed',
    ])
  })

  it('orders groups preferences → integrations → notifications → system', () => {
    const groups = buildSidebarGroups(schemas, 'Core')
    expect(groups.map((g) => g.id)).toEqual([
      'preferences',
      'integrations',
      'notifications',
      'system',
    ])
  })

  it('sorts items within a group by ui_order', () => {
    const groups = buildSidebarGroups(schemas, 'Core')
    const system = groups.find((g) => g.id === 'system')
    expect(system?.items.map((i) => i.order)).toEqual([10, 40, 50, 110])
  })

  it('drops sections without a ui_group annotation', () => {
    const groups = buildSidebarGroups({ core: coreSchema, orphan: { title: 'X' } }, 'Core')
    const titles = groups.flatMap((g) => g.items.map((i) => i.title))
    expect(titles).not.toContain('X')
  })

  it('returns empty for empty schemas', () => {
    expect(buildSidebarGroups({}, 'Core')).toEqual([])
  })
})
