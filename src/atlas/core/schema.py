"""Backend-agnostic description of a model: what the UI needs to render list, filters and forms."""

from __future__ import annotations

from dataclasses import asdict, dataclass, field
from enum import StrEnum
from typing import Any


class FieldType(StrEnum):
    STRING = "string"
    TEXT = "text"
    INTEGER = "integer"
    FLOAT = "float"
    DECIMAL = "decimal"
    BOOLEAN = "boolean"
    DATE = "date"
    DATETIME = "datetime"
    TIME = "time"
    UUID = "uuid"
    JSON = "json"
    ENUM = "enum"
    MANY_TO_ONE = "many_to_one"
    MANY_TO_MANY = "many_to_many"
    ONE_TO_MANY = "one_to_many"


RELATION_TYPES = frozenset({FieldType.MANY_TO_ONE, FieldType.MANY_TO_MANY, FieldType.ONE_TO_MANY})
SEARCHABLE_TYPES = frozenset({FieldType.STRING, FieldType.TEXT, FieldType.ENUM, FieldType.UUID})


@dataclass(slots=True)
class Choice:
    value: Any
    label: str


@dataclass(slots=True)
class Relation:
    """Target of a relation field. ``resource`` is the admin key if the target is registered."""

    model: Any
    resource: str | None = None
    kind: FieldType = FieldType.MANY_TO_ONE


@dataclass(slots=True)
class FieldSchema:
    name: str
    type: FieldType
    label: str = ""
    primary_key: bool = False
    required: bool = False
    nullable: bool = True
    read_only: bool = False
    has_default: bool = False
    max_length: int | None = None
    choices: list[Choice] | None = None
    relation: Relation | None = None
    help_text: str = ""
    sortable: bool = True
    searchable: bool = False
    filterable: bool = True
    # Visibility, filled by ModelAdmin
    in_list: bool = True
    in_form: bool = True
    in_detail: bool = True

    def __post_init__(self) -> None:
        if not self.label:
            self.label = self.name.replace("_", " ").strip().capitalize()
        if self.type in RELATION_TYPES and self.relation is None:
            raise ValueError(f"relation field {self.name!r} requires `relation`")

    @property
    def is_relation(self) -> bool:
        return self.type in RELATION_TYPES

    def to_dict(self) -> dict[str, Any]:
        data = asdict(self)
        data["type"] = self.type.value
        if self.relation is not None:
            data["relation"] = {
                "resource": self.relation.resource,
                "kind": self.relation.kind.value,
            }
        return data


@dataclass(slots=True)
class ModelSchema:
    key: str
    label: str
    label_plural: str
    pk_field: str
    fields: list[FieldSchema] = field(default_factory=list)

    def __post_init__(self) -> None:
        names = [f.name for f in self.fields]
        if len(names) != len(set(names)):
            raise ValueError(f"duplicate field names in schema {self.key!r}: {names}")
        if self.pk_field not in names:
            raise ValueError(f"pk_field {self.pk_field!r} is not among fields of {self.key!r}")

    @property
    def fields_by_name(self) -> dict[str, FieldSchema]:
        return {f.name: f for f in self.fields}

    def field(self, name: str) -> FieldSchema:
        for f in self.fields:
            if f.name == name:
                return f
        raise KeyError(name)

    @property
    def pk(self) -> FieldSchema:
        return self.field(self.pk_field)

    def to_dict(self) -> dict[str, Any]:
        return {
            "key": self.key,
            "label": self.label,
            "label_plural": self.label_plural,
            "pk_field": self.pk_field,
            "fields": [f.to_dict() for f in self.fields],
        }
