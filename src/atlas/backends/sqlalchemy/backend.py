"""SQLAlchemy 2.x backend. Works with sync ``Session`` and ``AsyncSession``.

All data access is written once as sync functions over ``Session``; for async engines they run
through ``AsyncSession.run_sync``, for sync engines in a worker thread via anyio.
"""

from __future__ import annotations

import builtins
import decimal
import enum
import uuid
from collections.abc import Callable, Sequence
from typing import Any, TypeVar, cast

import anyio
import sqlalchemy as sa
from sqlalchemy import inspect
from sqlalchemy.engine import Engine

try:  # async support needs sqlalchemy[asyncio] (greenlet); sync-only installs work without it
    from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession, async_sessionmaker
except ImportError:  # pragma: no cover

    class AsyncEngine:  # type: ignore[no-redef]
        pass

    class AsyncSession:  # type: ignore[no-redef]
        pass

    class async_sessionmaker:  # type: ignore[no-redef]  # noqa: N801
        pass


from sqlalchemy.orm import Mapper, Session, selectinload, sessionmaker
from sqlalchemy.orm.interfaces import MANYTOMANY, MANYTOONE, ONETOMANY
from sqlalchemy.sql.elements import ColumnElement

from atlas.core.exceptions import ValidationError
from atlas.core.filters import Condition, FilterGroup, Op
from atlas.core.model_admin import ModelAdmin
from atlas.core.query import ListQuery, Page
from atlas.core.schema import Choice, FieldSchema, FieldType, ModelSchema, Relation

T = TypeVar("T")
SessionFactory = Callable[[], Session] | Callable[[], AsyncSession]


def _column_type(column: sa.Column[Any]) -> tuple[FieldType, dict[str, Any]]:
    t = column.type
    extra: dict[str, Any] = {}
    if isinstance(t, sa.Enum):
        if t.enum_class is not None:
            extra["choices"] = [
                Choice(m.value if isinstance(m, enum.Enum) else m, m.name.replace("_", " ").title())
                for m in t.enum_class
            ]
        else:
            extra["choices"] = [Choice(v, v) for v in t.enums]
        return FieldType.ENUM, extra
    if isinstance(t, sa.Boolean):
        return FieldType.BOOLEAN, extra
    if isinstance(t, sa.Integer):
        return FieldType.INTEGER, extra
    if isinstance(t, sa.Numeric):
        return (FieldType.DECIMAL if t.asdecimal else FieldType.FLOAT), extra
    if isinstance(t, sa.Float):
        return FieldType.FLOAT, extra
    if isinstance(t, sa.DateTime):
        return FieldType.DATETIME, extra
    if isinstance(t, sa.Date):
        return FieldType.DATE, extra
    if isinstance(t, sa.Time):
        return FieldType.TIME, extra
    if isinstance(t, sa.Uuid):
        return FieldType.UUID, extra
    if isinstance(t, sa.JSON):
        return FieldType.JSON, extra
    if isinstance(t, sa.Text):
        return FieldType.TEXT, extra
    if isinstance(t, sa.String):
        extra["max_length"] = t.length
        return FieldType.STRING, extra
    try:
        py = t.python_type
    except NotImplementedError:
        return FieldType.STRING, extra
    mapping: dict[type, FieldType] = {
        int: FieldType.INTEGER,
        float: FieldType.FLOAT,
        decimal.Decimal: FieldType.DECIMAL,
        bool: FieldType.BOOLEAN,
        uuid.UUID: FieldType.UUID,
        dict: FieldType.JSON,
        list: FieldType.JSON,
    }
    return mapping.get(py, FieldType.STRING), extra


class SQLAlchemyBackend:
    name = "sqlalchemy"

    def __init__(
        self,
        bind: Engine | AsyncEngine | sessionmaker[Any] | async_sessionmaker[Any] | SessionFactory,
    ) -> None:
        if isinstance(bind, AsyncEngine):
            self.session_factory: Any = async_sessionmaker(bind, expire_on_commit=False)
            self.is_async = True
        elif isinstance(bind, Engine):
            self.session_factory = sessionmaker(bind, expire_on_commit=False)
            self.is_async = False
        elif isinstance(bind, async_sessionmaker):
            self.session_factory = bind
            self.is_async = True
        elif isinstance(bind, sessionmaker):
            self.session_factory = bind
            self.is_async = False
        elif callable(bind):
            self.session_factory = bind
            probe = bind()
            self.is_async = isinstance(probe, AsyncSession)
            _close = getattr(probe, "close", None)
            if _close is not None and not self.is_async:
                _close()
        else:
            raise TypeError(
                "bind must be an Engine, AsyncEngine, sessionmaker, async_sessionmaker or callable"
            )

    def supports(self, model: type) -> bool:
        return inspect(model, raiseerr=False) is not None

    def introspect(self, model: type, admin: ModelAdmin) -> ModelSchema:
        mapper: Mapper[Any] = inspect(model)
        fields: list[FieldSchema] = []
        fk_columns: set[str] = set()
        rel_fields: list[FieldSchema] = []

        for rel in mapper.relationships:
            target = rel.mapper.class_
            if rel.direction is MANYTOONE:
                local_cols = [c for c in rel.local_columns]
                for c in local_cols:
                    fk_columns.add(str(c.key))
                nullable = all(c.nullable for c in local_cols)
                rel_fields.append(
                    FieldSchema(
                        rel.key,
                        FieldType.MANY_TO_ONE,
                        nullable=nullable,
                        required=not nullable,
                        relation=Relation(model=target, kind=FieldType.MANY_TO_ONE),
                        sortable=False,
                    )
                )
            elif rel.direction is MANYTOMANY:
                rel_fields.append(
                    FieldSchema(
                        rel.key,
                        FieldType.MANY_TO_MANY,
                        nullable=True,
                        relation=Relation(model=target, kind=FieldType.MANY_TO_MANY),
                        sortable=False,
                        filterable=True,
                    )
                )
            elif rel.direction is ONETOMANY:
                rel_fields.append(
                    FieldSchema(
                        rel.key,
                        FieldType.ONE_TO_MANY,
                        read_only=True,
                        relation=Relation(model=target, kind=FieldType.ONE_TO_MANY),
                        sortable=False,
                        filterable=False,
                    )
                )

        pk_attr: str | None = None
        for attr in mapper.column_attrs:
            column = attr.columns[0]
            if not isinstance(column, sa.Column):
                continue  # column_property expressions
            if attr.key in fk_columns:
                continue
            ftype, extra = _column_type(column)
            is_pk = bool(column.primary_key)
            has_default = (
                column.default is not None
                or column.server_default is not None
                or (is_pk and column.autoincrement in (True, "auto") and ftype == FieldType.INTEGER)
            )
            nullable = bool(column.nullable) and not is_pk
            if is_pk and pk_attr is None:
                pk_attr = attr.key
            fields.append(
                FieldSchema(
                    attr.key,
                    ftype,
                    primary_key=is_pk,
                    required=not nullable and not has_default,
                    nullable=nullable,
                    read_only=is_pk and has_default,
                    has_default=has_default,
                    help_text=column.comment or column.doc or "",
                    **extra,
                )
            )
        if pk_attr is None:
            raise ValueError(f"{model.__name__}: composite or missing primary key is not supported")
        # relation fields go where their FK column was, i.e. right after scalars for simplicity
        fields.extend(rel_fields)
        name = model.__name__
        return ModelSchema(
            key=name.lower(), label=name, label_plural=f"{name}s", pk_field=pk_attr, fields=fields
        )

    def repository(
        self, model: type, schema: ModelSchema, admin: ModelAdmin
    ) -> SQLAlchemyRepository:
        return SQLAlchemyRepository(self, model, schema, admin)


class SQLAlchemyRepository:
    def __init__(
        self, backend: SQLAlchemyBackend, model: type, schema: ModelSchema, admin: ModelAdmin
    ) -> None:
        self.backend = backend
        self.model = model
        self.schema = schema
        self.admin = admin
        self.mapper: Mapper[Any] = inspect(model)
        self.pk_col: ColumnElement[Any] = getattr(model, schema.pk_field)
        self._relations = {r.key: r for r in self.mapper.relationships}
        self._loads = [
            selectinload(getattr(model, f.name))
            for f in schema.fields
            if f.type in (FieldType.MANY_TO_ONE, FieldType.MANY_TO_MANY)
        ]

    # ---- session plumbing -------------------------------------------------------------------

    async def _run(self, fn: Callable[[Session], T]) -> T:
        if self.backend.is_async:
            async with self.backend.session_factory() as session:
                return await session.run_sync(fn)  # type: ignore[no-any-return]
        else:

            def runner() -> T:
                with self.backend.session_factory() as session:
                    return fn(session)

            return await anyio.to_thread.run_sync(runner)

    # ---- query building ---------------------------------------------------------------------

    def _base(self) -> sa.Select[Any]:
        return sa.select(self.model).options(*self._loads)

    def _condition(self, cond: Condition) -> Any:
        f = self.schema.field(cond.field)
        op, value = cond.op, cond.value
        if f.type == FieldType.MANY_TO_MANY:
            rel = self._relations[f.name]
            target_pk = inspect(rel.mapper.class_).primary_key[0]
            values = value if isinstance(value, list) else [value]
            attr = getattr(self.model, f.name)
            if op in (Op.IN, Op.EQ):
                return attr.any(target_pk.in_(values))
            if op in (Op.NOT_IN, Op.NE):
                return ~attr.any(target_pk.in_(values))
            if op == Op.IS_NULL:
                return ~attr.any() if value else attr.any()
            raise ValidationError({f.name: f"operator {op.value} not supported for relations"})
        if f.type == FieldType.MANY_TO_ONE:
            rel = self._relations[f.name]
            col = next(iter(rel.local_columns))
        else:
            col = getattr(self.model, f.name)
        if op == Op.EQ:
            return col == value
        if op == Op.NE:
            return col != value
        if op == Op.LT:
            return col < value
        if op == Op.LTE:
            return col <= value
        if op == Op.GT:
            return col > value
        if op == Op.GTE:
            return col >= value
        if op == Op.IN:
            return col.in_(value or [])
        if op == Op.NOT_IN:
            return col.not_in(value or [])
        if op == Op.CONTAINS:
            return sa.cast(col, sa.String).contains(str(value))
        if op == Op.ICONTAINS:
            return sa.cast(col, sa.String).ilike(f"%{value}%")
        if op == Op.STARTSWITH:
            return sa.cast(col, sa.String).startswith(str(value))
        if op == Op.ENDSWITH:
            return sa.cast(col, sa.String).endswith(str(value))
        if op == Op.IS_NULL:
            return col.is_(None) if value else col.is_not(None)
        if op == Op.BETWEEN:
            lo, hi = value
            return col.between(lo, hi)
        raise ValidationError({f.name: f"unsupported operator {op.value}"})

    def _group(self, group: FilterGroup) -> Any:
        parts: builtins.list[Any] = []
        for item in group.items:
            clause = self._condition(item) if isinstance(item, Condition) else self._group(item)
            if clause is not None:
                parts.append(clause)
        if not parts:
            return None
        return sa.and_(*parts) if group.logic == "and" else sa.or_(*parts)

    def _apply(self, stmt: sa.Select[Any], query: ListQuery) -> sa.Select[Any]:
        clause = self._group(query.filters)
        if clause is not None:
            stmt = stmt.where(clause)
        if query.search:
            cols = [getattr(self.model, f.name) for f in self.schema.fields if f.searchable]
            if cols:
                term = f"%{query.search}%"
                stmt = stmt.where(sa.or_(*[sa.cast(c, sa.String).ilike(term) for c in cols]))
        return stmt

    def _ordered(self, stmt: sa.Select[Any], query: ListQuery) -> sa.Select[Any]:
        for name, direction in query.sort:
            col = getattr(self.model, name)
            stmt = stmt.order_by(col.desc() if direction == "desc" else col.asc())
        return stmt.order_by(self.pk_col.asc())

    # ---- Repository API ---------------------------------------------------------------------

    async def list(self, query: ListQuery) -> Page[Any]:
        def fn(session: Session) -> Page[Any]:
            filtered = self._apply(sa.select(self.model), query)
            total = session.scalar(sa.select(sa.func.count()).select_from(filtered.subquery())) or 0
            stmt = self._ordered(self._apply(self._base(), query), query)
            stmt = stmt.offset(query.offset).limit(query.limit)
            items = list(session.scalars(stmt).unique().all())
            session.expunge_all()
            return Page(items=items, total=int(total))

        return await self._run(fn)

    async def count(self, query: ListQuery) -> int:
        def fn(session: Session) -> int:
            filtered = self._apply(sa.select(self.model), query)
            return int(
                session.scalar(sa.select(sa.func.count()).select_from(filtered.subquery())) or 0
            )

        return await self._run(fn)

    def _fetch_one(self, session: Session, pk: Any) -> Any | None:
        obj = session.scalars(self._base().where(self.pk_col == pk)).unique().one_or_none()
        if obj is not None:
            session.expunge_all()
        return obj

    async def get(self, pk: Any) -> Any | None:
        return await self._run(lambda s: self._fetch_one(s, pk))

    async def get_many(self, pks: Sequence[Any]) -> Sequence[Any]:
        def fn(session: Session) -> builtins.list[Any]:
            items = list(
                session.scalars(self._base().where(self.pk_col.in_(list(pks)))).unique().all()
            )
            session.expunge_all()
            return items

        return await self._run(fn)

    def _assign(self, session: Session, obj: Any, data: dict[str, Any]) -> None:
        for name, value in data.items():
            f = self.schema.field(name)
            if f.type == FieldType.MANY_TO_ONE:
                rel = self._relations[name]
                if value is None:
                    setattr(obj, name, None)
                else:
                    target_obj = session.get(rel.mapper.class_, value)
                    if target_obj is None:
                        raise ValidationError({name: "related object does not exist"})
                    setattr(obj, name, target_obj)
            elif f.type == FieldType.MANY_TO_MANY:
                rel = self._relations[name]
                target = rel.mapper.class_
                target_pk = inspect(target).primary_key[0]
                ids = list(value or [])
                targets = (
                    list(session.scalars(sa.select(target).where(target_pk.in_(ids))).all())
                    if ids
                    else []
                )
                if len(targets) != len(set(ids)):
                    raise ValidationError({name: "some related objects do not exist"})
                setattr(obj, name, targets)
            else:
                setattr(obj, name, value)

    async def create(self, data: dict[str, Any]) -> Any:
        def fn(session: Session) -> Any:
            obj = self.model()
            session.add(obj)
            self._assign(session, obj, data)
            session.commit()
            pk = self.pk_of(obj)
            session.expire_all()
            return self._fetch_one(session, pk)

        return await self._run(fn)

    async def update(self, obj: Any, data: dict[str, Any]) -> Any:
        pk = self.pk_of(obj)

        def fn(session: Session) -> Any:
            live = session.scalars(self._base().where(self.pk_col == pk)).unique().one()
            self._assign(session, live, data)
            session.commit()
            session.expire_all()
            return self._fetch_one(session, pk)

        return await self._run(fn)

    async def delete(self, objs: Sequence[Any]) -> int:
        pks = [self.pk_of(o) for o in objs]

        def fn(session: Session) -> int:
            live: builtins.list[Any] = [
                *session.scalars(sa.select(self.model).where(self.pk_col.in_(pks))).all()
            ]
            for o in live:
                session.delete(o)
            session.commit()
            return len(live)

        return await self._run(fn)

    # ---- serialization ----------------------------------------------------------------------

    def pk_of(self, obj: Any) -> Any:
        return getattr(obj, self.schema.pk_field)

    def label_of(self, obj: Any) -> str:
        if _has_custom_str(obj):
            return str(obj)
        for f in self.schema.fields:
            if f.type == FieldType.STRING and getattr(obj, f.name, None):
                return str(getattr(obj, f.name))
        return f"{self.schema.label} #{self.pk_of(obj)}"

    def _ref(self, related: Any) -> dict[str, Any] | None:
        if related is None:
            return None
        target_pk = inspect(type(related)).primary_key[0].key
        res = self.admin.site.resource_for_model(type(related))
        label = res.repository.label_of(related) if res else _generic_label(related)
        return {"id": getattr(related, target_pk), "label": label}

    def to_dict(self, obj: Any) -> dict[str, Any]:
        out: dict[str, Any] = {}
        for f in self.schema.fields:
            if f.type == FieldType.ONE_TO_MANY:
                continue
            value = getattr(obj, f.name)
            if f.type == FieldType.MANY_TO_ONE:
                out[f.name] = self._ref(value)
            elif f.type == FieldType.MANY_TO_MANY:
                out[f.name] = [self._ref(v) for v in value]
            elif isinstance(value, enum.Enum):
                out[f.name] = value.value
            else:
                out[f.name] = value
        return out


def _has_custom_str(obj: Any) -> bool:
    return cast(Any, type(obj)).__str__ is not object.__str__


def _generic_label(obj: Any) -> str:
    if _has_custom_str(obj):
        return str(obj)
    for name in ("name", "title", "label", "username", "email"):
        v = getattr(obj, name, None)
        if v:
            return str(v)
    pk = inspect(type(obj)).primary_key[0].key
    return f"{type(obj).__name__} #{getattr(obj, pk)}"
