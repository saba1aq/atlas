import { config } from './config'

export class ApiError extends Error {
  status: number
  errors: Record<string, string>
  constructor(status: number, message: string, errors: Record<string, string> = {}) {
    super(message)
    this.status = status
    this.errors = errors
  }
}

export type Params = Record<string, string | number | undefined | null>

export async function api<T>(
  path: string,
  opts: { method?: string; body?: unknown; params?: Params } = {},
): Promise<T> {
  const qs = new URLSearchParams()
  for (const [k, v] of Object.entries(opts.params ?? {})) {
    if (v !== undefined && v !== null && v !== '') qs.set(k, String(v))
  }
  const url = `${config.apiPath}${path}${qs.size ? `?${qs}` : ''}`
  const res = await fetch(url, {
    method: opts.method ?? 'GET',
    credentials: 'include',
    headers: opts.body !== undefined ? { 'content-type': 'application/json' } : undefined,
    body: opts.body !== undefined ? JSON.stringify(opts.body) : undefined,
  })
  if (res.status === 204) return undefined as T
  const text = await res.text()
  let data: unknown = null
  try { data = text ? JSON.parse(text) : null } catch { data = { error: text } }
  if (!res.ok) {
    const d = (data ?? {}) as { error?: string; errors?: Record<string, string> }
    throw new ApiError(res.status, d.error ?? res.statusText, d.errors ?? {})
  }
  return data as T
}

export function exportUrl(resource: string, params: Params, format: 'csv' | 'json'): string {
  const qs = new URLSearchParams()
  for (const [k, v] of Object.entries(params)) if (v !== undefined && v !== null && v !== '') qs.set(k, String(v))
  qs.set('format', format)
  return `${config.apiPath}/${resource}/export?${qs}`
}
