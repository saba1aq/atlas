from __future__ import annotations

import datetime as dt
import enum
import uuid
from collections.abc import AsyncIterator

import pytest
from beanie import BackLink, Document, Link, init_beanie
from pydantic import Field
from pymongo import AsyncMongoClient

from atlas import AdminSite
from atlas.backends.beanie import BeanieBackend
from tests.contract import AuthorAdminBase, BookAdminBase, ContractTests
from tests.mongo_utils import MONGO_URL, requires_mongo

pytestmark = requires_mongo


class Author(Document):
    id: int  # type: ignore[assignment]
    name: str = Field(max_length=50)
    born: dt.date | None = None
    active: bool = True
    books: list[BackLink[Book]] = Field(json_schema_extra={"original_field": "author"})

    class Settings:
        name = "author"


class Genre(enum.StrEnum):
    sf = "sf"
    fantasy = "fantasy"


class Book(Document):
    id: int  # type: ignore[assignment]
    title: str = Field(max_length=200)
    pages: int | None = None
    genre: Genre | None = None
    author: Link[Author] | None = None
    tags: list[Link[Author]] = []
    created_at: dt.datetime = Field(default_factory=lambda: dt.datetime(2024, 1, 1, 12, 0))

    class Settings:
        name = "book"


Author.model_rebuild()


async def seed() -> None:
    a1 = await Author(
        id=1, name="Ursula Le Guin", born=dt.date(1929, 10, 21), active=False
    ).insert()
    a2 = await Author(id=2, name="Ted Chiang", born=dt.date(1967, 1, 1), active=True).insert()
    a3 = await Author(id=3, name="Ann Leckie", born=None, active=True).insert()
    await Book(
        id=1, title="The Dispossessed", pages=341, genre=Genre.sf, author=a1, tags=[a1, a2]
    ).insert()
    await Book(id=2, title="Exhalation", pages=350, genre=Genre.sf, author=a2).insert()
    await Book(
        id=3, title="Ancillary Justice", pages=416, genre=Genre.sf, author=a3, tags=[a3]
    ).insert()
    await Book(
        id=4, title="A Wizard of Earthsea", pages=183, genre=Genre.fantasy, author=a1
    ).insert()


class BeanieBookAdmin(BookAdminBase):
    pass


class TestBeanieContract(ContractTests):
    @pytest.fixture
    async def site(self) -> AsyncIterator[AdminSite]:
        name = f"atlas_test_{uuid.uuid4().hex[:8]}"
        client: AsyncMongoClient[dict] = AsyncMongoClient(MONGO_URL)
        await init_beanie(database=client[name], document_models=[Author, Book])
        await seed()
        s = AdminSite("Test", backend=BeanieBackend())
        s.register(Author, AuthorAdminBase)
        s.register(Book, BeanieBookAdmin)
        yield s
        await client.drop_database(name)
        await client.close()

    async def test_links_are_dbrefs_beanie_can_read(self, site: AdminSite) -> None:
        """Documents written by the admin must load through Beanie with links intact."""
        from tests.conftest import Client, body

        c = Client(site)
        r = await c.post("/book", {"title": "Via admin", "author": 2, "tags": [1, 3]})
        assert r.status == 201, body(r)
        doc = await Book.get(body(r)["id"], fetch_links=True)
        assert doc is not None and doc.author is not None
        assert doc.author.name == "Ted Chiang"  # type: ignore[union-attr]
        assert sorted(t.name for t in doc.tags) == ["Ann Leckie", "Ursula Le Guin"]  # type: ignore[union-attr]
