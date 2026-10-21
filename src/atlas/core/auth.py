"""Pluggable authentication. Core only knows ``AuthProvider``; transports never touch auth."""

from __future__ import annotations

import base64
import hashlib
import hmac
import secrets
import time
from collections.abc import Awaitable, Callable, Mapping
from dataclasses import dataclass, field
from typing import Any, Protocol, cast, runtime_checkable

from .http import AdminRequest, AdminResponse, Cookie

SESSION_COOKIE = "atlas_session"


@dataclass(slots=True)
class User:
    id: Any
    username: str
    display_name: str = ""
    is_superuser: bool = True
    extra: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "username": self.username,
            "display_name": self.display_name or self.username,
            "is_superuser": self.is_superuser,
        }


@runtime_checkable
class AuthProvider(Protocol):
    async def authenticate(self, request: AdminRequest) -> User | None:
        """Resolve the current user from cookies / headers. ``None`` means anonymous."""
        ...

    async def login(self, request: AdminRequest, username: str, password: str) -> User | None: ...

    def on_login(self, user: User, response: AdminResponse) -> AdminResponse:
        """Attach session cookie / token to the login response."""
        ...

    def on_logout(self, response: AdminResponse) -> AdminResponse: ...


class TokenSigner:
    """Stateless signed session token: ``base64(username|expires).signature``."""

    def __init__(self, secret_key: str, max_age: int = 7 * 24 * 3600) -> None:
        if not secret_key:
            raise ValueError("secret_key must not be empty")
        self._key = secret_key.encode()
        self.max_age = max_age

    def sign(self, subject: str) -> str:
        expires = int(time.time()) + self.max_age
        payload = base64.urlsafe_b64encode(f"{subject}|{expires}".encode()).decode().rstrip("=")
        return f"{payload}.{self._sig(payload)}"

    def unsign(self, token: str) -> str | None:
        if not token or "." not in token:
            return None
        payload, sig = token.rsplit(".", 1)
        if not hmac.compare_digest(sig, self._sig(payload)):
            return None
        try:
            raw = base64.urlsafe_b64decode(payload + "=" * (-len(payload) % 4)).decode()
            subject, expires = raw.rsplit("|", 1)
        except (ValueError, UnicodeDecodeError):
            return None
        if int(expires) < time.time():
            return None
        return subject

    def _sig(self, payload: str) -> str:
        return hmac.new(self._key, payload.encode(), hashlib.sha256).hexdigest()


def hash_password(password: str, *, iterations: int = 200_000) -> str:
    salt = secrets.token_hex(16)
    digest = hashlib.pbkdf2_hmac("sha256", password.encode(), salt.encode(), iterations).hex()
    return f"pbkdf2_sha256${iterations}${salt}${digest}"


def verify_password(password: str, hashed: str) -> bool:
    try:
        algo, iterations, salt, digest = hashed.split("$", 3)
    except ValueError:
        return False
    if algo != "pbkdf2_sha256":
        return False
    candidate = hashlib.pbkdf2_hmac(
        "sha256", password.encode(), salt.encode(), int(iterations)
    ).hex()
    return hmac.compare_digest(candidate, digest)


class SessionAuth:
    """Cookie-session auth with a pluggable credential check.

    ``verify(username, password)`` returns a ``User`` or ``None``; ``load(username)`` reloads the
    user for an existing session. Both may be sync or async.
    """

    def __init__(
        self,
        secret_key: str,
        verify: Callable[[str, str], Awaitable[User | None] | User | None],
        load: Callable[[str], Awaitable[User | None] | User | None] | None = None,
        *,
        cookie_name: str = SESSION_COOKIE,
        max_age: int = 7 * 24 * 3600,
        secure_cookie: bool = False,
    ) -> None:
        self.signer = TokenSigner(secret_key, max_age)
        self._verify = verify
        self._load = load
        self.cookie_name = cookie_name
        self.secure_cookie = secure_cookie

    async def authenticate(self, request: AdminRequest) -> User | None:
        token = request.cookies.get(self.cookie_name)
        if not token:
            auth = request.headers.get("authorization", "")
            if auth.lower().startswith("bearer "):
                token = auth[7:].strip()
        if not token:
            return None
        username = self.signer.unsign(token)
        if username is None:
            return None
        if self._load is None:
            return User(id=username, username=username)
        return cast(User | None, await _maybe_await(self._load(username)))

    async def login(self, request: AdminRequest, username: str, password: str) -> User | None:
        return cast(User | None, await _maybe_await(self._verify(username, password)))

    def on_login(self, user: User, response: AdminResponse) -> AdminResponse:
        token = self.signer.sign(user.username)
        response.headers["x-atlas-token"] = token
        return response.set_cookie(
            Cookie(self.cookie_name, token, max_age=self.signer.max_age, secure=self.secure_cookie)
        )

    def on_logout(self, response: AdminResponse) -> AdminResponse:
        return response.delete_cookie(self.cookie_name)


class SimpleAuth(SessionAuth):
    """Static user list for development: ``SimpleAuth("secret", {"admin": "password"})``.

    Values may be plain passwords or ``hash_password()`` output.
    """

    def __init__(self, secret_key: str, users: Mapping[str, str], **kwargs: Any) -> None:
        self._users = dict(users)
        super().__init__(secret_key, self._check, self._get, **kwargs)

    def _check(self, username: str, password: str) -> User | None:
        stored = self._users.get(username)
        if stored is None:
            return None
        ok = (
            verify_password(password, stored)
            if stored.startswith("pbkdf2_sha256$")
            else hmac.compare_digest(password, stored)
        )
        return User(id=username, username=username) if ok else None

    def _get(self, username: str) -> User | None:
        return User(id=username, username=username) if username in self._users else None


async def _maybe_await(value: Any) -> Any:
    if hasattr(value, "__await__"):
        return await value
    return value
