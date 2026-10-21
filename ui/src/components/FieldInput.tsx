import { useState } from 'react'
import type { Field, Ref } from '../lib/types'
import { fromLocalInput, isRef, toLocalInput } from '../lib/format'
import RelationSelect from './RelationSelect'

interface Props {
  field: Field
  value: unknown
  onChange: (v: unknown) => void
  error?: string
  disabled?: boolean
}

export default function FieldInput({ field, value, onChange, error, disabled }: Props) {
  const cls = `field ${error ? 'invalid' : ''}`
  const str = value === null || value === undefined ? '' : String(value)
  switch (field.type) {
    case 'text':
      return <textarea className={cls} rows={4} value={str} disabled={disabled} onChange={(e) => onChange(e.target.value)} />
    case 'json':
      return <JsonInput value={value} onChange={onChange} disabled={disabled} invalid={!!error} />
    case 'integer':
    case 'float':
      return (
        <input className={cls} type="number" step={field.type === 'integer' ? 1 : 'any'} value={str} disabled={disabled}
          onChange={(e) => onChange(e.target.value === '' ? null : e.target.value)} />
      )
    case 'decimal':
      return <input className={cls} inputMode="decimal" value={str} disabled={disabled} onChange={(e) => onChange(e.target.value || null)} />
    case 'boolean':
      if (field.nullable) {
        return (
          <select className={cls} value={value === null || value === undefined ? '' : value ? 'true' : 'false'} disabled={disabled}
            onChange={(e) => onChange(e.target.value === '' ? null : e.target.value === 'true')}>
            <option value="">—</option><option value="true">Yes</option><option value="false">No</option>
          </select>
        )
      }
      return (
        <label className="inline-flex h-9 items-center gap-2">
          <input type="checkbox" className="size-4 accent-accent" checked={!!value} disabled={disabled} onChange={(e) => onChange(e.target.checked)} />
          <span className="text-muted">{value ? 'Yes' : 'No'}</span>
        </label>
      )
    case 'date':
      return <input className={cls} type="date" value={str.slice(0, 10)} disabled={disabled} onChange={(e) => onChange(e.target.value || null)} />
    case 'datetime':
      return (
        <input className={cls} type="datetime-local" value={str ? toLocalInput(str) : ''} disabled={disabled}
          onChange={(e) => onChange(fromLocalInput(e.target.value))} />
      )
    case 'time':
      return <input className={cls} type="time" step={1} value={str} disabled={disabled} onChange={(e) => onChange(e.target.value || null)} />
    case 'enum':
      return (
        <select className={cls} value={str} disabled={disabled} onChange={(e) => onChange(e.target.value === '' ? null : e.target.value)}>
          <option value="">{field.nullable || !field.required ? '—' : 'Select…'}</option>
          {field.choices?.map((c) => <option key={String(c.value)} value={String(c.value)}>{c.label}</option>)}
        </select>
      )
    case 'many_to_one': {
      const refs: Ref[] = isRef(value) ? [value] : []
      if (!field.relation?.resource) return <input className={cls} value={str} disabled placeholder="(unregistered relation)" />
      return <RelationSelect resource={field.relation.resource} value={refs} disabled={disabled} invalid={!!error} onChange={(v) => onChange(v[0] ?? null)} />
    }
    case 'many_to_many': {
      const refs: Ref[] = Array.isArray(value) ? value.filter(isRef) : []
      if (!field.relation?.resource) return <input className={cls} value={str} disabled placeholder="(unregistered relation)" />
      return <RelationSelect resource={field.relation.resource} value={refs} multiple disabled={disabled} invalid={!!error} onChange={onChange} />
    }
    default:
      return <input className={cls} value={str} maxLength={field.max_length ?? undefined} disabled={disabled} onChange={(e) => onChange(e.target.value)} />
  }
}

function JsonInput({ value, onChange, disabled, invalid }: { value: unknown; onChange: (v: unknown) => void; disabled?: boolean; invalid: boolean }) {
  const [text, setText] = useState(() => (value === null || value === undefined ? '' : JSON.stringify(value, null, 2)))
  const [bad, setBad] = useState(false)
  return (
    <textarea
      className={`field font-mono text-xs ${invalid || bad ? 'invalid' : ''}`}
      rows={6}
      value={text}
      disabled={disabled}
      onChange={(e) => {
        setText(e.target.value)
        if (e.target.value.trim() === '') { setBad(false); onChange(null); return }
        try { onChange(JSON.parse(e.target.value)); setBad(false) } catch { setBad(true) }
      }}
    />
  )
}
