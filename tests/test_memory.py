from __future__ import annotations

import datetime as dt

import pytest

from atlas import AdminSite
from atlas.backends.memory import MemoryBackend
from atlas.core.schema import Choice, FieldSchema, FieldType, ModelSchema, Relation
from tests.contract import AuthorAdminBase, BookAdminBase, ContractTests


class Author:
    pass


class Book:
    pass


def make_backend() -> MemoryBackend:
    author_schema = ModelSchema(
        key="author",
        label="Author",
        label_plural="Authors",
        pk_field="id",
        fields=[
            FieldSchema(
                "id", FieldType.INTEGER, primary_key=True, read_only=True, has_default=True
            ),
            FieldSchema("name", FieldType.STRING, required=True, nullable=False, max_length=50),
            FieldSchema("born", FieldType.DATE),
            FieldSchema("active", FieldType.BOOLEAN, nullable=False, has_default=True),
            FieldSchema(
                "books",
                FieldType.ONE_TO_MANY,
                read_only=True,
                relation=Relation(model=Book, kind=FieldType.ONE_TO_MANY),
            ),
        ],
    )
    book_schema = ModelSchema(
        key="book",
        label="Book",
        label_plural="Books",
        pk_field="id",
        fields=[
            FieldSchema(
                "id", FieldType.INTEGER, primary_key=True, read_only=True, has_default=True
            ),
            FieldSchema("title", FieldType.STRING, required=True, nullable=False),
            FieldSchema("pages", FieldType.INTEGER),
            FieldSchema(
                "genre",
                FieldType.ENUM,
                choices=[Choice("sf", "Sci-Fi"), Choice("fantasy", "Fantasy")],
            ),
            FieldSchema("author", FieldType.MANY_TO_ONE, relation=Relation(model=Author)),
            FieldSchema(
                "tags",
                FieldType.MANY_TO_MANY,
                relation=Relation(model=Author, kind=FieldType.MANY_TO_MANY),
            ),
            FieldSchema("created_at", FieldType.DATETIME, read_only=True, has_default=True),
        ],
    )
    backend = MemoryBackend({Author: author_schema, Book: book_schema})
    backend.seed(
        Author,
        [
            {"id": 1, "name": "Ursula Le Guin", "born": dt.date(1929, 10, 21), "active": False},
            {"id": 2, "name": "Ted Chiang", "born": dt.date(1967, 1, 1), "active": True},
            {"id": 3, "name": "Ann Leckie", "born": None, "active": True},
        ],
    )
    now = dt.datetime(2024, 1, 1, 12, 0)
    backend.seed(
        Book,
        [
            {
                "id": 1,
                "title": "The Dispossessed",
                "pages": 341,
                "genre": "sf",
                "author": 1,
                "tags": [1, 2],
                "created_at": now,
            },
            {
                "id": 2,
                "title": "Exhalation",
                "pages": 350,
                "genre": "sf",
                "author": 2,
                "tags": [],
                "created_at": now,
            },
            {
                "id": 3,
                "title": "Ancillary Justice",
                "pages": 416,
                "genre": "sf",
                "author": 3,
                "tags": [3],
                "created_at": now,
            },
            {
                "id": 4,
                "title": "A Wizard of Earthsea",
                "pages": 183,
                "genre": "fantasy",
                "author": 1,
                "tags": [],
                "created_at": now,
            },
        ],
    )
    return backend


class MemoryBookAdmin(BookAdminBase):
    pass


class TestMemoryContract(ContractTests):
    @pytest.fixture
    def site(self) -> AdminSite:
        s = AdminSite("Test", backend=make_backend())
        s.register(Author, AuthorAdminBase)
        s.register(Book, MemoryBookAdmin)
        return s

    async def test_create(self, client):  # type: ignore[override]
        pytest.skip("memory backend has no defaults/created_at; covered by test_core")
