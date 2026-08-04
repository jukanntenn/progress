import { execFileSync } from 'node:child_process'
import { dirname, resolve } from 'node:path'
import { fileURLToPath } from 'node:url'
import type { APIRequestContext } from '@playwright/test'

export const BASE_URL = process.env.BASE_URL || 'http://localhost:5000'

/** Default admin credentials used by the e2e container's bootstrap seed.
 *
 * The docker-compose.local.yml seed sets ``initial_admin_password`` so tests
 * get a deterministic login instead of the random password the empty-config
 * bootstrap would print. */
export const ADMIN_USERNAME = process.env.E2E_ADMIN_USERNAME || 'admin'
export const ADMIN_PASSWORD = process.env.E2E_ADMIN_PASSWORD || 'admin123'

// ESM has no __dirname; derive the repo root from this file's location
// (e2e/web/lib/helpers.ts → three levels up).
const REPO_ROOT = resolve(dirname(fileURLToPath(import.meta.url)), '..', '..', '..')
const COMPOSE_FILE = 'docker/docker-compose.local.yml'
// `docker compose exec` addresses the *service* name (defined in compose as
// `services: progress`), not the `container_name` (`progress-local`).
const SERVICE = 'progress'

/** Poll /healthz until the container is up or the timeout elapses. */
export async function waitForBackend(
  request: APIRequestContext,
  timeoutMs = 120_000,
): Promise<void> {
  const deadline = Date.now() + timeoutMs
  let lastError: unknown
  while (Date.now() < deadline) {
    try {
      const resp = await request.get(`${BASE_URL}/healthz`, { timeout: 5_000 })
      if (resp.ok()) {
        return
      }
    } catch (e) {
      lastError = e
    }
    await new Promise((r) => setTimeout(r, 2_000))
  }
  throw new Error(`backend at ${BASE_URL} not ready after ${timeoutMs}ms: ${String(lastError)}`)
}

/** GET /api/v1/config — returns the full config object ({ core, plugins }).
 *
 * ``token`` is required now that the config endpoints are behind auth.
 */
export async function getConfig(
  request: APIRequestContext,
  token: string,
): Promise<Record<string, unknown>> {
  const resp = await request.get(`${BASE_URL}/api/v1/config`, {
    headers: { Authorization: `Bearer ${token}` },
  })
  if (!resp.ok()) {
    throw new Error(`GET /api/v1/config failed: ${resp.status()} ${await resp.text()}`)
  }
  return resp.json()
}

/** PUT /api/v1/config/{section} — upsert one section's payload.
 *
 * The request body is `{"data": {...}}` (see ConfigUpdateRequest); the API
 * validates the payload against the section's JSON schema and masks secrets.
 * ``token`` is required now that the config endpoints are behind auth.
 */
export async function putConfigSection(
  request: APIRequestContext,
  section: string,
  data: Record<string, unknown>,
  token: string,
): Promise<Record<string, unknown>> {
  const resp = await request.put(`${BASE_URL}/api/v1/config/${section}`, {
    data: { data },
    headers: { Authorization: `Bearer ${token}` },
  })
  if (!resp.ok()) {
    throw new Error(`PUT /api/v1/config/${section} failed: ${resp.status()} ${await resp.text()}`)
  }
  return resp.json()
}

/** Login as the seeded admin and return the Bearer token.
 *
 * All non-public endpoints require auth, so e2e tests that hit /reports,
 * /config, /integrations, or /version must call this first and send the
 * ``Authorization: Bearer <token>`` header.
 */
export async function loginAsAdmin(request: APIRequestContext): Promise<string> {
  const resp = await request.post(`${BASE_URL}/api/v1/auth/login`, {
    data: { username: ADMIN_USERNAME, password: ADMIN_PASSWORD },
  })
  if (!resp.ok()) {
    throw new Error(`login failed: ${resp.status()} ${await resp.text()}`)
  }
  const body = await resp.json()
  return body.access_token as string
}

/** A markdown body with mixed headings, a <details> block, and fenced code
 *  (incl. a `#`-prefixed line inside the fence) that exercises the report
 *  detail page: heading-downgrade render, rehype-slug anchors, TOC, and the
 *  details/summary sanitize allowlist.
 */
export const SAMPLE_REPORT_CONTENT = [
  '## Overview',
  '',
  'Top-level summary of this run.',
  '',
  '### Highlights',
  '',
  '- Feature A shipped',
  '- Bug B fixed',
  '',
  '## Details',
  '',
  '<details>',
  '<summary>Commit: fix rendering bug</summary>',
  '',
  'The commit body explaining the fix.',
  '',
  '</details>',
  '',
  '### Code Sample',
  '',
  '```python',
  '# this is a comment, not a heading',
  'def main():',
  '    pass',
  '```',
  '',
  '## Conclusion',
  '',
  'All good.',
].join('\n')

export interface SeededReport {
  id: number
  title: string
}

/**
 * Seed a Report row directly into the container's SQLite DB.
 *
 * The reports API is read-only (no POST/PUT), so UI e2e tests that need a
 * rendered report insert one via `docker compose exec` running the app's own
 * DB helpers in-process. Running inside the container (rather than touching the
 * file from the host) keeps the WAL pragmas consistent with the live FastAPI
 * connection. `repo_id=null` is required — GET /reports filters
 * `repo_id__isnull=True`.
 *
 * Returns the created report's id so the test can navigate to /reports/{id}.
 */
export function seedReport(
  overrides: { title?: string; content?: string; report_type?: string } = {},
): SeededReport {
  const title = overrides.title ?? 'E2E Seeded Report'
  const content = overrides.content ?? SAMPLE_REPORT_CONTENT
  const reportType = overrides.report_type ?? 'repo_update'
  // Pass the variable payload through stdin so quoting in the embedded Python
  // is never an issue; the snippet reads it from a fixed env var.
  const py = [
    'import os, asyncio',
    'from progress.db import init_db, close_db',
    'from progress.db.models.report import Report',
    'async def main():',
    "    await init_db('/app/data', run_migrations=False)",
    '    row = await Report.create(',
    "        report_type=os.environ['REPORT_TYPE'],",
    '        repo_id=None,',
    "        title=os.environ['REPORT_TITLE'],",
    "        commit_hash='',",
    '        commit_count=1,',
    "        content=os.environ['REPORT_CONTENT'],",
    '    )',
    '    await close_db()',
    '    print(row.id)',
    'asyncio.run(main())',
  ].join('\n')
  const stdout = execFileSync(
    'docker',
    [
      'compose',
      '-f',
      COMPOSE_FILE,
      'exec',
      '-T',
      '-e',
      `REPORT_TITLE=${title}`,
      '-e',
      `REPORT_CONTENT=${content}`,
      '-e',
      `REPORT_TYPE=${reportType}`,
      SERVICE,
      'python',
      '-c',
      py,
    ],
    { cwd: REPO_ROOT, encoding: 'utf-8', stdio: ['pipe', 'pipe', 'pipe'] },
  )
  const id = Number.parseInt(stdout.trim(), 10)
  if (!Number.isFinite(id)) {
    throw new Error(`seedReport: could not parse report id from stdout: ${stdout}`)
  }
  return { id, title }
}

/** Delete reports by id (cleanup after a test). No-op for already-absent ids. */
export function deleteReports(ids: number[]): void {
  if (ids.length === 0) return
  const py = [
    'import asyncio',
    'from progress.db import init_db, close_db',
    'from progress.db.models.report import Report',
    'async def main():',
    "    await init_db('/app/data', run_migrations=False)",
    '    await Report.filter(id__in=' + JSON.stringify(ids) + ').delete()',
    '    await close_db()',
    'asyncio.run(main())',
  ].join('\n')
  execFileSync(
    'docker',
    ['compose', '-f', COMPOSE_FILE, 'exec', '-T', SERVICE, 'python', '-c', py],
    { cwd: REPO_ROOT, encoding: 'utf-8', stdio: ['pipe', 'pipe', 'pipe'] },
  )
}
