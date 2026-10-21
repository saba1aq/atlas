"""MongoDB backend over raw collections. Works with:

* ``pymongo.MongoClient`` (sync, calls run in a worker thread),
* ``pymongo.AsyncMongoClient`` (native async),
* ``motor.motor_asyncio.AsyncIOMotorClient`` (async, deprecated upstream but supported).

Models are Pydantic classes describing the document; ``Ref`` marks references::

    class Post(BaseModel):
        id: int                       # or ObjectId / str; maps to ``_id``
        title: str = Field(max_length=200)
        author: Annotated[int | None, Ref(User)] = None
        tags: Annotated[list[int], Ref(Tag)] = []

Collection name: ``ModelAdmin.collection``, else ``Model.__collection__``, else the lower-cased
class name.
"""

from __future__ import annotations

import builtins
import inspect
from collections.abc import Callable, Sequence
from typing import Any

import anyio
from pydantic import BaseModel

from atlas.core.exceptions import ValidationError
from atlas.core.model_admin import ModelAdmin
from atlas.core.query import ListQuery, Page
from atlas.core.schema import FieldType, ModelSchema

from .common import (
    Ref,
    build_query,
    build_sort,
    from_bson,
    introspect_pydantic,
    parse_pk,
    pk_to_json,
    to_bson,
)

REFS_KEY = "_atlas_refs"


class Driver:
    """Uniform async facade over sync pymongo, async pymongo and Motor collections."""

    def __init__(self, database: Any) -> None:
        self.database = database
        mod = type(database).__module__
        self.is_sync = mod.startswith("pymongo.database") or mod == "pymongo.synchronous.database"

    def collection(self, name: str) -> Any:
        return self.database[name]

    async def _run(self, fn: Callable[[], Any]) -> Any:
        if self.is_sync:
            return await anyio.to_thread.run_sync(fn)
        result = fn()
        return await result if inspect.isawaitable(result) else result

    async def find(
        self, coll: Any, q: dict[str, Any], *, sort: Any = None, skip: int = 0, limit: int = 0
    ) -> builtins.list[dict[str, Any]]:
        def build() -> Any:
            cursor = coll.find(q)
            if sort:
                cursor = cursor.sort(sort)
            if skip:
                cursor = cursor.skip(skip)
            if limit:
                cursor = cursor.limit(limit)
            return cursor

        if self.is_sync:
            return await anyio.to_thread.run_sync(lambda: [*build()])
        return [*await build().to_list(length=None)]

    async def count(self, coll: Any, q: dict[str, Any]) -> int:
        return int(await self._run(lambda: coll.count_documents(q)))

    async def insert_one(self, coll: Any, doc: dict[str, Any]) -> Any:
        res = await self._run(lambda: coll.insert_one(doc))
        return res.inserted_id

    async def update_one(self, coll: Any, flt: dict[str, Any], update: dict[str, Any]) -> None:
        await self._run(lambda: coll.update_one(flt, update))

    async def delete_many(self, coll: Any, flt: dict[str, Any]) -> int:
        res = await self._run(lambda: coll.delete_many(flt))
        return int(res.deleted_count)


class MongoBackend:
    name = "mongo"

    def __init__(self, database: Any) -> None:
        self.driver = Driver(database)

    def supports(self, model: type) -> bool:
        return isinstance(model, type) and issubclass(model, BaseModel)

    def introspect(self, model: type, admin: ModelAdmin) -> ModelSchema:
        return introspect_pydantic(model)

    def repository(self, model: type, schema: ModelSchema, admin: ModelAdmin) -> MongoRepository:
        return MongoRepository(self, model, schema, admin)


class MongoRepository:
    id_path = ""  # relation ids are stored directly; Beanie overrides with ".$id"

    def __init__(
        self, backend: MongoBackend, model: type, schema: ModelSchema, admin: ModelAdmin
    ) -> None:
        self.backend = backend
        self.model = model
        self.schema = schema
        self.admin = admin
        self._coll: Any = None
        self._pk_is_int = schema.pk.type == FieldType.INTEGER

    # ---- plumbing ---------------------------------------------------------------------------

    @property
    def driver(self) -> Driver:
        return self.backend.driver

    @property
    def collection_name(self) -> str:
        return str(
            getattr(self.admin, "collection", None)
            or getattr(self.model, "__collection__", None)
            or self.model.__name__.lower()
        )

    @property
    def coll(self) -> Any:
        if self._coll is None:
            self._coll = self.driver.collection(self.collection_name)
        return self._coll

    def _pk(self, raw: Any) -> Any:
        return parse_pk(raw)

    def _rel_value(self, f: Any, value: Any) -> Any:
        """How a reference is stored: plain id here, DBRef in Beanie."""
        return to_bson(f, value)

    def _rel_ids(self, f: Any, stored: Any) -> builtins.list[Any]:
        """Extract target ids from a stored reference value."""
        if stored is None:
            return []
        return [*stored] if isinstance(stored, list) else [stored]

    # ---- relation labels --------------------------------------------------------------------

    async def _attach_refs(self, docs: Sequence[dict[str, Any]]) -> None:
        for f in self.schema.fields:
            if not f.is_relation or f.relation is None or f.type == FieldType.ONE_TO_MANY:
                continue
            ids: set[Any] = set()
            for d in docs:
                ids.update(self._rel_ids(f, d.get(f.name)))
            labels: dict[Any, str] = {}
            res = self.admin.site.resource_for_model(f.relation.model)
            if res is not None and ids:
                repo = res.repository
                for obj in await repo.get_many([*ids]):
                    labels[pk_to_json(repo.pk_of(obj))] = repo.label_of(obj)
            for d in docs:
                d.setdefault(REFS_KEY, {})[f.name] = [
                    {"id": pk_to_json(i), "label": labels.get(pk_to_json(i), str(i))}
                    for i in self._rel_ids(f, d.get(f.name))
                ]

    async def _validate_refs(self, data: dict[str, Any]) -> None:
        for name, value in data.items():
            f = self.schema.field(name)
            if not f.is_relation or f.relation is None or value is None:
                continue
            res = self.admin.site.resource_for_model(f.relation.model)
            if res is None:
                continue
            ids = value if isinstance(value, list) else [value]
            if not ids:
                continue
            found = await res.repository.get_many([parse_pk(i) for i in ids])
            if len(found) != len({str(i) for i in ids}):
                raise ValidationError({name: "related object does not exist"})

    # ---- Repository API ---------------------------------------------------------------------

    async def _fetch(self, q: dict[str, Any], **kw: Any) -> builtins.list[dict[str, Any]]:
        docs = await self.driver.find(self.coll, q, **kw)
        await self._attach_refs(docs)
        return docs

    async def list(self, query: ListQuery) -> Page[Any]:
        q = build_query(self.schema, query, id_path=self.id_path)
        total = await self.driver.count(self.coll, q)
        docs = await self._fetch(
            q, sort=build_sort(self.schema, query), skip=query.offset, limit=query.limit
        )
        return Page(items=docs, total=total)

    async def count(self, query: ListQuery) -> int:
        return await self.driver.count(
            self.coll, build_query(self.schema, query, id_path=self.id_path)
        )

    async def get(self, pk: Any) -> Any | None:
        docs = await self._fetch({"_id": self._pk(pk)}, limit=1)
        return docs[0] if docs else None

    async def get_many(self, pks: Sequence[Any]) -> Sequence[Any]:
        return await self._fetch({"_id": {"$in": [self._pk(p) for p in pks]}})

    def _encode(self, data: dict[str, Any]) -> dict[str, Any]:
        out: dict[str, Any] = {}
        for name, value in data.items():
            f = self.schema.field(name)
            out[name] = self._rel_value(f, value) if f.is_relation else to_bson(f, value)
        return out

    def _defaults(self, data: dict[str, Any]) -> dict[str, Any]:
        """Fill Pydantic defaults for fields missing from a create payload."""
        if not (isinstance(self.model, type) and issubclass(self.model, BaseModel)):
            return data
        out = dict(data)
        for name, info in self.model.model_fields.items():
            if name in out or name == self.schema.pk_field or info.is_required():
                continue
            if name not in self.schema.fields_by_name:
                continue
            default = info.get_default(call_default_factory=True)
            if default is not None:
                out[name] = default
        return out

    async def create(self, data: dict[str, Any]) -> Any:
        await self._validate_refs(data)
        doc = self._encode(self._defaults(data))
        if self._pk_is_int and "_id" not in doc:
            doc["_id"] = await self._next_int_id()
        inserted = await self.driver.insert_one(self.coll, doc)
        return await self.get(inserted)

    async def _next_int_id(self) -> int:
        last = await self.driver.find(self.coll, {}, sort=[("_id", -1)], limit=1)
        return (int(last[0]["_id"]) + 1) if last and isinstance(last[0]["_id"], int) else 1

    async def update(self, obj: Any, data: dict[str, Any]) -> Any:
        await self._validate_refs(data)
        pk = obj["_id"]
        if data:
            await self.driver.update_one(self.coll, {"_id": pk}, {"$set": self._encode(data)})
        return await self.get(pk)

    async def delete(self, objs: Sequence[Any]) -> int:
        pks = [o["_id"] for o in objs]
        if not pks:
            return 0
        return await self.driver.delete_many(self.coll, {"_id": {"$in": pks}})

    # ---- serialization ----------------------------------------------------------------------

    def pk_of(self, obj: Any) -> Any:
        return obj["_id"]

    def label_of(self, obj: Any) -> str:
        for name in ("name", "title", "label", "username", "email"):
            if obj.get(name):
                return str(obj[name])
        for f in self.schema.fields:
            if f.type == FieldType.STRING and not f.primary_key and obj.get(f.name):
                return str(obj[f.name])
        return f"{self.schema.label} #{pk_to_json(obj['_id'])}"

    def to_dict(self, obj: Any) -> dict[str, Any]:
        refs = obj.get(REFS_KEY, {})
        out: dict[str, Any] = {}
        for f in self.schema.fields:
            if f.type == FieldType.ONE_TO_MANY:
                continue
            if f.primary_key:
                out[f.name] = pk_to_json(obj.get("_id"))
            elif f.type == FieldType.MANY_TO_ONE:
                items = refs.get(f.name, [])
                out[f.name] = items[0] if items else None
            elif f.type == FieldType.MANY_TO_MANY:
                out[f.name] = refs.get(f.name, [])
            else:
                out[f.name] = from_bson(f, obj.get(f.name))
        return out


__all__ = ["Driver", "MongoBackend", "MongoRepository", "Ref"]
