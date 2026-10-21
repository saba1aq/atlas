"""Per-model configuration, Django-admin style."""

from __future__ import annotations

import inspect
from collections.abc import Awaitable, Callable, Sequence
from dataclasses import dataclass
from typing import TYPE_CHECKING, Any, ClassVar

from .query import ListQuery
from .schema import SEARCHABLE_TYPES, FieldType, ModelSchema

if TYPE_CHECKING:
    from .http import AdminRequest
    from .repository import Backend
    from .site import AdminSite


ActionHandler = Callable[..., Awaitable[Any]]


@dataclass(slots=True)
class Action:
    name: str
    label: str
    handler: ActionHandler
    confirm: str | None = None
    icon: str | None = None
    bulk: bool = True

    def to_dict(self) -> dict[str, Any]:
        return {
            "name": self.name,
            "label": self.label,
            "confirm": self.confirm,
            "icon": self.icon,
            "bulk": self.bulk,
        }


def action(
    label: str | None = None,
    *,
    confirm: str | None = None,
    icon: str | None = None,
    bulk: bool = True,
) -> Callable[[ActionHandler], ActionHandler]:
    """Mark a ``ModelAdmin`` coroutine method as an action.

    Handler signature: ``async def name(self, request, objs) -> str | dict | None``.
    The returned value becomes ``{"message": ...}`` (str) or is passed through (dict).
    """

    def decorator(fn: ActionHandler) -> ActionHandler:
        if not inspect.iscoroutinefunction(fn):
            raise TypeError(f"action {fn.__name__!r} must be `async def`")
        fn.__atlas_action__ = {  # type: ignore[attr-defined]
            "label": label or fn.__name__.replace("_", " ").capitalize(),
            "confirm": confirm,
            "icon": icon,
            "bulk": bulk,
        }
        return fn

    return decorator


class ModelAdmin:
    """Subclass and override class attributes / hooks. One instance per registered model."""

    model: type
    backend: ClassVar[Backend | None] = None

    key: ClassVar[str | None] = None
    label: ClassVar[str | None] = None
    label_plural: ClassVar[str | None] = None
    icon: ClassVar[str | None] = None

    list_display: ClassVar[Sequence[str] | None] = None
    list_filter: ClassVar[Sequence[str] | None] = None
    search_fields: ClassVar[Sequence[str] | None] = None
    ordering: ClassVar[Sequence[str]] = ()
    fields: ClassVar[Sequence[str] | None] = None
    exclude: ClassVar[Sequence[str]] = ()
    readonly_fields: ClassVar[Sequence[str]] = ()
    page_size: ClassVar[int] = 25
    max_page_size: ClassVar[int] = 200
    export_limit: ClassVar[int] = 10_000

    can_create: ClassVar[bool] = True
    can_edit: ClassVar[bool] = True
    can_delete: ClassVar[bool] = True

    def __init__(self, model: type, site: AdminSite) -> None:
        self.model = model
        self.site = site
        self._actions: dict[str, Action] | None = None

    # ---- schema -----------------------------------------------------------------------------

    def configure_schema(self, schema: ModelSchema) -> ModelSchema:
        """Apply list_display/fields/exclude/readonly/search settings to an introspected schema."""
        names = {f.name for f in schema.fields}
        for attr in (
            "list_display",
            "list_filter",
            "search_fields",
            "fields",
            "exclude",
            "readonly_fields",
        ):
            value = getattr(self, attr)
            if value is None:
                continue
            unknown = [n for n in value if n not in names]
            if unknown:
                raise ValueError(
                    f"{type(self).__name__}.{attr}: unknown fields {unknown} for {schema.key}"
                )
        for name in self.ordering:
            if name.lstrip("-+") not in names:
                raise ValueError(f"{type(self).__name__}.ordering: unknown field {name!r}")

        list_display = set(self.list_display) if self.list_display is not None else None
        form_fields = set(self.fields) if self.fields is not None else None
        exclude = set(self.exclude)
        readonly = set(self.readonly_fields)
        search = set(self.search_fields) if self.search_fields is not None else None
        filterable = set(self.list_filter) if self.list_filter is not None else None

        for f in schema.fields:
            if list_display is not None:
                f.in_list = f.name in list_display
            if f.type == FieldType.ONE_TO_MANY:
                f.in_list = False
                f.in_form = False
            if f.name in exclude:
                f.in_form = False
                f.in_detail = False
                f.in_list = False
            elif form_fields is not None and not f.primary_key:
                f.in_form = f.name in form_fields
            if f.name in readonly:
                f.read_only = True
            if search is not None:
                f.searchable = f.name in search
            else:
                f.searchable = f.type in SEARCHABLE_TYPES
            if filterable is not None:
                f.filterable = f.name in filterable
            if f.is_relation:
                f.sortable = False
        if self.list_display is not None:  # list columns follow list_display order
            order = {name: i for i, name in enumerate(self.list_display)}
            schema.fields.sort(key=lambda f: order.get(f.name, len(order)))
        return schema

    # ---- actions ----------------------------------------------------------------------------

    def get_actions(self) -> dict[str, Action]:
        if self._actions is None:
            found: dict[str, Action] = {}
            for name, member in inspect.getmembers(type(self)):
                meta = getattr(member, "__atlas_action__", None)
                if meta:
                    found[name] = Action(name=name, handler=getattr(self, name), **meta)
            self._actions = found
        return self._actions

    # ---- query ------------------------------------------------------------------------------

    def get_query(self, request: AdminRequest, query: ListQuery) -> ListQuery:
        """Hook to restrict or alter the list query (e.g. tenant scoping)."""
        return query

    def display(self, obj: Any) -> str:
        return str(obj)

    # ---- permissions ------------------------------------------------------------------------

    async def has_view_permission(self, request: AdminRequest, obj: Any = None) -> bool:
        return True

    async def has_add_permission(self, request: AdminRequest) -> bool:
        return self.can_create

    async def has_change_permission(self, request: AdminRequest, obj: Any = None) -> bool:
        return self.can_edit

    async def has_delete_permission(self, request: AdminRequest, obj: Any = None) -> bool:
        return self.can_delete

    # ---- lifecycle hooks --------------------------------------------------------------------

    async def validate(self, request: AdminRequest, data: dict[str, Any], obj: Any = None) -> None:
        """Raise ``ValidationError({field: message})`` for business-rule validation."""

    async def before_create(self, request: AdminRequest, data: dict[str, Any]) -> None: ...
    async def after_create(self, request: AdminRequest, obj: Any) -> None: ...
    async def before_update(
        self, request: AdminRequest, obj: Any, data: dict[str, Any]
    ) -> None: ...
    async def after_update(self, request: AdminRequest, obj: Any) -> None: ...
    async def before_delete(self, request: AdminRequest, objs: Sequence[Any]) -> None: ...
    async def after_delete(self, request: AdminRequest, count: int) -> None: ...
