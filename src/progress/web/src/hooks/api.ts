import useSWR from 'swr'

const fetcher = async (url: string) => {
  const res = await fetch(url)
  if (!res.ok) {
    throw new Error('Failed to fetch')
  }
  return res.json()
}

export interface Report {
  id: number
  title: string | null
  created_at: string
  markpost_url: string | null
}

export interface ReportDetail extends Report {
  content: string
}

export interface PaginatedReports {
  reports: Report[]
  page: number
  total_pages: number
  total: number
  has_prev: boolean
  has_next: boolean
}

export function useReports(page: number = 1) {
  return useSWR<PaginatedReports>(`/api/v1/reports?page=${page}`, fetcher)
}

export function useReport(id: number | undefined) {
  return useSWR<ReportDetail>(id ? `/api/v1/reports/${id}` : null, fetcher)
}

export interface ConfigData {
  success: boolean
  data: Record<string, unknown>
  toml: string
  path: string
  comments: Record<string, string>
}

export function useConfig() {
  return useSWR<ConfigData>('/api/v1/config', fetcher)
}

export function useTimezones() {
  return useSWR<{ success: boolean; timezones: string[] }>(
    '/api/v1/config/timezones',
    fetcher,
  )
}

export interface FieldSchema {
  type: string
  path: string
  label: string
  help_text?: string | null
  required?: boolean
  default?: unknown
  options?: string[]
  validation?: Record<string, unknown>
  item_label?: string | null
  item_fields?: FieldSchema[] | null
  discriminator?: string | null
  variants?: Record<string, FieldSchema[]> | null
}

export interface SectionSchema {
  id: string
  title: string
  description?: string
  fields: FieldSchema[]
}

export interface EditorSchema {
  sections: SectionSchema[]
}

export function useConfigSchema() {
  return useSWR<EditorSchema>('/api/v1/config/schema', fetcher)
}

export async function saveConfigToml(
  toml: string,
): Promise<{ success: boolean; toml?: string; error?: string; message?: string }> {
  const res = await fetch('/api/v1/config', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ toml }),
  })
  return res.json()
}

export async function saveConfigData(
  config: Record<string, unknown>,
): Promise<{ success: boolean; toml?: string; error?: string; message?: string }> {
  const res = await fetch('/api/v1/config', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ config }),
  })
  return res.json()
}

export async function validateConfig(
  toml: string,
): Promise<{ success: boolean; error?: string }> {
  const res = await fetch('/api/v1/config/validate', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ toml }),
  })
  return res.json()
}

export async function validateConfigData(
  config: Record<string, unknown>,
): Promise<{ success: boolean; error?: string }> {
  const res = await fetch('/api/v1/config/validate-data', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ config }),
  })
  return res.json()
}
