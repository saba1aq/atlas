"""Raw-collection Mongo backend with three drivers: pymongo sync, pymongo async, Motor."""

from __future__ import annotations

import datetime as dt
import enum
import uuid
from collections.abc import AsyncIterator
from typing import Annotated

import pytest
from pydantic import BaseModel, Field
from pymongo import AsyncMongoClient, MongoClient

from atlas import AdminSite
from atlas.backends.mongo import MongoBackend, Ref
from tests.contract import AuthorAdminBase, BookAdminBase, ContractTests
from tests.mongo_utils import MONGO_URL, requires_mongo

pytestmark = requires_mongo


class Author(BaseModel):
    id: int
    name: str = Field(max_length=50)
    born: dt.date | None = None
    active: bool = True


class Genre(enum.StrEnum):
    sf = "sf"
    fantasy = "fantasy"


class Book(BaseModel):
    id: int
    title: str = Field(max_length=200)
    pages: int | None = None
    genre: Genre | None = None
    author: Annotated[int | None, Ref(Author)] = None
    tags: Annotated[list[int], Ref(Author)] = []
    created_at: dt.datetime = Field(default_factory=lambda: dt.datetime(2024, 1, 1, 12, 0))


NOW = dt.datetime(2024, 1, 1, 12, 0)


def seed(db_name: str) -> None:
    client: MongoClient[dict] = MongoClient(MONGO_URL)
    client.drop_database(db_name)
    db = client[db_name]
    db["author"].insert_many(
        [
            {
                "_id": 1,
                "name": "Ursula Le Guin",
                "born": dt.datetime(1929, 10, 21),
                "active": False,
            },
            {"_id": 2, "name": "Ted Chiang", "born": dt.datetime(1967, 1, 1), "active": True},
            {"_id": 3, "name": "Ann Leckie", "born": None, "active": True},
        ]
    )
    db["book"].insert_many(
        [
            {
                "_id": 1,
                "title": "The Dispossessed",
                "pages": 341,
                "genre": "sf",
                "author": 1,
                "tags": [1, 2],
                "created_at": NOW,
            },
            {
                "_id": 2,
                "title": "Exhalation",
                "pages": 350,
                "genre": "sf",
                "author": 2,
                "tags": [],
                "created_at": NOW,
            },
            {
                "_id": 3,
                "title": "Ancillary Justice",
                "pages": 416,
                "genre": "sf",
                "author": 3,
                "tags": [3],
                "created_at": NOW,
            },
            {
                "_id": 4,
                "title": "A Wizard of Earthsea",
                "pages": 183,
                "genre": "fantasy",
                "author": 1,
                "tags": [],
                "created_at": NOW,
            },
        ]
    )
    client.close()


class MongoBookAdmin(BookAdminBase):
    pass


def make_site(database: object) -> AdminSite:
    site = AdminSite("Test", backend=MongoBackend(database))
    site.register(Author, AuthorAdminBase)
    site.register(Book, MongoBookAdmin)
    return site


class TestPyMongoSync(ContractTests):
    @pytest.fixture
    def site(self) -> AdminSite:
        name = f"atlas_test_{uuid.uuid4().hex[:8]}"
        seed(name)
        return make_site(MongoClient(MONGO_URL)[name])


class TestPyMongoAsync(ContractTests):
    @pytest.fixture
    async def site(self) -> AsyncIterator[AdminSite]:
        name = f"atlas_test_{uuid.uuid4().hex[:8]}"
        seed(name)
        client: AsyncMongoClient[dict] = AsyncMongoClient(MONGO_URL)
        yield make_site(client[name])
        await client.drop_database(name)
        await client.close()


class TestMotor(ContractTests):
    @pytest.fixture
    async def site(self) -> AsyncIterator[AdminSite]:
        from motor.motor_asyncio import AsyncIOMotorClient

        name = f"atlas_test_{uuid.uuid4().hex[:8]}"
        seed(name)
        client = AsyncIOMotorClient(MONGO_URL)
        yield make_site(client[name])
        await client.drop_database(name)
        client.close()


async def test_objectid_pk_roundtrip() -> None:
    """Default ObjectId primary keys: created ids are hex strings and resolve back."""
    from tests.conftest import Client, body

    class Note(BaseModel):
        text: str
        ref: Annotated[str | None, Ref(Author)] = None

    name = f"atlas_test_{uuid.uuid4().hex[:8]}"
    seed(name)
    client: AsyncMongoClient[dict] = AsyncMongoClient(MONGO_URL)
    site = AdminSite("T", backend=MongoBackend(client[name]))
    site.register(Author, AuthorAdminBase)
    site.register(Note, type("NoteAdmin", (BookAdminBase.__mro__[1],), {}))
    c = Client(site)
    r = await c.post("/note", {"text": "hello", "ref": 2})
    assert r.status == 201, body(r)
    pk = body(r)["id"]
    assert len(pk) == 24 and body(r)["ref"] == {"id": 2, "label": "Ted Chiang"}
    assert body(await c.get(f"/note/{pk}"))["text"] == "hello"
    assert (
        body(await c.get("/note", filters=f'[{{"field":"id","op":"eq","value":"{pk}"}}]'))["total"]
        == 1
    )
    assert (await c.delete(f"/note/{pk}")).status == 200
    assert (await c.get(f"/note/{pk}")).status == 404
    await client.drop_database(name)
    await client.close()
