/**
 * Format an ISO timestamp using the browser locale + the configured timezone.
 * Falls back to the raw string when the input is not a valid date.
 */
export function formatDateTime(iso: string | null | undefined, timezone?: string): string {
  if (!iso) return ''
  const d = new Date(iso)
  if (Number.isNaN(d.getTime())) return iso
  const options: Intl.DateTimeFormatOptions = {
    year: 'numeric',
    month: '2-digit',
    day: '2-digit',
    hour: '2-digit',
    minute: '2-digit',
    second: '2-digit',
    hour12: false,
  }
  if (timezone) options.timeZone = timezone
  return new Intl.DateTimeFormat(undefined, options).format(d)
}
