import { useEffect, useRef, useState } from 'react'
import { X } from 'lucide-react'
import { api } from '../lib/api'
import type { Ref } from '../lib/types'

interface Props {
  resource: string
  value: Ref[] // one item for single select
  multiple?: boolean
  onChange: (v: Ref[]) => void
  disabled?: boolean
  invalid?: boolean
  placeholder?: string
}

export default function RelationSelect({ resource, value, multiple, onChange, disabled, invalid, placeholder }: Props) {
  const [q, setQ] = useState('')
  const [open, setOpen] = useState(false)
  const [options, setOptions] = useState<Ref[]>([])
  const [loading, setLoading] = useState(false)
  const [active, setActive] = useState(0)
  const box = useRef<HTMLDivElement>(null)

  useEffect(() => {
    if (!open) return
    let cancelled = false
    setLoading(true)
    const t = setTimeout(async () => {
      try {
        const r = await api<{ items: { value: string | number; label: string }[] }>(`/${resource}/options`, { params: { q } })
        if (!cancelled) setOptions(r.items.map((o) => ({ id: o.value, label: o.label })))
      } finally {
        if (!cancelled) setLoading(false)
      }
    }, 200)
    return () => { cancelled = true; clearTimeout(t) }
  }, [q, open, resource])

  useEffect(() => {
    const onDoc = (e: MouseEvent) => { if (!box.current?.contains(e.target as Node)) setOpen(false) }
    document.addEventListener('mousedown', onDoc)
    return () => document.removeEventListener('mousedown', onDoc)
  }, [])

  const pick = (o: Ref) => {
    if (multiple) {
      if (!value.some((v) => String(v.id) === String(o.id))) onChange([...value, o])
    } else {
      onChange([o])
      setOpen(false)
    }
    setQ('')
  }
  const remove = (id: Ref['id']) => onChange(value.filter((v) => String(v.id) !== String(id)))
  const visible = options.filter((o) => !multiple || !value.some((v) => String(v.id) === String(o.id)))

  return (
    <div ref={box} className="relative">
      <div className={`field flex min-h-9 flex-wrap items-center gap-1 ${invalid ? 'invalid' : ''} ${disabled ? 'opacity-60' : ''}`} onClick={() => !disabled && setOpen(true)}>
        {value.map((v) => (
          <span key={String(v.id)} className="inline-flex items-center gap-1 rounded bg-accent/15 px-1.5 py-0.5 text-xs text-accent">
            {v.label}
            {!disabled && <button type="button" onClick={(e) => { e.stopPropagation(); remove(v.id) }} aria-label="Remove"><X size={12} /></button>}
          </span>
        ))}
        {(multiple || value.length === 0) && (
          <input
            className="min-w-24 flex-1 bg-transparent outline-none"
            value={q}
            disabled={disabled}
            placeholder={value.length ? '' : placeholder ?? 'Search…'}
            onChange={(e) => { setQ(e.target.value); setOpen(true); setActive(0) }}
            onFocus={() => setOpen(true)}
            onKeyDown={(e) => {
              if (e.key === 'ArrowDown') { e.preventDefault(); setActive((a) => Math.min(a + 1, visible.length - 1)) }
              else if (e.key === 'ArrowUp') { e.preventDefault(); setActive((a) => Math.max(a - 1, 0)) }
              else if (e.key === 'Enter' && open && visible[active]) { e.preventDefault(); pick(visible[active]) }
              else if (e.key === 'Escape') setOpen(false)
              else if (e.key === 'Backspace' && !q && value.length && multiple) remove(value[value.length - 1].id)
            }}
          />
        )}
      </div>
      {open && !disabled && (
        <div className="popover absolute z-20 mt-1 max-h-60 w-full overflow-auto rounded-lg border bg-surface shadow-lg">
          {loading && options.length === 0 && <div className="px-3 py-2 text-xs text-muted">Loading…</div>}
          {!loading && visible.length === 0 && <div className="px-3 py-2 text-xs text-muted">No results</div>}
          {visible.map((o, i) => (
            <button
              type="button"
              key={String(o.id)}
              onMouseEnter={() => setActive(i)}
              onClick={() => pick(o)}
              className={`block w-full px-3 py-1.5 text-left text-sm transition-colors duration-100 ${i === active ? 'bg-accent/15' : ''}`}
            >
              {o.label} <span className="text-xs text-muted">#{String(o.id)}</span>
            </button>
          ))}
        </div>
      )}
    </div>
  )
}
