from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass, field
from typing import Any, Generic, Literal, TypeVar

from .filters import FilterGroup

T = TypeVar("T")

SortDir = Literal["asc", "desc"]


@dataclass(slots=True)
class ListQuery:
    filters: FilterGroup = field(default_factory=FilterGroup)
    search: str | None = None
    sort: list[tuple[str, SortDir]] = field(default_factory=list)
    offset: int = 0
    limit: int = 25

    @staticmethod
    def parse_sort(raw: str | None) -> list[tuple[str, SortDir]]:
        """``"-created_at,name"`` -> ``[("created_at", "desc"), ("name", "asc")]``."""
        if not raw:
            return []
        out: list[tuple[str, SortDir]] = []
        for part in raw.split(","):
            part = part.strip()
            if not part:
                continue
            if part.startswith("-"):
                out.append((part[1:], "desc"))
            else:
                out.append((part.lstrip("+"), "asc"))
        return out


@dataclass(slots=True)
class Page(Generic[T]):
    items: Sequence[T]
    total: int

    def to_dict(self, serialize: Any) -> dict[str, Any]:
        return {"items": [serialize(i) for i in self.items], "total": self.total}
