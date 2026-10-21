"""Filter tree shared by UI, core and backends.

Wire format (JSON in ``?filters=``)::

    {"and": [{"field": "age", "op": "gte", "value": 18},
             {"or": [{"field": "name", "op": "icontains", "value": "a"}, ...]}]}

A bare list is treated as an AND group.
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from enum import StrEnum
from typing import Any, Literal

from .exceptions import BadRequest


class Op(StrEnum):
    EQ = "eq"
    NE = "ne"
    LT = "lt"
    LTE = "lte"
    GT = "gt"
    GTE = "gte"
    IN = "in"
    NOT_IN = "not_in"
    CONTAINS = "contains"
    ICONTAINS = "icontains"
    STARTSWITH = "startswith"
    ENDSWITH = "endswith"
    IS_NULL = "is_null"
    BETWEEN = "between"


@dataclass(slots=True)
class Condition:
    field: str
    op: Op
    value: Any = None


@dataclass(slots=True)
class FilterGroup:
    logic: Literal["and", "or"] = "and"
    items: list[Condition | FilterGroup] = field(default_factory=list)

    def is_empty(self) -> bool:
        return not self.items

    def conditions(self) -> list[Condition]:
        out: list[Condition] = []
        for item in self.items:
            if isinstance(item, Condition):
                out.append(item)
            else:
                out.extend(item.conditions())
        return out

    @staticmethod
    def parse(raw: str | dict[str, Any] | list[Any] | None) -> FilterGroup:
        if raw is None or raw == "":
            return FilterGroup()
        if isinstance(raw, str):
            try:
                raw = json.loads(raw)
            except json.JSONDecodeError as exc:
                raise BadRequest(f"filters is not valid JSON: {exc.msg}") from exc
        return _parse_node(raw)


def _parse_node(node: Any) -> FilterGroup:
    if isinstance(node, list):
        return FilterGroup("and", [_parse_item(i) for i in node])
    if isinstance(node, dict):
        for logic in ("and", "or"):
            if logic in node:
                items = node[logic]
                if not isinstance(items, list):
                    raise BadRequest(f"filters: '{logic}' must be a list")
                return FilterGroup(logic, [_parse_item(i) for i in items])
        return FilterGroup("and", [_parse_item(node)])
    raise BadRequest("filters: expected object or list")


def _parse_item(item: Any) -> Condition | FilterGroup:
    if isinstance(item, dict) and ("and" in item or "or" in item):
        return _parse_node(item)
    if not isinstance(item, dict) or "field" not in item:
        raise BadRequest("filters: condition must be an object with 'field'")
    op_raw = item.get("op", "eq")
    try:
        op = Op(op_raw)
    except ValueError as exc:
        raise BadRequest(f"filters: unknown op {op_raw!r}") from exc
    if not isinstance(item["field"], str):
        raise BadRequest("filters: 'field' must be a string")
    return Condition(field=item["field"], op=op, value=item.get("value"))
