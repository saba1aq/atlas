import { useEffect, useMemo, useState } from 'react'
import { Link, useNavigate, useParams, useSearchParams } from 'react-router-dom'
import { useMutation, useQueryClient } from '@tanstack/react-query'
import { ArrowDown, ArrowUp, ChevronLeft, ChevronRight, Download, Filter, Plus, Search, Trash2, X } from 'lucide-react'
import { useList, useSchema } from '../lib/hooks'
import { api, ApiError, exportUrl } from '../lib/api'
import { formatCell } from '../lib/format'
import type { Action, Row, Schema } from '../lib/types'
import { Badge, Button, Empty, ErrorBox, Spinner } from '../components/ui'
import FilterPanel, { countActive, toConditions, type FilterState } from '../components/FilterPanel'
import { useConfirm } from '../components/Confirm'
import { useToast } from '../components/Toast'

export default function ListPage() {
  const { resource = '' } = useParams()
  const schema = useSchema(resource)
  if (schema.isPending) return <Spinner />
  if (schema.error) return <ErrorBox>{schema.error instanceof ApiError ? schema.error.message : String(schema.error)}</ErrorBox>
  return <ResourceList key={resource} schema={schema.data} />
}

function parseFilters(raw: string | null): FilterState {
  if (!raw) return {}
  try { return JSON.parse(raw) as FilterState } catch { return {} }
}

function ResourceList({ schema }: { schema: Schema }) {
  const resource = schema.key
  const navigate = useNavigate()
  const qc = useQueryClient()
  const toast = useToast()
  const confirm = useConfirm()
  const [sp, setSp] = useSearchParams()
  const offset = Number(sp.get('offset') ?? 0)
  const limit = Number(sp.get('limit') ?? schema.page_size)
  const sort = sp.get('sort') ?? schema.ordering.join(',')
  const search = sp.get('search') ?? ''
  const filterState = useMemo(() => parseFilters(sp.get('f')), [sp])
  const [searchDraft, setSearchDraft] = useState(search)
  const [showFilters, setShowFilters] = useState(false)
  const [selected, setSelected] = useState<Set<string>>(new Set())

  const update = (patch: Record<string, string | null>, resetOffset = true) => {
    const next = new URLSearchParams(sp)
    for (const [k, v] of Object.entries(patch)) v === null || v === '' ? next.delete(k) : next.set(k, v)
    if (resetOffset) next.delete('offset')
    setSp(next)
  }

  useEffect(() => {
    const t = setTimeout(() => { if (searchDraft !== search) update({ search: searchDraft }) }, 300)
    return () => clearTimeout(t)
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [searchDraft])

  const columns = schema.fields.filter((f) => f.in_list)
  const filterable = schema.fields.filter((f) => f.filterable && f.type !== 'one_to_many' && !f.primary_key)
  const conditions = useMemo(() => toConditions(schema.fields, filterState), [schema.fields, filterState])
  const params = { offset, limit, sort, search, filters: conditions.length ? JSON.stringify(conditions) : undefined }
  const list = useList(resource, params)
  const rows = list.data?.items ?? []
  const total = list.data?.total ?? 0
  const pk = schema.pk_field
  const idOf = (r: Row) => String(r[pk])

  useEffect(() => setSelected(new Set()), [list.data])

  const toggleSort = (name: string) => {
    const current = sort.split(',').filter(Boolean)
    const idx = current.findIndex((s) => s.replace(/^-/, '') === name)
    if (idx === -1) update({ sort: name })
    else if (!current[idx].startsWith('-')) update({ sort: `-${name}` })
    else update({ sort: null })
  }
  const sortDir = (name: string) => {
    const s = sort.split(',').find((x) => x.replace(/^-/, '') === name)
    return s ? (s.startsWith('-') ? 'desc' : 'asc') : null
  }

  const invalidate = () => qc.invalidateQueries({ queryKey: ['list', resource] })
  const del = useMutation({
    mutationFn: (pks: string[]) => api<{ deleted: number }>(`/${resource}`, { method: 'DELETE', body: { pks } }),
    onSuccess: (r) => { toast(`Deleted ${r.deleted} ${r.deleted === 1 ? schema.label : schema.label_plural}`, 'success'); invalidate() },
    onError: (e) => toast(e instanceof ApiError ? e.message : 'Delete failed', 'error'),
  })
  const act = useMutation({
    mutationFn: ({ action, pks }: { action: Action; pks: string[] }) =>
      api<{ message?: string }>(`/${resource}/actions/${action.name}`, { method: 'POST', body: { pks } }),
    onSuccess: (r) => { toast(r.message ?? 'Done', 'success'); invalidate() },
    onError: (e) => toast(e instanceof ApiError ? e.message : 'Action failed', 'error'),
  })

  const runDelete = async () => {
    const pks = [...selected]
    if (await confirm({ title: `Delete ${pks.length} ${pks.length === 1 ? schema.label : schema.label_plural}?`, body: 'This cannot be undone.', confirmLabel: 'Delete', danger: true })) del.mutate(pks)
  }
  const runAction = async (action: Action) => {
    const pks = [...selected]
    if (action.confirm && !(await confirm({ title: action.label, body: action.confirm }))) return
    act.mutate({ action, pks })
  }

  const allSelected = rows.length > 0 && rows.every((r) => selected.has(idOf(r)))
  const activeFilters = countActive(filterState)
  const page = Math.floor(offset / limit) + 1
  const pages = Math.max(1, Math.ceil(total / limit))

  return (
    <div className="page-enter flex h-full gap-4">
      <div className="flex min-w-0 flex-1 flex-col">
        <div className="mb-4 flex flex-wrap items-center gap-2">
          <h1 className="mr-auto text-xl font-semibold tracking-tight">
            {schema.label_plural} <span className="text-sm font-normal text-muted">{total}</span>
          </h1>
          <label className="relative">
            <Search size={14} className="pointer-events-none absolute top-1/2 left-2.5 -translate-y-1/2 text-muted" />
            <input className="field w-56 pl-8" placeholder="Search" value={searchDraft} onChange={(e) => setSearchDraft(e.target.value)} />
          </label>
          {filterable.length > 0 && (
            <Button onClick={() => setShowFilters((v) => !v)} variant={showFilters ? 'primary' : 'secondary'}>
              <Filter size={14} /> Filters {activeFilters > 0 && <Badge>{activeFilters}</Badge>}
            </Button>
          )}
          <a className="pressable hoverable inline-flex items-center gap-1.5 rounded-md border bg-surface px-3 py-1.5 text-sm" href={exportUrl(resource, params, 'csv')} title="Export CSV">
            <Download size={14} /> CSV
          </a>
          {schema.permissions.create && (
            <Link to={`/${resource}/new`} className="pressable inline-flex items-center gap-1.5 rounded-md bg-accent px-3 py-1.5 text-sm font-medium text-accent-fg [@media(hover:hover)]:hover:opacity-90">
              <Plus size={14} /> New {schema.label}
            </Link>
          )}
        </div>

        {selected.size > 0 && (
          <div className="panel-enter mb-3 flex flex-wrap items-center gap-2 rounded-md border bg-surface-2 px-3 py-2 text-sm">
            <span className="font-medium">{selected.size} selected</span>
            {schema.actions.filter((a) => a.bulk || selected.size === 1).map((a) => (
              <Button key={a.name} size="sm" onClick={() => runAction(a)} loading={act.isPending}>{a.label}</Button>
            ))}
            {schema.permissions.delete && <Button size="sm" variant="danger" onClick={runDelete} loading={del.isPending}><Trash2 size={12} /> Delete</Button>}
            <button className="pressable pressable-sm ml-auto rounded p-0.5 text-muted hoverable" onClick={() => setSelected(new Set())} aria-label="Clear selection"><X size={14} /></button>
          </div>
        )}

        {list.error && <ErrorBox>{list.error instanceof ApiError ? list.error.message : String(list.error)}</ErrorBox>}
        {list.isPending ? <Spinner /> : rows.length === 0 ? (
          <Empty>No {schema.label_plural.toLowerCase()} found{activeFilters || search ? ' for the current filters' : ''}.</Empty>
        ) : (
          <div className={`fetching overflow-auto rounded-lg border bg-surface ${list.isFetching ? 'opacity-60' : ''}`}>
            <table className="w-full border-collapse text-sm">
              <thead className="sticky top-0 bg-surface-2 text-left text-xs uppercase tracking-wide text-muted">
                <tr>
                  <th className="w-8 px-3 py-2"><input type="checkbox" className="accent-accent" checked={allSelected} onChange={() => setSelected(allSelected ? new Set() : new Set(rows.map(idOf)))} /></th>
                  {columns.map((c) => (
                    <th key={c.name} className="px-3 py-2 font-medium whitespace-nowrap">
                      {c.sortable ? (
                        <button onClick={() => toggleSort(c.name)} className="inline-flex items-center gap-1 transition-colors duration-100 [@media(hover:hover)]:hover:text-fg">
                          {c.label}
                          {sortDir(c.name) === 'asc' && <ArrowUp size={12} />}
                          {sortDir(c.name) === 'desc' && <ArrowDown size={12} />}
                        </button>
                      ) : c.label}
                    </th>
                  ))}
                </tr>
              </thead>
              <tbody>
                {rows.map((r) => {
                  const id = idOf(r)
                  return (
                    <tr key={id} className={`row-hover cursor-pointer border-t ${selected.has(id) ? 'row-selected' : ''}`} onClick={() => navigate(`/${resource}/${encodeURIComponent(id)}`)}>
                      <td className="px-3 py-2" onClick={(e) => e.stopPropagation()}>
                        <input type="checkbox" className="accent-accent" checked={selected.has(id)} onChange={() => setSelected((s) => { const n = new Set(s); n.has(id) ? n.delete(id) : n.add(id); return n })} />
                      </td>
                      {columns.map((c) => (
                        <td key={c.name} className="max-w-xs truncate px-3 py-2">
                          {c.type === 'boolean' && r[c.name] !== null && r[c.name] !== undefined ? (
                            <Badge tone={r[c.name] ? 'success' : 'neutral'}>{formatCell(c, r[c.name])}</Badge>
                          ) : (
                            <span className={r[c.name] === null || r[c.name] === undefined ? 'text-muted' : ''}>{formatCell(c, r[c.name])}</span>
                          )}
                        </td>
                      ))}
                    </tr>
                  )
                })}
              </tbody>
            </table>
          </div>
        )}

        {total > 0 && (
          <div className="mt-3 flex flex-wrap items-center gap-2 text-sm text-muted">
            <span>{offset + 1}–{Math.min(offset + limit, total)} of {total}</span>
            <select className="field w-auto py-1" value={limit} onChange={(e) => update({ limit: e.target.value })}>
              {[10, 25, 50, 100].map((n) => <option key={n} value={n}>{n} / page</option>)}
            </select>
            <span className="ml-auto">Page {page} of {pages}</span>
            <Button size="sm" disabled={offset === 0} onClick={() => update({ offset: String(Math.max(0, offset - limit)) }, false)}><ChevronLeft size={14} /></Button>
            <Button size="sm" disabled={offset + limit >= total} onClick={() => update({ offset: String(offset + limit) }, false)}><ChevronRight size={14} /></Button>
          </div>
        )}
      </div>

      {showFilters && (
        <aside className="panel-enter w-72 shrink-0 self-start overflow-hidden rounded-lg border bg-surface">
          <div className="border-b px-4 py-2 text-sm font-medium">Filters</div>
          <FilterPanel fields={filterable} initial={filterState} onApply={(s) => update({ f: countActive(s) ? JSON.stringify(s) : null })} onClose={() => setShowFilters(false)} />
        </aside>
      )}
    </div>
  )
}
