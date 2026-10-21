"""Turn JSON input into typed Python values according to a ``ModelSchema``."""

from __future__ import annotations

import datetime as dt
import decimal
import json
import uuid
from typing import Any

from .exceptions import BadRequest, ValidationError
from .filters import Condition, Op
from .schema import FieldSchema, FieldType, ModelSchema


def coerce_input(schema: ModelSchema, data: Any, *, partial: bool) -> dict[str, Any]:
    """Validate and convert a create (``partial=False``) or update (``partial=True``) payload.

    Unknown, read-only, primary-key and one_to_many fields are dropped silently.
    """
    if not isinstance(data, dict):
        raise ValidationError({"__all__": "expected a JSON object"})
    errors: dict[str, str] = {}
    out: dict[str, Any] = {}
    for f in schema.fields:
        if f.primary_key or f.read_only or not f.in_form or f.type == FieldType.ONE_TO_MANY:
            continue
        if f.name not in data:
            if not partial and f.required and not f.has_default and not f.nullable:
                errors[f.name] = "This field is required."
            continue
        raw = data[f.name]
        if raw is None or (raw == "" and f.type not in (FieldType.STRING, FieldType.TEXT)):
            if f.type == FieldType.MANY_TO_MANY:
                out[f.name] = []
            elif f.nullable:
                out[f.name] = None
            elif f.has_default and raw is None:
                continue
            else:
                errors[f.name] = "This field may not be null."
            continue
        try:
            out[f.name] = coerce_value(f, raw)
        except (ValueError, TypeError, decimal.InvalidOperation) as exc:
            errors[f.name] = str(exc) or "Invalid value."
    if errors:
        raise ValidationError(errors)
    return out


def coerce_value(f: FieldSchema, raw: Any) -> Any:  # noqa: C901 - one branch per type is the clearest form
    t = f.type
    if t in (FieldType.STRING, FieldType.TEXT):
        if not isinstance(raw, str):
            raw = str(raw)
        if f.max_length and len(raw) > f.max_length:
            raise ValueError(f"Ensure this value has at most {f.max_length} characters.")
        return raw
    if t == FieldType.INTEGER:
        if isinstance(raw, bool):
            raise ValueError("Expected an integer.")
        if isinstance(raw, str):
            raw = raw.strip()
        return int(raw)
    if t == FieldType.FLOAT:
        if isinstance(raw, bool):
            raise ValueError("Expected a number.")
        return float(raw)
    if t == FieldType.DECIMAL:
        if isinstance(raw, bool):
            raise ValueError("Expected a decimal number.")
        return decimal.Decimal(str(raw))
    if t == FieldType.BOOLEAN:
        if isinstance(raw, bool):
            return raw
        if isinstance(raw, str) and raw.lower() in ("true", "1", "yes", "on"):
            return True
        if isinstance(raw, str) and raw.lower() in ("false", "0", "no", "off"):
            return False
        if isinstance(raw, int) and raw in (0, 1):
            return bool(raw)
        raise ValueError("Expected a boolean.")
    if t == FieldType.DATE:
        if isinstance(raw, dt.datetime):
            return raw.date()
        if isinstance(raw, dt.date):
            return raw
        return dt.date.fromisoformat(str(raw)[:10])
    if t == FieldType.DATETIME:
        if isinstance(raw, dt.datetime):
            return raw
        s = str(raw).strip()
        if s.endswith("Z"):
            s = s[:-1] + "+00:00"
        return dt.datetime.fromisoformat(s)
    if t == FieldType.TIME:
        if isinstance(raw, dt.time):
            return raw
        return dt.time.fromisoformat(str(raw))
    if t == FieldType.UUID:
        return raw if isinstance(raw, uuid.UUID) else uuid.UUID(str(raw))
    if t == FieldType.JSON:
        if isinstance(raw, str):
            try:
                return json.loads(raw)
            except json.JSONDecodeError as exc:
                raise ValueError(f"Invalid JSON: {exc.msg}") from exc
        return raw
    if t == FieldType.ENUM:
        for c in f.choices or []:
            if c.value == raw or str(c.value) == str(raw):
                return c.value
        raise ValueError("Not a valid choice.")
    if t == FieldType.MANY_TO_ONE:
        if isinstance(raw, dict):
            raw = raw.get("id")
        return raw
    if t == FieldType.MANY_TO_MANY:
        if isinstance(raw, dict | str):
            raise ValueError("Expected a list of ids.")
        return [i.get("id") if isinstance(i, dict) else i for i in raw]
    return raw


def coerce_pk(schema: ModelSchema, raw: str) -> Any:
    pk = schema.pk
    try:
        if pk.type == FieldType.INTEGER:
            return int(raw)
        if pk.type == FieldType.UUID:
            return uuid.UUID(raw)
    except ValueError as exc:
        raise BadRequest(f"invalid primary key {raw!r}") from exc
    return raw


def coerce_filter_value(f: FieldSchema, cond: Condition) -> Any:
    """Convert a filter value from JSON to the field's Python type (dates, decimals, enums...)."""
    value = cond.value
    if cond.op == Op.IS_NULL:
        return bool(value)
    if f.is_relation:
        return value
    if cond.op in (Op.CONTAINS, Op.ICONTAINS, Op.STARTSWITH, Op.ENDSWITH):
        return "" if value is None else str(value)
    scalar = FieldSchema(f.name, f.type, choices=f.choices, nullable=True)
    try:
        if cond.op in (Op.IN, Op.NOT_IN, Op.BETWEEN):
            if not isinstance(value, list):
                raise ValueError("expected a list")
            if cond.op == Op.BETWEEN and len(value) != 2:
                raise ValueError("between expects [low, high]")
            return [None if v is None else coerce_value(scalar, v) for v in value]
        return None if value is None else coerce_value(scalar, value)
    except (ValueError, TypeError, decimal.InvalidOperation) as exc:
        raise BadRequest(f"invalid filter value for {f.name!r}: {exc}") from exc
