from __future__ import annotations

from typing import Any


class AdminError(Exception):
    status: int = 500

    def __init__(self, message: str = "", *, details: Any = None) -> None:
        super().__init__(message)
        self.message = message or self.__class__.__name__
        self.details = details

    def to_dict(self) -> dict[str, Any]:
        payload: dict[str, Any] = {"error": self.message}
        if self.details is not None:
            payload["details"] = self.details
        return payload


class NotFound(AdminError):
    status = 404


class BadRequest(AdminError):
    status = 400


class Unauthorized(AdminError):
    status = 401


class PermissionDenied(AdminError):
    status = 403


class ValidationError(AdminError):
    """Field-level validation errors: ``{"field": "message"}``."""

    status = 422

    def __init__(
        self, errors: dict[str, str] | None = None, message: str = "Validation failed"
    ) -> None:
        super().__init__(message, details=errors or {})
        self.errors: dict[str, str] = errors or {}

    def to_dict(self) -> dict[str, Any]:
        return {"error": self.message, "errors": self.errors}
