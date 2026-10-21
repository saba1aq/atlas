"""AdminSite: model registry + framework-neutral HTTP dispatcher.

Transports call ``await site.dispatch(AdminRequest)`` and translate the ``AdminResponse``.
"""

from __future__ import annotations

import csv
import io
import re
from collections.abc import Awaitable, Callable, Sequence
from dataclasses import dataclass
from typing import Any

from .auth import AuthProvider
from .coerce import coerce_filter_value, coerce_input, coerce_pk
from .exceptions import AdminError, BadRequest, NotFound, PermissionDenied, Unauthorized
from .filters import FilterGroup
from .http import AdminRequest, AdminResponse
from .model_admin import ModelAdmin
from .query import ListQuery
from .repository import Backend, Repository
from .schema import FieldType, ModelSchema

Handler = Callable[..., Awaitable[AdminResponse]]


@dataclass(slots=True)
class Route:
    method: str
    pattern: re.Pattern[str]
    handler: Handler
    public: bool = False


class Resource:
    """A registered model: admin config + lazily built schema and repository."""

    def __init__(
        self, key: str, model: type, admin: ModelAdmin, backend: Backend, site: AdminSite
    ) -> None:
        self.key = key
        self.model = model
        self.admin = admin
        self.backend = backend
        self.site = site
        self._schema: ModelSchema | None = None
        self._repo: Repository | None = None

    @property
    def schema(self) -> ModelSchema:
        if self._schema is None:
            schema = self.backend.introspect(self.model, self.admin)
            schema.key = self.key
            schema.label = self.admin.label or schema.label
            schema.label_plural = self.admin.label_plural or schema.label_plural
            for f in schema.fields:
                if f.relation is not None and f.relation.resource is None:
                    target = self.site.resource_for_model(f.relation.model)
                    f.relation.resource = target.key if target else None
            self._schema = self.admin.configure_schema(schema)
        return self._schema

    @property
    def repository(self) -> Repository:
        if self._repo is None:
            self._repo = self.backend.repository(self.model, self.schema, self.admin)
        return self._repo

    def to_dict(self) -> dict[str, Any]:
        return {
            "key": self.key,
            "label": self.schema.label,
            "label_plural": self.schema.label_plural,
            "icon": self.admin.icon,
        }


class AdminSite:
    def __init__(
        self,
        title: str = "Atlas Admin",
        *,
        backend: Backend | None = None,
        backends: Sequence[Backend] = (),
        auth: AuthProvider | None = None,
    ) -> None:
        self.title = title
        self.auth = auth
        self._backends: list[Backend] = list(backends)
        if backend is not None:
            self._backends.insert(0, backend)
        self._resources: dict[str, Resource] = {}
        self._by_model: dict[type, Resource] = {}
        self._routes: list[Route] = []
        self._register_routes()

    # ---- registry ---------------------------------------------------------------------------

    def add_backend(self, backend: Backend) -> None:
        self._backends.append(backend)

    def register(
        self,
        model: type,
        admin_cls: type[ModelAdmin] | None = None,
        *,
        backend: Backend | None = None,
        key: str | None = None,
    ) -> Any:
        """Register a model: ``site.register(Model, Admin)`` or ``@site.register(Model)``."""
        if admin_cls is None:

            def decorator(cls: type[ModelAdmin]) -> type[ModelAdmin]:
                self.register(model, cls, backend=backend, key=key)
                return cls

            return decorator

        if not isinstance(admin_cls, type) or not issubclass(admin_cls, ModelAdmin):
            raise TypeError("admin_cls must be a ModelAdmin subclass")
        chosen = backend or admin_cls.backend or self._pick_backend(model)
        admin = admin_cls(model, self)
        resource_key = key or admin_cls.key or _slug(model.__name__)
        if resource_key in self._resources:
            raise ValueError(f"resource key {resource_key!r} is already registered")
        if model in self._by_model:
            raise ValueError(f"model {model.__name__} is already registered")
        res = Resource(resource_key, model, admin, chosen, self)
        self._resources[resource_key] = res
        self._by_model[model] = res
        return admin

    def _pick_backend(self, model: type) -> Backend:
        for b in self._backends:
            if b.supports(model):
                return b
        if len(self._backends) == 1:
            return self._backends[0]
        raise ValueError(
            f"no backend supports {model.__name__}; pass backend=... to register() or AdminSite()"
        )

    @property
    def resources(self) -> dict[str, Resource]:
        return self._resources

    def resource(self, key: str) -> Resource:
        try:
            return self._resources[key]
        except KeyError:
            raise NotFound(f"unknown resource {key!r}") from None

    def resource_for_model(self, model: type) -> Resource | None:
        return self._by_model.get(model)

    # ---- routing ----------------------------------------------------------------------------

    def _register_routes(self) -> None:
        add = self._add_route
        add("GET", r"/site", self.h_site)
        add("POST", r"/auth/login", self.h_login, public=True)
        add("POST", r"/auth/logout", self.h_logout)
        add("GET", r"/auth/me", self.h_me)
        add("GET", r"/(?P<key>[\w-]+)/schema", self.h_schema)
        add("GET", r"/(?P<key>[\w-]+)/options", self.h_options)
        add("GET", r"/(?P<key>[\w-]+)/export", self.h_export)
        add("POST", r"/(?P<key>[\w-]+)/actions/(?P<name>\w+)", self.h_action)
        add("GET", r"/(?P<key>[\w-]+)", self.h_list)
        add("POST", r"/(?P<key>[\w-]+)", self.h_create)
        add("DELETE", r"/(?P<key>[\w-]+)", self.h_bulk_delete)
        add("GET", r"/(?P<key>[\w-]+)/(?P<pk>[^/]+)", self.h_get)
        add("PATCH", r"/(?P<key>[\w-]+)/(?P<pk>[^/]+)", self.h_update)
        add("PUT", r"/(?P<key>[\w-]+)/(?P<pk>[^/]+)", self.h_update)
        add("DELETE", r"/(?P<key>[\w-]+)/(?P<pk>[^/]+)", self.h_delete)

    def _add_route(
        self, method: str, pattern: str, handler: Handler, *, public: bool = False
    ) -> None:
        self._routes.append(Route(method, re.compile(f"^{pattern}/?$"), handler, public))

    async def dispatch(self, request: AdminRequest) -> AdminResponse:
        try:
            return await self._dispatch(request)
        except AdminError as exc:
            return AdminResponse.json(exc.to_dict(), status=exc.status)

    async def _dispatch(self, request: AdminRequest) -> AdminResponse:
        path = request.path or "/"
        method = request.method.upper()
        matched_path = False
        for route in self._routes:
            m = route.pattern.match(path)
            if not m:
                continue
            matched_path = True
            if route.method != method:
                continue
            if self.auth is not None:
                request.user = await self.auth.authenticate(request)
                if request.user is None and not route.public:
                    raise Unauthorized("Authentication required")
            return await route.handler(request, **m.groupdict())
        if matched_path:
            return AdminResponse.json({"error": "method not allowed"}, status=405)
        raise NotFound(f"no route for {method} {path}")

    # ---- handlers: site & auth --------------------------------------------------------------

    async def h_site(self, request: AdminRequest) -> AdminResponse:
        resources = []
        for res in self._resources.values():
            if await res.admin.has_view_permission(request):
                resources.append(res.to_dict())
        user = (
            request.user.to_dict()
            if request.user is not None and hasattr(request.user, "to_dict")
            else request.user
        )
        return AdminResponse.json(
            {
                "title": self.title,
                "resources": resources,
                "user": user,
                "auth_enabled": self.auth is not None,
            }
        )

    async def h_login(self, request: AdminRequest) -> AdminResponse:
        if self.auth is None:
            raise BadRequest("authentication is not configured")
        body = request.json() or {}
        username = str(body.get("username", "")).strip()
        password = str(body.get("password", ""))
        if not username or not password:
            raise BadRequest("username and password are required")
        user = await self.auth.login(request, username, password)
        if user is None:
            raise Unauthorized("Invalid credentials")
        return self.auth.on_login(user, AdminResponse.json({"user": user.to_dict()}))

    async def h_logout(self, request: AdminRequest) -> AdminResponse:
        if self.auth is None:
            raise BadRequest("authentication is not configured")
        return self.auth.on_logout(AdminResponse.no_content())

    async def h_me(self, request: AdminRequest) -> AdminResponse:
        user = request.user.to_dict() if hasattr(request.user, "to_dict") else request.user
        return AdminResponse.json({"user": user})

    # ---- handlers: resources ----------------------------------------------------------------

    async def _resource(self, request: AdminRequest, key: str) -> Resource:
        res = self.resource(key)
        if not await res.admin.has_view_permission(request):
            raise PermissionDenied("You do not have permission to view this resource")
        return res

    async def _get_or_404(self, res: Resource, pk: str) -> Any:
        obj = await res.repository.get(coerce_pk(res.schema, pk))
        if obj is None:
            raise NotFound(f"{res.schema.label} {pk!r} not found")
        return obj

    async def h_schema(self, request: AdminRequest, key: str) -> AdminResponse:
        res = await self._resource(request, key)
        admin = res.admin
        data = res.schema.to_dict()
        data.update(
            {
                "icon": admin.icon,
                "page_size": admin.page_size,
                "ordering": list(admin.ordering),
                "actions": [a.to_dict() for a in admin.get_actions().values()],
                "permissions": {
                    "create": await admin.has_add_permission(request),
                    "edit": await admin.has_change_permission(request),
                    "delete": await admin.has_delete_permission(request),
                },
            }
        )
        return AdminResponse.json(data)

    def _build_query(
        self, request: AdminRequest, res: Resource, *, limit_cap: int | None = None
    ) -> ListQuery:
        schema, admin = res.schema, res.admin
        fields = schema.fields_by_name
        page_size = request.int_param(
            "limit", admin.page_size, minimum=1, maximum=limit_cap or admin.max_page_size
        )
        offset = request.int_param("offset", 0, minimum=0)
        sort = ListQuery.parse_sort(request.param("sort")) or ListQuery.parse_sort(
            ",".join(admin.ordering)
        )
        for name, _ in sort:
            f = fields.get(name)
            if f is None or not f.sortable:
                raise BadRequest(f"cannot sort by {name!r}")
        filters = FilterGroup.parse(request.param("filters"))
        for cond in filters.conditions():
            f = fields.get(cond.field)
            if f is None or not f.filterable:
                raise BadRequest(f"cannot filter by {cond.field!r}")
            cond.value = coerce_filter_value(f, cond)
        search = (request.param("search") or request.param("q") or "").strip() or None
        query = ListQuery(filters=filters, search=search, sort=sort, offset=offset, limit=page_size)
        return admin.get_query(request, query)

    async def h_list(self, request: AdminRequest, key: str) -> AdminResponse:
        res = await self._resource(request, key)
        query = self._build_query(request, res)
        page = await res.repository.list(query)
        return AdminResponse.json(page.to_dict(res.repository.to_dict))

    async def h_options(self, request: AdminRequest, key: str) -> AdminResponse:
        """Autocomplete for relation widgets: ``?q=term`` or ``?ids=1,2,3``."""
        res = await self._resource(request, key)
        repo = res.repository
        ids_raw = request.param("ids")
        if ids_raw:
            pks = [coerce_pk(res.schema, i) for i in ids_raw.split(",") if i]
            objs = await repo.get_many(pks)
        else:
            query = ListQuery(
                search=(request.param("q") or "").strip() or None,
                sort=ListQuery.parse_sort(",".join(res.admin.ordering)),
                limit=request.int_param("limit", 20, minimum=1, maximum=100),
            )
            objs = (await repo.list(res.admin.get_query(request, query))).items
        return AdminResponse.json(
            {
                "items": [
                    {
                        "value": repo.pk_of(o),
                        "label": res.admin.display(o)
                        if type(res.admin).display is not ModelAdmin.display
                        else repo.label_of(o),
                    }
                    for o in objs
                ]
            }
        )

    async def h_get(self, request: AdminRequest, key: str, pk: str) -> AdminResponse:
        res = await self._resource(request, key)
        obj = await self._get_or_404(res, pk)
        if not await res.admin.has_view_permission(request, obj):
            raise PermissionDenied("You do not have permission to view this object")
        return AdminResponse.json(res.repository.to_dict(obj))

    async def h_create(self, request: AdminRequest, key: str) -> AdminResponse:
        res = await self._resource(request, key)
        if not await res.admin.has_add_permission(request):
            raise PermissionDenied("You do not have permission to create objects")
        data = coerce_input(res.schema, request.json(), partial=False)
        await res.admin.validate(request, data)
        await res.admin.before_create(request, data)
        obj = await res.repository.create(data)
        await res.admin.after_create(request, obj)
        return AdminResponse.json(res.repository.to_dict(obj), status=201)

    async def h_update(self, request: AdminRequest, key: str, pk: str) -> AdminResponse:
        res = await self._resource(request, key)
        obj = await self._get_or_404(res, pk)
        if not await res.admin.has_change_permission(request, obj):
            raise PermissionDenied("You do not have permission to edit this object")
        data = coerce_input(res.schema, request.json(), partial=request.method.upper() == "PATCH")
        await res.admin.validate(request, data, obj)
        await res.admin.before_update(request, obj, data)
        obj = await res.repository.update(obj, data)
        await res.admin.after_update(request, obj)
        return AdminResponse.json(res.repository.to_dict(obj))

    async def _delete(
        self, request: AdminRequest, res: Resource, objs: Sequence[Any]
    ) -> AdminResponse:
        for obj in objs:
            if not await res.admin.has_delete_permission(request, obj):
                raise PermissionDenied("You do not have permission to delete this object")
        await res.admin.before_delete(request, objs)
        count = await res.repository.delete(objs)
        await res.admin.after_delete(request, count)
        return AdminResponse.json({"deleted": count})

    async def h_delete(self, request: AdminRequest, key: str, pk: str) -> AdminResponse:
        res = await self._resource(request, key)
        obj = await self._get_or_404(res, pk)
        return await self._delete(request, res, [obj])

    async def _objs_from_body(self, request: AdminRequest, res: Resource) -> list[Any]:
        body = request.json() or {}
        pks = body.get("pks")
        if not isinstance(pks, list) or not pks:
            raise BadRequest("body must contain a non-empty 'pks' list")
        objs = list(await res.repository.get_many([coerce_pk(res.schema, str(p)) for p in pks]))
        if len(objs) != len(set(map(str, pks))):
            raise NotFound("some objects were not found")
        return objs

    async def h_bulk_delete(self, request: AdminRequest, key: str) -> AdminResponse:
        res = await self._resource(request, key)
        objs = await self._objs_from_body(request, res)
        return await self._delete(request, res, objs)

    async def h_action(self, request: AdminRequest, key: str, name: str) -> AdminResponse:
        res = await self._resource(request, key)
        act = res.admin.get_actions().get(name)
        if act is None:
            raise NotFound(f"unknown action {name!r}")
        objs = await self._objs_from_body(request, res)
        if not act.bulk and len(objs) != 1:
            raise BadRequest(f"action {name!r} accepts exactly one object")
        result = await act.handler(request, objs)
        if result is None:
            result = {"message": f"{act.label}: {len(objs)} object(s) processed"}
        elif isinstance(result, str):
            result = {"message": result}
        return AdminResponse.json(result)

    async def h_export(self, request: AdminRequest, key: str) -> AdminResponse:
        res = await self._resource(request, key)
        fmt = (request.param("format") or "csv").lower()
        if fmt not in ("csv", "json"):
            raise BadRequest("format must be csv or json")
        query = self._build_query(request, res, limit_cap=res.admin.export_limit)
        query.limit = request.int_param(
            "limit", res.admin.export_limit, minimum=1, maximum=res.admin.export_limit
        )
        page = await res.repository.list(query)
        rows = [res.repository.to_dict(o) for o in page.items]
        columns = [f.name for f in res.schema.fields if f.in_list]
        if fmt == "json":
            resp = AdminResponse.json([{c: r.get(c) for c in columns} for r in rows])
        else:
            buf = io.StringIO()
            writer = csv.writer(buf)
            writer.writerow(columns)
            for r in rows:
                writer.writerow([_csv_cell(r.get(c)) for c in columns])
            resp = AdminResponse.text(buf.getvalue(), media_type="text/csv; charset=utf-8")
        resp.headers["content-disposition"] = f'attachment; filename="{key}.{fmt}"'
        return resp


def _csv_cell(value: Any) -> Any:
    if isinstance(value, dict) and "label" in value:
        return value["label"]
    if isinstance(value, list):
        return ", ".join(_csv_cell(v) for v in value)
    if value is None:
        return ""
    return value


def _slug(name: str) -> str:
    s = re.sub(r"(?<!^)(?=[A-Z])", "_", name).lower()
    return s.replace("__", "_")


__all__ = ["AdminSite", "Resource", "FieldType"]
