"""Contracts every ORM backend implements. Core never imports an ORM."""

from __future__ import annotations

from collections.abc import Sequence
from typing import TYPE_CHECKING, Any, Protocol, runtime_checkable

from .query import ListQuery, Page
from .schema import ModelSchema

if TYPE_CHECKING:
    from .model_admin import ModelAdmin


@runtime_checkable
class Repository(Protocol):
    """Data access for one model. ``data`` dicts are already coerced by core:

    * scalar fields hold Python values (int, str, date, Decimal, ...);
    * many_to_one fields hold the target pk or ``None``;
    * many_to_many fields hold a list of target pks.
    """

    schema: ModelSchema

    async def list(self, query: ListQuery) -> Page[Any]: ...
    async def count(self, query: ListQuery) -> int: ...
    async def get(self, pk: Any) -> Any | None: ...
    async def get_many(self, pks: Sequence[Any]) -> Sequence[Any]: ...
    async def create(self, data: dict[str, Any]) -> Any: ...
    async def update(self, obj: Any, data: dict[str, Any]) -> Any: ...
    async def delete(self, objs: Sequence[Any]) -> int: ...

    def pk_of(self, obj: Any) -> Any: ...
    def label_of(self, obj: Any) -> str: ...
    def to_dict(self, obj: Any) -> dict[str, Any]:
        """Serialize a row fetched by this repository (relations must already be loaded)."""
        ...


@runtime_checkable
class Backend(Protocol):
    """Factory for schemas and repositories of one ORM."""

    name: str

    def supports(self, model: type) -> bool: ...
    def introspect(self, model: type, admin: ModelAdmin) -> ModelSchema: ...
    def repository(self, model: type, schema: ModelSchema, admin: ModelAdmin) -> Repository: ...
