"""In-memory backend: reference implementation of the Repository contract, used by core tests.

Models are plain classes; their schema is passed explicitly. Rows are dicts keyed by pk.
"""

from __future__ import annotations

from collections.abc import Sequence
from typing import Any

from atlas.core.exceptions import ValidationError
from atlas.core.filters import Condition, FilterGroup, Op
from atlas.core.model_admin import ModelAdmin
from atlas.core.query import ListQuery, Page
from atlas.core.schema import FieldType, ModelSchema


def matches(cond: Condition, value: Any) -> bool:  # noqa: C901
    return bool(_matches(cond, value))


def _matches(cond: Condition, value: Any) -> Any:
    op, target = cond.op, cond.value
    if op == Op.IS_NULL:
        return (value is None) == bool(target)
    if op == Op.EQ:
        return value == target
    if op == Op.NE:
        return value != target
    if value is None:
        return False
    if op == Op.LT:
        return value < target
    if op == Op.LTE:
        return value <= target
    if op == Op.GT:
        return value > target
    if op == Op.GTE:
        return value >= target
    if op == Op.IN:
        if isinstance(value, list):  # many_to_many: any overlap
            return any(v in (target or []) for v in value)
        return value in (target or [])
    if op == Op.NOT_IN:
        if isinstance(value, list):
            return not any(v in (target or []) for v in value)
        return value not in (target or [])
    if op == Op.CONTAINS:
        return str(target) in str(value)
    if op == Op.ICONTAINS:
        return str(target).lower() in str(value).lower()
    if op == Op.STARTSWITH:
        return str(value).startswith(str(target))
    if op == Op.ENDSWITH:
        return str(value).endswith(str(target))
    if op == Op.BETWEEN:
        lo, hi = target
        return lo <= value <= hi
    raise ValueError(op)


def matches_group(group: FilterGroup, row: dict[str, Any]) -> bool:
    if group.is_empty():
        return True
    results = (
        matches(i, row.get(i.field)) if isinstance(i, Condition) else matches_group(i, row)
        for i in group.items
    )
    return all(results) if group.logic == "and" else any(results)


class MemoryRepository:
    def __init__(
        self, backend: MemoryBackend, model: type, schema: ModelSchema, admin: ModelAdmin
    ) -> None:
        self.backend = backend
        self.model = model
        self.schema = schema
        self.admin = admin
        self.rows: dict[Any, dict[str, Any]] = backend.storage.setdefault(model, {})

    def _next_pk(self) -> int:
        existing = [p for p in self.rows if isinstance(p, int)]
        return (max(existing) + 1) if existing else 1

    def _apply(self, query: ListQuery) -> list[dict[str, Any]]:
        rows = [r for r in self.rows.values() if matches_group(query.filters, r)]
        if query.search:
            term = query.search.lower()
            searchable = [f.name for f in self.schema.fields if f.searchable]
            rows = [r for r in rows if any(term in str(r.get(n) or "").lower() for n in searchable)]
        for name, direction in reversed(query.sort):
            rows.sort(key=lambda r: (r.get(name) is None, r.get(name)), reverse=direction == "desc")
        return rows

    async def list(self, query: ListQuery) -> Page[dict[str, Any]]:
        rows = self._apply(query)
        return Page(items=rows[query.offset : query.offset + query.limit], total=len(rows))

    async def count(self, query: ListQuery) -> int:
        return len(self._apply(query))

    async def get(self, pk: Any) -> dict[str, Any] | None:
        return self.rows.get(pk)

    async def get_many(self, pks: Sequence[Any]) -> Sequence[dict[str, Any]]:
        return [self.rows[p] for p in pks if p in self.rows]

    def _check_relations(self, data: dict[str, Any]) -> None:
        for name, value in data.items():
            f = self.schema.field(name)
            if not f.is_relation or f.relation is None or value is None:
                continue
            rows = self.backend.storage.get(f.relation.model, {})
            ids = value if isinstance(value, list) else [value]
            if any(i not in rows for i in ids):
                raise ValidationError({name: "related object does not exist"})

    async def create(self, data: dict[str, Any]) -> dict[str, Any]:
        self._check_relations(data)
        pk_name = self.schema.pk_field
        row: dict[str, Any] = {
            f.name: None for f in self.schema.fields if f.type != FieldType.ONE_TO_MANY
        }
        row.update(data)
        if row.get(pk_name) is None:
            row[pk_name] = self._next_pk()
        if row[pk_name] in self.rows:
            raise ValidationError({pk_name: "already exists"})
        self.rows[row[pk_name]] = row
        return row

    async def update(self, obj: dict[str, Any], data: dict[str, Any]) -> dict[str, Any]:
        self._check_relations(data)
        obj.update(data)
        return obj

    async def delete(self, objs: Sequence[dict[str, Any]]) -> int:
        n = 0
        for o in objs:
            if self.rows.pop(o[self.schema.pk_field], None) is not None:
                n += 1
        return n

    def pk_of(self, obj: dict[str, Any]) -> Any:
        return obj[self.schema.pk_field]

    def label_of(self, obj: dict[str, Any]) -> str:
        for f in self.schema.fields:
            if f.type == FieldType.STRING and obj.get(f.name):
                return str(obj[f.name])
        return f"{self.schema.label} #{self.pk_of(obj)}"

    def _related(self, f: Any, pk: Any) -> dict[str, Any]:
        rows = self.backend.storage.get(f.relation.model, {})
        target_schema = self.backend.schemas.get(f.relation.model)
        row = rows.get(pk)
        if row is None or target_schema is None:
            return {"id": pk, "label": str(pk)}
        repo = MemoryRepository(self.backend, f.relation.model, target_schema, self.admin)
        return {"id": pk, "label": repo.label_of(row)}

    def to_dict(self, obj: dict[str, Any]) -> dict[str, Any]:
        out: dict[str, Any] = {}
        for f in self.schema.fields:
            if f.type == FieldType.ONE_TO_MANY:
                continue
            v = obj.get(f.name)
            if f.type == FieldType.MANY_TO_ONE:
                out[f.name] = None if v is None else self._related(f, v)
            elif f.type == FieldType.MANY_TO_MANY:
                out[f.name] = [self._related(f, i) for i in (v or [])]
            else:
                out[f.name] = v
        return out


class MemoryBackend:
    name = "memory"

    def __init__(self, schemas: dict[type, ModelSchema] | None = None) -> None:
        self.schemas: dict[type, ModelSchema] = dict(schemas or {})
        self.storage: dict[type, dict[Any, dict[str, Any]]] = {}

    def add(self, model: type, schema: ModelSchema) -> None:
        self.schemas[model] = schema

    def supports(self, model: type) -> bool:
        return model in self.schemas

    def introspect(self, model: type, admin: ModelAdmin) -> ModelSchema:
        import copy

        return copy.deepcopy(self.schemas[model])

    def repository(self, model: type, schema: ModelSchema, admin: ModelAdmin) -> MemoryRepository:
        return MemoryRepository(self, model, schema, admin)

    def seed(self, model: type, rows: list[dict[str, Any]]) -> None:
        pk = self.schemas[model].pk_field
        self.storage.setdefault(model, {}).update({r[pk]: dict(r) for r in rows})
