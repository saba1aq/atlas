import type { Field, Ref } from './types'

export function isRef(v: unknown): v is Ref {
  return typeof v === 'object' && v !== null && 'id' in v && 'label' in v
}

export function formatCell(field: Field, value: unknown): string {
  if (value === null || value === undefined || value === '') return '—'
  switch (field.type) {
    case 'boolean': return value ? 'Yes' : 'No'
    case 'datetime': {
      const d = new Date(String(value))
      return isNaN(d.getTime()) ? String(value) : d.toLocaleString()
    }
    case 'many_to_one': return isRef(value) ? value.label : String(value)
    case 'many_to_many': return Array.isArray(value) ? value.map((v) => (isRef(v) ? v.label : String(v))).join(', ') : String(value)
    case 'json': { const s = JSON.stringify(value); return s.length > 60 ? s.slice(0, 57) + '…' : s }
    case 'enum': return field.choices?.find((c) => String(c.value) === String(value))?.label ?? String(value)
    default: { const s = String(value); return s.length > 120 ? s.slice(0, 117) + '…' : s }
  }
}

/** ISO datetime -> value for <input type="datetime-local"> in the viewer's timezone. */
export function toLocalInput(iso: string): string {
  const d = new Date(iso)
  if (isNaN(d.getTime())) return ''
  const pad = (n: number) => String(n).padStart(2, '0')
  return `${d.getFullYear()}-${pad(d.getMonth() + 1)}-${pad(d.getDate())}T${pad(d.getHours())}:${pad(d.getMinutes())}`
}

export function fromLocalInput(local: string): string | null {
  if (!local) return null
  const d = new Date(local)
  return isNaN(d.getTime()) ? null : d.toISOString()
}
