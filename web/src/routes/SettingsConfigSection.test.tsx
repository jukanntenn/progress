/**
 * Tests for SettingsConfigSection's server-422 → field-level error mapping.
 */

import { describe, expect, it } from 'vitest'

// Mirrors parseServerErrors in SettingsConfigSection (kept in sync; the page
// wiring itself is covered by the Playwright e2e suite).
import { extractServerDetail, parseServerErrors } from './SettingsConfigSection'

describe('extractServerDetail', () => {
  it('unwraps the spec-12 error envelope (error.message)', () => {
    const detail =
      "invalid config for section 'core':\n  - timezone: Value error, Invalid timezone: 'Asia'"
    expect(
      extractServerDetail({ error: { code: 'client_error', message: detail, details: {} } }),
    ).toBe(detail)
  })

  it('falls back to a bare detail field (FastAPI style)', () => {
    expect(extractServerDetail({ detail: 'bad' })).toBe('bad')
  })

  it('falls back to a bare message field (network Error)', () => {
    expect(extractServerDetail(new Error('Failed to fetch'))).toBe('Failed to fetch')
  })

  it('returns null for unrecognized payloads', () => {
    expect(extractServerDetail({ foo: 1 })).toBeNull()
    expect(extractServerDetail(null)).toBeNull()
  })
})

describe('parseServerErrors', () => {
  it('maps "  - github.gh_token: msg" into a nested __errors schema', () => {
    const { extraErrors, general } = parseServerErrors(
      "invalid config for section 'core':\n  - github.gh_token: Input should be a valid string",
    )
    expect(extraErrors).toEqual({
      github: { gh_token: { __errors: ['Input should be a valid string'] } },
    })
    expect(general).toEqual(["invalid config for section 'core':"])
  })

  it('maps deep nested paths (notification.channels[1].recipient)', () => {
    const { extraErrors } = parseServerErrors(
      "invalid config for section 'core':\n  - notification.channels.1.recipient: Input should be a valid string",
    )
    expect(extraErrors).toEqual({
      notification: {
        channels: { '1': { recipient: { __errors: ['Input should be a valid string'] } } },
      },
    })
  })

  it('collects unparseable lines as general errors', () => {
    const { extraErrors, general } = parseServerErrors(
      "invalid config for section 'core':\n  - weird line",
    )
    expect(extraErrors).toEqual({})
    expect(general).toEqual(["invalid config for section 'core':", '- weird line'])
  })

  it('handles multiple errors on different fields', () => {
    const { extraErrors } = parseServerErrors(
      "invalid config for section 'core':\n  - a.b: one\n  - a.c: two",
    )
    expect(extraErrors).toEqual({
      a: { b: { __errors: ['one'] }, c: { __errors: ['two'] } },
    })
  })

  it('returns empty structures for empty input', () => {
    const { extraErrors, general } = parseServerErrors('')
    expect(extraErrors).toEqual({})
    expect(general).toEqual([])
  })
})
