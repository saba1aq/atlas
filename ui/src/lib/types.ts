export type FieldType =
  | 'string' | 'text' | 'integer' | 'float' | 'decimal' | 'boolean' | 'date' | 'datetime'
  | 'time' | 'uuid' | 'json' | 'enum' | 'many_to_one' | 'many_to_many' | 'one_to_many'

export interface Choice { value: string | number; label: string }

export interface Field {
  name: string
  type: FieldType
  label: string
  primary_key: boolean
  required: boolean
  nullable: boolean
  read_only: boolean
  has_default: boolean
  max_length: number | null
  choices: Choice[] | null
  relation: { resource: string | null; kind: FieldType } | null
  help_text: string
  sortable: boolean
  searchable: boolean
  filterable: boolean
  in_list: boolean
  in_form: boolean
  in_detail: boolean
}

export interface Action { name: string; label: string; confirm: string | null; icon: string | null; bulk: boolean }

export interface Schema {
  key: string
  label: string
  label_plural: string
  pk_field: string
  fields: Field[]
  icon: string | null
  page_size: number
  ordering: string[]
  actions: Action[]
  permissions: { create: boolean; edit: boolean; delete: boolean }
}

export interface ResourceInfo { key: string; label: string; label_plural: string; icon: string | null }
export interface User { id: string | number; username: string; display_name: string; is_superuser: boolean }
export interface SiteInfo { title: string; resources: ResourceInfo[]; user: User | null; auth_enabled: boolean }

export interface Ref { id: string | number; label: string }
export type Row = Record<string, unknown>
export interface Page { items: Row[]; total: number }

export type FilterOp = 'eq' | 'ne' | 'lt' | 'lte' | 'gt' | 'gte' | 'in' | 'not_in' | 'contains'
  | 'icontains' | 'startswith' | 'endswith' | 'is_null' | 'between'
export interface Condition { field: string; op: FilterOp; value?: unknown }
