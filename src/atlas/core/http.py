"""Framework-neutral request/response. Transports convert to and from these."""

from __future__ import annotations

import json
from collections.abc import Mapping
from dataclasses import dataclass, field
from typing import Any

from .exceptions import BadRequest


@dataclass(slots=True)
class AdminRequest:
    method: str
    path: str  # path relative to the admin API root, always starts with "/"
    query: Mapping[str, list[str]] = field(default_factory=dict)
    headers: Mapping[str, str] = field(default_factory=dict)  # lower-case keys
    cookies: Mapping[str, str] = field(default_factory=dict)
    body: bytes = b""
    user: Any = None
    state: dict[str, Any] = field(default_factory=dict)

    def param(self, name: str, default: str | None = None) -> str | None:
        values = self.query.get(name)
        return values[0] if values else default

    def int_param(
        self, name: str, default: int, *, minimum: int | None = None, maximum: int | None = None
    ) -> int:
        raw = self.param(name)
        if raw is None or raw == "":
            return default
        try:
            value = int(raw)
        except ValueError as exc:
            raise BadRequest(f"{name} must be an integer") from exc
        if minimum is not None:
            value = max(minimum, value)
        if maximum is not None:
            value = min(maximum, value)
        return value

    def json(self) -> Any:
        if not self.body:
            return None
        try:
            return json.loads(self.body)
        except json.JSONDecodeError as exc:
            raise BadRequest(f"invalid JSON body: {exc.msg}") from exc


@dataclass(slots=True)
class Cookie:
    name: str
    value: str
    max_age: int | None = None
    path: str = "/"
    http_only: bool = True
    same_site: str = "lax"
    secure: bool = False


@dataclass(slots=True)
class AdminResponse:
    status: int = 200
    body: bytes = b""
    media_type: str = "application/json"
    headers: dict[str, str] = field(default_factory=dict)
    cookies: list[Cookie] = field(default_factory=list)

    @classmethod
    def json(cls, data: Any, status: int = 200) -> AdminResponse:
        return cls(
            status=status,
            body=json.dumps(data, default=_json_default).encode(),
            media_type="application/json",
        )

    @classmethod
    def text(cls, data: str, status: int = 200, media_type: str = "text/plain") -> AdminResponse:
        return cls(status=status, body=data.encode(), media_type=media_type)

    @classmethod
    def no_content(cls) -> AdminResponse:
        return cls(status=204, body=b"", media_type="text/plain")

    def set_cookie(self, cookie: Cookie) -> AdminResponse:
        self.cookies.append(cookie)
        return self

    def delete_cookie(self, name: str, path: str = "/") -> AdminResponse:
        self.cookies.append(Cookie(name=name, value="", max_age=0, path=path))
        return self


def _json_default(value: Any) -> Any:
    import datetime as dt
    import decimal
    import enum
    import uuid

    if isinstance(value, dt.datetime | dt.date | dt.time):
        return value.isoformat()
    if isinstance(value, decimal.Decimal):
        return str(value)
    if isinstance(value, uuid.UUID):
        return str(value)
    if isinstance(value, enum.Enum):
        return value.value
    if isinstance(value, bytes):
        return value.decode("utf-8", errors="replace")
    if isinstance(value, set | frozenset):
        return list(value)
    if type(value).__name__ in ("ObjectId", "Decimal128", "DBRef"):  # bson, without importing it
        return str(value)
    raise TypeError(f"Object of type {type(value).__name__} is not JSON serializable")
