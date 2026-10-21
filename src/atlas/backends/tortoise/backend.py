"""Tortoise ORM backend. Requires ``Tortoise.init()`` to have run before the first request
(relations are resolved by Tortoise at init time), so schemas are built lazily by core.
"""

from __future__ import annotations

import builtins
import enum
from collections.abc import Sequence
from typing import Any, cast

from tortoise import fields as tf
from tortoise.expressions import Q
from tortoise.models import Model
from tortoise.queryset import QuerySet

from atlas.core.exceptions import ValidationError
from atlas.core.filters import Condition, FilterGroup, Op
from atlas.core.model_admin import ModelAdmin
from atlas.core.query import ListQuery, Page
from atlas.core.schema import Choice, FieldSchema, FieldType, ModelSchema, Relation

_SCALAR_TYPES: list[tuple[type, FieldType]] = [
    (tf.BooleanField, FieldType.BOOLEAN),
    (tf.IntField, FieldType.INTEGER),
    (tf.BigIntField, FieldType.INTEGER),
    (tf.SmallIntField, FieldType.INTEGER),
    (tf.FloatField, FieldType.FLOAT),
    (tf.DecimalField, FieldType.DECIMAL),
    (tf.DatetimeField, FieldType.DATETIME),
    (tf.DateField, FieldType.DATE),
    (tf.TimeField, FieldType.TIME),
    (tf.UUIDField, FieldType.UUID),
    (tf.JSONField, FieldType.JSON),
    (tf.TextField, FieldType.TEXT),
    (tf.CharField, FieldType.STRING),
]


def _scalar_type(f: tf.Field[Any]) -> tuple[FieldType, dict[str, Any]]:
    extra: dict[str, Any] = {}
    enum_type = getattr(f, "enum_type", None)
    if enum_type is not None:
        extra["choices"] = [Choice(m.value, m.name.replace("_", " ").title()) for m in enum_type]
        return FieldType.ENUM, extra
    for cls, ftype in _SCALAR_TYPES:
        if isinstance(f, cls):
            if ftype == FieldType.STRING:
                extra["max_length"] = getattr(f, "max_length", None)
            return ftype, extra
    return FieldType.STRING, extra


class TortoiseBackend:
    name = "tortoise"

    def supports(self, model: type) -> bool:
        return isinstance(model, type) and issubclass(model, Model)

    def introspect(self, model: type, admin: ModelAdmin) -> ModelSchema:
        meta = model._meta  # type: ignore[attr-defined]
        if not meta.fields_map:
            raise RuntimeError(
                f"{model.__name__}: Tortoise is not initialised; "
                "call Tortoise.init() before using the admin"
            )
        fk_source_cols = {
            meta.fields_map[name].source_field for name in (meta.fk_fields | meta.o2o_fields)
        }
        fields: list[FieldSchema] = []
        relations: list[FieldSchema] = []
        for name, f in meta.fields_map.items():
            if name in fk_source_cols:
                continue
            if name in meta.fk_fields or name in meta.o2o_fields:
                relations.append(
                    FieldSchema(
                        name,
                        FieldType.MANY_TO_ONE,
                        nullable=bool(f.null),
                        required=not f.null and f.default is None,
                        relation=Relation(model=f.related_model, kind=FieldType.MANY_TO_ONE),
                        help_text=f.description or "",
                        sortable=False,
                    )
                )
            elif name in meta.m2m_fields:
                relations.append(
                    FieldSchema(
                        name,
                        FieldType.MANY_TO_MANY,
                        nullable=True,
                        relation=Relation(model=f.related_model, kind=FieldType.MANY_TO_MANY),
                        help_text=f.description or "",
                        sortable=False,
                    )
                )
            elif name in meta.backward_fk_fields or name in meta.backward_o2o_fields:
                relations.append(
                    FieldSchema(
                        name,
                        FieldType.ONE_TO_MANY,
                        read_only=True,
                        relation=Relation(model=f.related_model, kind=FieldType.ONE_TO_MANY),
                        sortable=False,
                        filterable=False,
                    )
                )
            else:
                ftype, extra = _scalar_type(f)
                is_pk = bool(f.pk)
                generated = bool(getattr(f, "generated", False))
                has_default = (
                    f.default is not None
                    or generated
                    or bool(getattr(f, "auto_now", False))
                    or bool(getattr(f, "auto_now_add", False))
                )
                nullable = bool(f.null) and not is_pk
                fields.append(
                    FieldSchema(
                        name,
                        ftype,
                        primary_key=is_pk,
                        required=not nullable and not has_default,
                        nullable=nullable,
                        read_only=(is_pk and generated)
                        or bool(getattr(f, "auto_now", False))
                        or bool(getattr(f, "auto_now_add", False)),
                        has_default=has_default,
                        help_text=f.description or "",
                        **extra,
                    )
                )
        fields.extend(relations)
        name = model.__name__
        return ModelSchema(
            key=name.lower(),
            label=name,
            label_plural=f"{name}s",
            pk_field=meta.pk_attr,
            fields=fields,
        )

    def repository(self, model: type, schema: ModelSchema, admin: ModelAdmin) -> TortoiseRepository:
        return TortoiseRepository(self, model, schema, admin)


def _q(**kwargs: Any) -> Q:
    return Q(**kwargs)


_LOOKUPS = {
    Op.EQ: "",
    Op.LT: "__lt",
    Op.LTE: "__lte",
    Op.GT: "__gt",
    Op.GTE: "__gte",
    Op.IN: "__in",
    Op.CONTAINS: "__contains",
    Op.ICONTAINS: "__icontains",
    Op.STARTSWITH: "__startswith",
    Op.ENDSWITH: "__endswith",
}


class TortoiseRepository:
    def __init__(
        self, backend: TortoiseBackend, model: type[Model], schema: ModelSchema, admin: ModelAdmin
    ) -> None:
        self.backend = backend
        self.model = model
        self.schema = schema
        self.admin = admin
        self.meta = model._meta
        self._prefetch = [
            f.name
            for f in schema.fields
            if f.type in (FieldType.MANY_TO_ONE, FieldType.MANY_TO_MANY)
        ]

    # ---- query building ---------------------------------------------------------------------

    def _lookup_name(self, f: FieldSchema) -> str:
        if f.type == FieldType.MANY_TO_ONE:
            return str(self.meta.fields_map[f.name].source_field)
        if f.type == FieldType.MANY_TO_MANY:
            target_pk = f.relation.model._meta.pk_attr if f.relation else "id"
            return f"{f.name}__{target_pk}"
        return f.name

    def _condition(self, cond: Condition) -> Q:
        f = self.schema.field(cond.field)
        name = self._lookup_name(f)
        op, value = cond.op, cond.value
        if op == Op.IS_NULL:
            return _q(**{f"{name}__isnull": bool(value)})
        if op == Op.NE:
            return ~_q(**{name: value})
        if op == Op.NOT_IN:
            return ~_q(**{f"{name}__in": list(value or [])})
        if op == Op.BETWEEN:
            lo, hi = value
            return _q(**{f"{name}__gte": lo}) & Q(**{f"{name}__lte": hi})
        if f.type == FieldType.MANY_TO_MANY and op == Op.EQ:
            return _q(**{f"{name}__in": value if isinstance(value, list) else [value]})
        if op == Op.IN:
            return _q(**{f"{name}__in": list(value or [])})
        return _q(**{f"{name}{_LOOKUPS[op]}": value})

    def _group(self, group: FilterGroup) -> Q | None:
        q: Q | None = None
        for item in group.items:
            part = self._condition(item) if isinstance(item, Condition) else self._group(item)
            if part is None:
                continue
            if q is None:
                q = part
            elif group.logic == "and":
                q = q & part
            else:
                q = q | part
        return q

    def _apply(self, query: ListQuery) -> QuerySet[Any]:
        qs: QuerySet[Any] = self.model.all()
        q = self._group(query.filters)
        if q is not None:
            qs = qs.filter(q)
        if query.search:
            search_q: Q | None = None
            for f in self.schema.fields:
                if not f.searchable:
                    continue
                part = Q(**{f"{f.name}__icontains": query.search})
                search_q = part if search_q is None else (search_q | part)
            if search_q is not None:
                qs = qs.filter(search_q)
        return qs

    def _ordered(self, qs: QuerySet[Any], query: ListQuery) -> QuerySet[Any]:
        order = [f"-{n}" if d == "desc" else n for n, d in query.sort]
        order.append(self.meta.pk_attr)
        return qs.order_by(*order)

    # ---- Repository API ---------------------------------------------------------------------

    async def list(self, query: ListQuery) -> Page[Any]:
        qs = self._apply(query)
        total = await qs.count()
        items = await (
            self._ordered(qs, query)
            .offset(query.offset)
            .limit(query.limit)
            .prefetch_related(*self._prefetch)
        )
        return Page(items=items, total=total)

    async def count(self, query: ListQuery) -> int:
        return await self._apply(query).count()

    async def get(self, pk: Any) -> Any | None:
        return await self.model.filter(pk=pk).prefetch_related(*self._prefetch).first()

    async def get_many(self, pks: Sequence[Any]) -> Sequence[Any]:
        return await self.model.filter(pk__in=list(pks)).prefetch_related(*self._prefetch)

    async def _assign(
        self, obj: Model, data: dict[str, Any]
    ) -> builtins.list[tuple[str, builtins.list[Any]]]:
        """Set scalar and FK fields on ``obj``; return pending m2m assignments."""
        m2m: builtins.list[tuple[str, builtins.list[Any]]] = []
        for name, value in data.items():
            f = self.schema.field(name)
            if f.type == FieldType.MANY_TO_ONE:
                if value is not None and f.relation is not None:
                    exists = await f.relation.model.filter(pk=value).exists()
                    if not exists:
                        raise ValidationError({name: "related object does not exist"})
                setattr(obj, str(self.meta.fields_map[name].source_field), value)
            elif f.type == FieldType.MANY_TO_MANY:
                m2m.append((name, list(value or [])))
            else:
                setattr(obj, name, value)
        return m2m

    async def _set_m2m(
        self, obj: Model, pending: builtins.list[tuple[str, builtins.list[Any]]]
    ) -> None:
        for name, ids in pending:
            f = self.schema.field(name)
            assert f.relation is not None
            targets = await f.relation.model.filter(pk__in=ids) if ids else []
            if len(targets) != len(set(ids)):
                raise ValidationError({name: "some related objects do not exist"})
            relation = getattr(obj, name)
            await relation.clear()
            if targets:
                await relation.add(*targets)

    async def create(self, data: dict[str, Any]) -> Any:
        obj = self.model()
        m2m = await self._assign(obj, data)
        await obj.save()
        await self._set_m2m(obj, m2m)
        return await self.get(obj.pk)

    async def update(self, obj: Any, data: dict[str, Any]) -> Any:
        m2m = await self._assign(obj, data)
        await obj.save()
        await self._set_m2m(obj, m2m)
        return await self.get(obj.pk)

    async def delete(self, objs: Sequence[Any]) -> int:
        pks = [o.pk for o in objs]
        if not pks:
            return 0
        qs = self.model.filter(pk__in=pks)
        count = await qs.count()  # .delete() rowcount may include m2m through-table rows
        await qs.delete()
        return count

    # ---- serialization ----------------------------------------------------------------------

    def pk_of(self, obj: Any) -> Any:
        return obj.pk

    def label_of(self, obj: Any) -> str:
        if _has_custom_str(obj):
            return str(obj)
        for f in self.schema.fields:
            if f.type == FieldType.STRING and getattr(obj, f.name, None):
                return str(getattr(obj, f.name))
        return f"{self.schema.label} #{obj.pk}"

    def _ref(self, related: Any) -> dict[str, Any] | None:
        if related is None:
            return None
        res = self.admin.site.resource_for_model(type(related))
        label = res.repository.label_of(related) if res else _generic_label(related)
        return {"id": related.pk, "label": label}

    def to_dict(self, obj: Any) -> dict[str, Any]:
        out: dict[str, Any] = {}
        for f in self.schema.fields:
            if f.type == FieldType.ONE_TO_MANY:
                continue
            if f.type == FieldType.MANY_TO_ONE:
                out[f.name] = self._ref(getattr(obj, f.name))
            elif f.type == FieldType.MANY_TO_MANY:
                out[f.name] = [self._ref(v) for v in getattr(obj, f.name)]
            else:
                value = getattr(obj, f.name)
                out[f.name] = value.value if isinstance(value, enum.Enum) else value
        return out


def _has_custom_str(obj: Any) -> bool:
    return cast(Any, type(obj)).__str__ is not Model.__str__


def _generic_label(obj: Any) -> str:
    if _has_custom_str(obj):
        return str(obj)
    for name in ("name", "title", "label", "username", "email"):
        v = getattr(obj, name, None)
        if v:
            return str(v)
    return f"{type(obj).__name__} #{obj.pk}"
