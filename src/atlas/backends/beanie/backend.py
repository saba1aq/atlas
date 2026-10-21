"""Beanie ODM backend. ``Link[T]`` -> many_to_one, ``list[Link[T]]`` -> many_to_many,
``BackLink[T]`` -> one_to_many (read-only). Requires ``init_beanie()`` before the first request.

Documents are read and written through the raw pymongo collection that Beanie manages; links are
stored as DBRefs exactly as Beanie stores them, so both sides stay compatible.
"""

from __future__ import annotations

import builtins
from typing import Any, cast, get_args, get_origin

from beanie import Document
from beanie.odm.fields import BackLink, Link
from bson import DBRef

from atlas.core.model_admin import ModelAdmin
from atlas.core.schema import FieldSchema, FieldType, ModelSchema, Relation

from ..mongo.backend import Driver, MongoBackend, MongoRepository
from ..mongo.common import Ref, _unwrap, field_from_annotation, parse_pk

_HIDDEN = {"revision_id"}


class BeanieBackend(MongoBackend):
    name = "beanie"

    def __init__(self) -> None:  # database comes from init_beanie()
        self._driver: Driver | None = None

    @property
    def driver(self) -> Driver:
        if self._driver is None:
            raise RuntimeError(
                "Beanie is not initialised; call init_beanie() before using the admin"
            )
        return self._driver

    @driver.setter
    def driver(self, value: Driver) -> None:
        self._driver = value

    def supports(self, model: type) -> bool:
        return isinstance(model, type) and issubclass(model, Document)

    def introspect(self, model: type, admin: ModelAdmin) -> ModelSchema:
        fields: list[FieldSchema] = []
        doc = cast(type[Document], model)
        for name, info in doc.model_fields.items():
            if name in _HIDDEN:
                continue
            if name == "id":
                f = field_from_annotation("id", info.annotation, info)
                f.primary_key, f.read_only, f.has_default, f.required, f.nullable = (
                    True,
                    True,
                    True,
                    False,
                    False,
                )
                fields.insert(0, f)
                continue
            core, nullable, _ = _unwrap(info.annotation)
            origin = get_origin(core)
            inner = get_args(core)[0] if origin in (list, set, tuple) and get_args(core) else None
            if origin is Link:
                target = get_args(core)[0]
                ann: Any = (str | None) if nullable else str
                fields.append(field_from_annotation(name, ann, info, extra_metadata=[Ref(target)]))
            elif inner is not None and get_origin(inner) is Link:
                target = get_args(inner)[0]
                fields.append(
                    field_from_annotation(name, list[str], info, extra_metadata=[Ref(target)])
                )
            elif origin is BackLink or (inner is not None and get_origin(inner) is BackLink):
                link = core if origin is BackLink else inner
                target = get_args(link)[0] if get_args(link) else Any
                fields.append(
                    FieldSchema(
                        name,
                        FieldType.ONE_TO_MANY,
                        read_only=True,
                        relation=Relation(model=target, kind=FieldType.ONE_TO_MANY),
                        sortable=False,
                        filterable=False,
                    )
                )
            else:
                fields.append(field_from_annotation(name, info.annotation, info))
        label = model.__name__
        return ModelSchema(
            key=label.lower(), label=label, label_plural=f"{label}s", pk_field="id", fields=fields
        )

    def repository(self, model: type, schema: ModelSchema, admin: ModelAdmin) -> BeanieRepository:
        return BeanieRepository(self, model, schema, admin)


class BeanieRepository(MongoRepository):
    id_path = ".$id"

    @property
    def driver(self) -> Driver:
        _ = self.coll  # resolving the collection also wires the driver from init_beanie()
        return self.backend.driver

    @property
    def coll(self) -> Any:
        if self._coll is None:
            doc = cast(type[Document], self.model)
            self._coll = doc.get_pymongo_collection()  # raises if init_beanie() was not run
            self.backend.driver = Driver(self._coll.database)
        return self._coll

    @property
    def collection_name(self) -> str:
        return str(cast(type[Document], self.model).get_collection_name())

    def _target_collection(self, f: FieldSchema) -> str:
        assert f.relation is not None
        return str(f.relation.model.get_collection_name())

    def _rel_value(self, f: FieldSchema, value: Any) -> Any:
        if value is None:
            return None
        coll = self._target_collection(f)
        if f.type == FieldType.MANY_TO_MANY:
            return [DBRef(coll, parse_pk(v)) for v in value]
        return DBRef(coll, parse_pk(value))

    def _rel_ids(self, f: FieldSchema, stored: Any) -> builtins.list[Any]:
        if stored is None:
            return []
        items = stored if isinstance(stored, list) else [stored]
        out = []
        for i in items:
            if isinstance(i, DBRef):
                out.append(i.id)
            elif isinstance(i, dict) and "$id" in i:
                out.append(i["$id"])
            else:
                out.append(i)
        return out


__all__ = ["BeanieBackend", "BeanieRepository"]
