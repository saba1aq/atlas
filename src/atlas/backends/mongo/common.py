"""Shared pieces for MongoDB backends: Pydantic introspection, filter translation, BSON coercion."""

from __future__ import annotations

import datetime as dt
import decimal
import enum
import re
import types
import typing
import uuid
from collections.abc import Sequence
from dataclasses import dataclass
from typing import Any, get_args, get_origin

from bson import ObjectId
from bson.decimal128 import Decimal128
from pydantic import BaseModel
from pydantic.fields import FieldInfo

from atlas.core.exceptions import ValidationError
from atlas.core.filters import Condition, FilterGroup, Op
from atlas.core.query import ListQuery
from atlas.core.schema import Choice, FieldSchema, FieldType, ModelSchema, Relation


@dataclass(frozen=True, slots=True)
class Ref:
    """Marks a Pydantic field as a reference to another registered model.

    author: Annotated[int | None, Ref(Author)] = None          # many_to_one
    tags: Annotated[list[int], Ref(Author)] = []               # many_to_many
    """

    model: type


_SCALARS: dict[type, FieldType] = {
    str: FieldType.STRING,
    int: FieldType.INTEGER,
    float: FieldType.FLOAT,
    decimal.Decimal: FieldType.DECIMAL,
    bool: FieldType.BOOLEAN,
    dt.datetime: FieldType.DATETIME,
    dt.date: FieldType.DATE,
    dt.time: FieldType.TIME,
    uuid.UUID: FieldType.UUID,
    dict: FieldType.JSON,
    list: FieldType.JSON,
    ObjectId: FieldType.STRING,
}


def _unwrap(annotation: Any) -> tuple[Any, bool, list[Any]]:
    """Return (core type, nullable, metadata) stripping Optional/Annotated."""
    metadata: list[Any] = []
    nullable = False
    ann = annotation
    while True:
        origin = get_origin(ann)
        if origin is typing.Annotated:
            args = get_args(ann)
            metadata.extend(args[1:])
            ann = args[0]
            continue
        if origin in (typing.Union, types.UnionType):
            non_null = [a for a in get_args(ann) if a is not type(None)]
            nullable = len(non_null) < len(get_args(ann))
            ann = non_null[0] if len(non_null) == 1 else Any
            continue
        return ann, nullable, metadata


def field_from_annotation(
    name: str, annotation: Any, info: FieldInfo | None, *, extra_metadata: Sequence[Any] = ()
) -> FieldSchema:
    core, nullable, metadata = _unwrap(annotation)
    metadata = [*metadata, *(info.metadata if info is not None else []), *extra_metadata]
    has_default = info is not None and not info.is_required()
    required = not nullable and not has_default
    ref = next((m for m in metadata if isinstance(m, Ref)), None)
    description = (info.description if info is not None else None) or ""
    base: dict[str, Any] = {
        "nullable": nullable,
        "required": required,
        "has_default": has_default,
        "help_text": description,
        "label": (info.title if info is not None else None) or "",
    }
    if ref is not None:
        origin = get_origin(core)
        if origin in (list, set, tuple) or core in (list, set, tuple):
            return FieldSchema(
                name,
                FieldType.MANY_TO_MANY,
                relation=Relation(model=ref.model, kind=FieldType.MANY_TO_MANY),
                sortable=False,
                **{**base, "nullable": True, "required": False},
            )
        return FieldSchema(
            name,
            FieldType.MANY_TO_ONE,
            relation=Relation(model=ref.model, kind=FieldType.MANY_TO_ONE),
            sortable=False,
            **base,
        )
    extra: dict[str, Any] = {}
    origin = get_origin(core)
    if origin is typing.Literal:
        extra["choices"] = [Choice(v, str(v).replace("_", " ").title()) for v in get_args(core)]
        return FieldSchema(name, FieldType.ENUM, **base, **extra)
    if isinstance(core, type) and issubclass(core, enum.Enum):
        extra["choices"] = [Choice(m.value, m.name.replace("_", " ").title()) for m in core]
        return FieldSchema(name, FieldType.ENUM, **base, **extra)
    if origin in (list, dict, set, tuple):
        return FieldSchema(name, FieldType.JSON, **base)
    ftype = _SCALARS.get(core, FieldType.STRING) if isinstance(core, type) else FieldType.JSON
    if ftype == FieldType.STRING:
        for m in metadata:
            max_length = getattr(m, "max_length", None)
            if max_length:
                extra["max_length"] = max_length
    return FieldSchema(name, ftype, **base, **extra)


def introspect_pydantic(
    model: type[BaseModel], *, pk_field: str = "id", pk_alias: str = "_id"
) -> ModelSchema:
    fields: list[FieldSchema] = []
    pk_found = False
    for name, info in model.model_fields.items():
        if name == pk_field or info.alias == pk_alias:
            f = field_from_annotation(pk_field, info.annotation, info)
            f.primary_key = True
            f.read_only = True
            f.has_default = True
            f.required = False
            f.nullable = False
            f.filterable = True
            fields.insert(0, f)
            pk_found = True
            continue
        fields.append(field_from_annotation(name, info.annotation, info))
    if not pk_found:
        fields.insert(
            0,
            FieldSchema(
                pk_field,
                FieldType.STRING,
                primary_key=True,
                read_only=True,
                has_default=True,
                nullable=False,
            ),
        )
    label = model.__name__
    return ModelSchema(
        key=label.lower(), label=label, label_plural=f"{label}s", pk_field=pk_field, fields=fields
    )


# ---- values ----------------------------------------------------------------------------------


def parse_pk(raw: Any) -> Any:
    """Turn a pk from the URL/JSON into what is stored in ``_id``."""
    if isinstance(raw, ObjectId | int):
        return raw
    if isinstance(raw, str):
        if ObjectId.is_valid(raw) and len(raw) == 24:
            return ObjectId(raw)
        if raw.lstrip("-").isdigit():
            return int(raw)
    return raw


def pk_to_json(value: Any) -> Any:
    return str(value) if isinstance(value, ObjectId) else value


def to_bson(f: FieldSchema, value: Any) -> Any:
    if value is None:
        return None
    if (
        f.type == FieldType.DATE
        and isinstance(value, dt.date)
        and not isinstance(value, dt.datetime)
    ):
        return dt.datetime(value.year, value.month, value.day)
    if f.type == FieldType.TIME and isinstance(value, dt.time):
        return value.isoformat()
    if f.type == FieldType.DECIMAL and isinstance(value, decimal.Decimal):
        return Decimal128(value)
    if f.type == FieldType.UUID and isinstance(value, uuid.UUID):
        return value  # bson handles uuid natively (binary subtype 4)
    if isinstance(value, enum.Enum):
        return value.value
    if f.type == FieldType.MANY_TO_ONE:
        return parse_pk(value)
    if f.type == FieldType.MANY_TO_MANY:
        return [parse_pk(v) for v in value]
    return value


def from_bson(f: FieldSchema, value: Any) -> Any:
    if value is None:
        return None
    if f.type == FieldType.DATE and isinstance(value, dt.datetime):
        return value.date()
    if f.type == FieldType.TIME and isinstance(value, str):
        try:
            return dt.time.fromisoformat(value)
        except ValueError:
            return value
    if isinstance(value, Decimal128):
        return value.to_decimal()
    if isinstance(value, ObjectId):
        return str(value)
    return value


# ---- queries ---------------------------------------------------------------------------------


def condition_to_mongo(
    schema: ModelSchema, cond: Condition, *, id_path: str = ""
) -> dict[str, Any]:
    """``id_path`` is appended to relation fields stored as sub-documents (Beanie: ".$id")."""
    f = schema.field(cond.field)
    path = "_id" if f.primary_key else f.name
    if f.is_relation:
        path = f"{f.name}{id_path}"
    op, value = cond.op, cond.value
    if f.is_relation:
        values = [parse_pk(v) for v in (value if isinstance(value, list) else [value])]
        if op in (Op.EQ, Op.IN):
            return {path: {"$in": values}}
        if op in (Op.NE, Op.NOT_IN):
            return {path: {"$nin": values}}
        if op == Op.IS_NULL:
            return {path: None} if value else {path: {"$ne": None}}
        raise ValidationError({f.name: f"operator {op.value} not supported for relations"})
    if f.primary_key:
        value = [parse_pk(v) for v in value] if isinstance(value, list) else parse_pk(value)
    else:
        value = [to_bson(f, v) for v in value] if isinstance(value, list) else to_bson(f, value)
    if op == Op.EQ:
        return {path: value}
    if op == Op.NE:
        return {path: {"$ne": value}}
    if op == Op.LT:
        return {path: {"$lt": value}}
    if op == Op.LTE:
        return {path: {"$lte": value}}
    if op == Op.GT:
        return {path: {"$gt": value}}
    if op == Op.GTE:
        return {path: {"$gte": value}}
    if op == Op.IN:
        return {path: {"$in": list(value or [])}}
    if op == Op.NOT_IN:
        return {path: {"$nin": list(value or [])}}
    if op == Op.CONTAINS:
        return {path: {"$regex": re.escape(str(value))}}
    if op == Op.ICONTAINS:
        return {path: {"$regex": re.escape(str(value)), "$options": "i"}}
    if op == Op.STARTSWITH:
        return {path: {"$regex": "^" + re.escape(str(value))}}
    if op == Op.ENDSWITH:
        return {path: {"$regex": re.escape(str(value)) + "$"}}
    if op == Op.IS_NULL:
        return {path: None} if value else {path: {"$ne": None}}
    if op == Op.BETWEEN:
        lo, hi = value
        return {path: {"$gte": lo, "$lte": hi}}
    raise ValidationError({f.name: f"unsupported operator {op.value}"})


def group_to_mongo(schema: ModelSchema, group: FilterGroup, *, id_path: str = "") -> dict[str, Any]:
    parts = [
        condition_to_mongo(schema, i, id_path=id_path)
        if isinstance(i, Condition)
        else group_to_mongo(schema, i, id_path=id_path)
        for i in group.items
    ]
    parts = [p for p in parts if p]
    if not parts:
        return {}
    if len(parts) == 1:
        return parts[0]
    return {"$and": parts} if group.logic == "and" else {"$or": parts}


def build_query(schema: ModelSchema, query: ListQuery, *, id_path: str = "") -> dict[str, Any]:
    q = group_to_mongo(schema, query.filters, id_path=id_path)
    if query.search:
        regex = {"$regex": re.escape(query.search), "$options": "i"}
        searchable = [f.name for f in schema.fields if f.searchable and not f.primary_key]
        if searchable:
            search_q = {"$or": [{n: regex} for n in searchable]}
            q = {"$and": [q, search_q]} if q else search_q
    return q


def build_sort(schema: ModelSchema, query: ListQuery) -> list[tuple[str, int]]:
    sort = [("_id" if n == schema.pk_field else n, -1 if d == "desc" else 1) for n, d in query.sort]
    sort.append(("_id", 1))
    return sort


__all__ = [
    "Ref",
    "build_query",
    "build_sort",
    "from_bson",
    "introspect_pydantic",
    "parse_pk",
    "pk_to_json",
    "to_bson",
]
