import { useState } from 'react'
import type { Condition, Field, Ref } from '../lib/types'
import { Button } from './ui'
import RelationSelect from './RelationSelect'

export type FilterState = Record<string, unknown>

/** Translate the panel's simple per-field state into the API filter tree. */
export function toConditions(fields: Field[], state: FilterState): Condition[] {
  const out: Condition[] = []
  for (const f of fields) {
    const v = state[f.name]
    if (v === undefined || v === null || v === '') continue
    switch (f.type) {
      case 'string': case 'text': case 'uuid':
        out.push({ field: f.name, op: 'icontains', value: v }); break
      case 'integer': case 'float': case 'decimal': case 'date': case 'datetime': case 'time': {
        const r = v as { from?: string; to?: string }
        if (r.from) out.push({ field: f.name, op: 'gte', value: r.from })
        if (r.to) out.push({ field: f.name, op: 'lte', value: r.to })
        break
      }
      case 'boolean':
        out.push({ field: f.name, op: 'eq', value: v === 'true' }); break
      case 'enum':
        out.push({ field: f.name, op: 'eq', value: v }); break
      case 'many_to_one': {
        const refs = v as Ref[]
        if (refs.length) out.push({ field: f.name, op: 'in', value: refs.map((r) => r.id) })
        break
      }
      case 'many_to_many': {
        const refs = v as Ref[]
        if (refs.length) out.push({ field: f.name, op: 'in', value: refs.map((r) => r.id) })
        break
      }
    }
  }
  return out
}

export function countActive(state: FilterState): number {
  return Object.values(state).filter((v) => {
    if (v === undefined || v === null || v === '') return false
    if (Array.isArray(v)) return v.length > 0
    if (typeof v === 'object') return Object.values(v as object).some(Boolean)
    return true
  }).length
}

export default function FilterPanel({ fields, initial, onApply, onClose }: {
  fields: Field[]; initial: FilterState; onApply: (s: FilterState) => void; onClose: () => void
}) {
  const [state, setState] = useState<FilterState>(initial)
  const set = (name: string, v: unknown) => setState((s) => ({ ...s, [name]: v }))
  return (
    <form className="flex h-full flex-col" onSubmit={(e) => { e.preventDefault(); onApply(state) }}>
      <div className="flex-1 space-y-4 overflow-auto p-4">
        {fields.map((f) => (
          <div key={f.name}>
            <label className="mb-1 block text-xs font-medium text-muted">{f.label}</label>
            <FilterWidget field={f} value={state[f.name]} onChange={(v) => set(f.name, v)} />
          </div>
        ))}
        {fields.length === 0 && <p className="text-sm text-muted">No filterable fields.</p>}
      </div>
      <div className="flex gap-2 border-t p-3">
        <Button type="submit" variant="primary">Apply</Button>
        <Button type="button" onClick={() => { setState({}); onApply({}) }}>Clear</Button>
        <Button type="button" variant="ghost" className="ml-auto" onClick={onClose}>Close</Button>
      </div>
    </form>
  )
}

function FilterWidget({ field: f, value, onChange }: { field: Field; value: unknown; onChange: (v: unknown) => void }) {
  switch (f.type) {
    case 'boolean':
      return (
        <select className="field" value={(value as string) ?? ''} onChange={(e) => onChange(e.target.value)}>
          <option value="">Any</option><option value="true">Yes</option><option value="false">No</option>
        </select>
      )
    case 'enum':
      return (
        <select className="field" value={(value as string) ?? ''} onChange={(e) => onChange(e.target.value)}>
          <option value="">Any</option>
          {f.choices?.map((c) => <option key={String(c.value)} value={String(c.value)}>{c.label}</option>)}
        </select>
      )
    case 'integer': case 'float': case 'decimal': case 'date': case 'datetime': case 'time': {
      const r = (value as { from?: string; to?: string }) ?? {}
      const type = f.type === 'date' ? 'date' : f.type === 'datetime' ? 'datetime-local' : f.type === 'time' ? 'time' : 'number'
      return (
        <div className="flex gap-2">
          <input className="field" type={type} placeholder="from" value={r.from ?? ''} onChange={(e) => onChange({ ...r, from: e.target.value })} />
          <input className="field" type={type} placeholder="to" value={r.to ?? ''} onChange={(e) => onChange({ ...r, to: e.target.value })} />
        </div>
      )
    }
    case 'many_to_one': case 'many_to_many':
      if (!f.relation?.resource) return null
      return <RelationSelect resource={f.relation.resource} multiple value={(value as Ref[]) ?? []} onChange={onChange} placeholder="Any" />
    case 'one_to_many':
      return null
    default:
      return <input className="field" placeholder="contains…" value={(value as string) ?? ''} onChange={(e) => onChange(e.target.value)} />
  }
}
