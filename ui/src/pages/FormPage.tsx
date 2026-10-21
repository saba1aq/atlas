import { useEffect, useState, type FormEvent } from 'react'
import { Link, useNavigate, useParams } from 'react-router-dom'
import { useMutation, useQueryClient } from '@tanstack/react-query'
import { ChevronLeft, Trash2 } from 'lucide-react'
import { useRecord, useSchema } from '../lib/hooks'
import { api, ApiError } from '../lib/api'
import { isRef } from '../lib/format'
import type { Field, Row, Schema } from '../lib/types'
import { Button, ErrorBox, Spinner } from '../components/ui'
import FieldInput from '../components/FieldInput'
import { useConfirm } from '../components/Confirm'
import { useToast } from '../components/Toast'

export default function FormPage({ mode }: { mode: 'create' | 'edit' }) {
  const { resource = '', pk } = useParams()
  const schema = useSchema(resource)
  const record = useRecord(resource, mode === 'edit' ? pk : undefined)
  if (schema.isPending || (mode === 'edit' && record.isPending)) return <Spinner />
  if (schema.error) return <ErrorBox>{String(schema.error)}</ErrorBox>
  if (mode === 'edit' && record.error) return <ErrorBox>{record.error instanceof ApiError ? record.error.message : String(record.error)}</ErrorBox>
  return <RecordForm key={`${resource}:${pk ?? 'new'}`} schema={schema.data} record={mode === 'edit' ? record.data : undefined} />
}

function toPayload(fields: Field[], values: Row): Row {
  const out: Row = {}
  for (const f of fields) {
    const v = values[f.name]
    if (f.type === 'many_to_one') out[f.name] = isRef(v) ? v.id : null
    else if (f.type === 'many_to_many') out[f.name] = Array.isArray(v) ? v.map((x) => (isRef(x) ? x.id : x)) : []
    else out[f.name] = v === '' && f.type !== 'string' && f.type !== 'text' ? null : v
  }
  return out
}

function RecordForm({ schema, record }: { schema: Schema; record?: Row }) {
  const resource = schema.key
  const editing = record !== undefined
  const navigate = useNavigate()
  const qc = useQueryClient()
  const toast = useToast()
  const confirm = useConfirm()
  const editable = schema.fields.filter((f) => f.in_form && !f.read_only && !f.primary_key)
  const readonly = schema.fields.filter((f) => f.in_detail && (f.read_only || f.primary_key) && f.type !== 'one_to_many')
  const [values, setValues] = useState<Row>(() => {
    const init: Row = {}
    for (const f of editable) init[f.name] = record?.[f.name] ?? (f.type === 'many_to_many' ? [] : f.type === 'boolean' && !f.nullable ? false : null)
    return init
  })
  const [errors, setErrors] = useState<Record<string, string>>({})
  const pkValue = record ? String(record[schema.pk_field]) : null

  const save = useMutation({
    mutationFn: (payload: Row) =>
      editing ? api<Row>(`/${resource}/${pkValue}`, { method: 'PATCH', body: payload }) : api<Row>(`/${resource}`, { method: 'POST', body: payload }),
    onSuccess: (row) => {
      qc.invalidateQueries({ queryKey: ['list', resource] })
      qc.setQueryData(['record', resource, String(row[schema.pk_field])], row)
      toast(`${schema.label} ${editing ? 'saved' : 'created'}`, 'success')
      if (!editing) navigate(`/${resource}/${encodeURIComponent(String(row[schema.pk_field]))}`, { replace: true })
      setErrors({})
    },
    onError: (e) => {
      if (e instanceof ApiError) { setErrors(Object.keys(e.errors).length ? e.errors : { __all__: e.message }) } else setErrors({ __all__: String(e) })
    },
  })
  const del = useMutation({
    mutationFn: () => api(`/${resource}/${pkValue}`, { method: 'DELETE' }),
    onSuccess: () => { qc.invalidateQueries({ queryKey: ['list', resource] }); toast(`${schema.label} deleted`, 'success'); navigate(`/${resource}`) },
    onError: (e) => toast(e instanceof ApiError ? e.message : 'Delete failed', 'error'),
  })

  useEffect(() => {
    const onKey = (e: KeyboardEvent) => { if ((e.metaKey || e.ctrlKey) && e.key === 's') { e.preventDefault(); save.mutate(toPayload(editable, values)) } }
    window.addEventListener('keydown', onKey)
    return () => window.removeEventListener('keydown', onKey)
  })

  const submit = (e: FormEvent) => { e.preventDefault(); save.mutate(toPayload(editable, values)) }
  const title = editing ? `${schema.label} #${pkValue}` : `New ${schema.label}`

  return (
    <form onSubmit={submit} className="page-enter mx-auto max-w-3xl">
      <div className="mb-4 flex items-center gap-3">
        <Link to={`/${resource}`} className="pressable pressable-sm rounded-md p-1.5 text-muted hoverable" aria-label="Back"><ChevronLeft size={18} /></Link>
        <h1 className="text-xl font-semibold tracking-tight">{title}</h1>
        <div className="ml-auto flex gap-2">
          {editing && schema.permissions.delete && (
            <Button type="button" variant="danger" loading={del.isPending} onClick={async () => { if (await confirm({ title: `Delete ${schema.label} #${pkValue}?`, confirmLabel: 'Delete', danger: true })) del.mutate() }}>
              <Trash2 size={14} /> Delete
            </Button>
          )}
          <Button type="submit" variant="primary" loading={save.isPending} disabled={editing ? !schema.permissions.edit : !schema.permissions.create}>
            {editing ? 'Save' : 'Create'}
          </Button>
        </div>
      </div>
      {errors.__all__ && <div className="mb-4"><ErrorBox>{errors.__all__}</ErrorBox></div>}
      <div className="space-y-5 rounded-lg border bg-surface p-5">
        {editable.map((f) => (
          <div key={f.name} className="grid gap-1 sm:grid-cols-[180px_1fr] sm:gap-4">
            <label className="pt-1.5 text-sm text-muted" htmlFor={`f-${f.name}`}>
              {f.label}{f.required && !f.has_default && <span className="text-danger"> *</span>}
            </label>
            <div>
              <FieldInput field={f} value={values[f.name]} error={errors[f.name]} disabled={editing ? !schema.permissions.edit : !schema.permissions.create}
                onChange={(v) => { setValues((s) => ({ ...s, [f.name]: v })); if (errors[f.name]) setErrors(({ [f.name]: _, ...rest }) => rest) }} />
              {errors[f.name] && <p className="mt-1 text-xs text-danger">{errors[f.name]}</p>}
              {f.help_text && !errors[f.name] && <p className="mt-1 text-xs text-muted">{f.help_text}</p>}
            </div>
          </div>
        ))}
        {editing && readonly.length > 0 && (
          <div className="border-t pt-4">
            <dl className="grid gap-x-4 gap-y-2 text-sm sm:grid-cols-[180px_1fr]">
              {readonly.map((f) => (
                <ReadOnly key={f.name} field={f} value={record?.[f.name]} />
              ))}
            </dl>
          </div>
        )}
      </div>
    </form>
  )
}

function ReadOnly({ field, value }: { field: Field; value: unknown }) {
  let text: string
  if (value === null || value === undefined) text = '—'
  else if (isRef(value)) text = value.label
  else if (Array.isArray(value)) text = value.map((v) => (isRef(v) ? v.label : String(v))).join(', ')
  else if (typeof value === 'object') text = JSON.stringify(value)
  else text = String(value)
  return (<><dt className="text-muted">{field.label}</dt><dd className="font-mono text-xs leading-5 break-all">{text}</dd></>)
}
