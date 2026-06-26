export function getAtPath(obj: unknown, path: string): unknown {
  return path.split('.').reduce((current: unknown, key) => {
    if (current == null || typeof current !== 'object') return undefined
    return (current as Record<string, unknown>)[key]
  }, obj)
}

export function setAtPath(obj: unknown, path: string, value: unknown): Record<string, unknown> {
  const keys = path.split('.')
  const result = { ...(obj as Record<string, unknown>) }
  let current: Record<string, unknown> = result

  for (let i = 0; i < keys.length - 1; i++) {
    const key = keys[i]
    const next = current[key]
    current[key] = { ...(next as Record<string, unknown>) }
    current = current[key] as Record<string, unknown>
  }

  current[keys[keys.length - 1]] = value
  return result
}
