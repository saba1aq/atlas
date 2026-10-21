from __future__ import annotations

import datetime as dt
import enum
from collections.abc import AsyncIterator

import pytest
from tortoise import Tortoise, fields
from tortoise.models import Model

from atlas import AdminSite
from atlas.backends.tortoise import TortoiseBackend
from tests.contract import AuthorAdminBase, BookAdminBase, ContractTests


class Genre(enum.StrEnum):
    sf = "sf"
    fantasy = "fantasy"


class Author(Model):
    id = fields.IntField(primary_key=True)
    name = fields.CharField(max_length=50)
    born = fields.DateField(null=True)
    active = fields.BooleanField(default=True)

    books: fields.ReverseRelation[Book]


class Book(Model):
    id = fields.IntField(primary_key=True)
    title = fields.CharField(max_length=200)
    pages = fields.IntField(null=True)
    genre = fields.CharEnumField(Genre, null=True)
    author: fields.ForeignKeyNullableRelation[Author] = fields.ForeignKeyField(
        "models.Author", related_name="books", null=True
    )
    tags: fields.ManyToManyRelation[Author] = fields.ManyToManyField(
        "models.Author", related_name="tagged"
    )
    created_at = fields.DatetimeField(default=lambda: dt.datetime(2024, 1, 1, 12, 0, tzinfo=dt.UTC))


async def seed() -> None:
    a1 = await Author.create(id=1, name="Ursula Le Guin", born=dt.date(1929, 10, 21), active=False)
    a2 = await Author.create(id=2, name="Ted Chiang", born=dt.date(1967, 1, 1), active=True)
    a3 = await Author.create(id=3, name="Ann Leckie", born=None, active=True)
    b1 = await Book.create(id=1, title="The Dispossessed", pages=341, genre=Genre.sf, author=a1)
    await b1.tags.add(a1, a2)
    await Book.create(id=2, title="Exhalation", pages=350, genre=Genre.sf, author=a2)
    b3 = await Book.create(id=3, title="Ancillary Justice", pages=416, genre=Genre.sf, author=a3)
    await b3.tags.add(a3)
    await Book.create(id=4, title="A Wizard of Earthsea", pages=183, genre=Genre.fantasy, author=a1)


class TortoiseBookAdmin(BookAdminBase):
    pass


class TestTortoiseContract(ContractTests):
    @pytest.fixture
    async def site(self) -> AsyncIterator[AdminSite]:
        await Tortoise.init(db_url="sqlite://:memory:", modules={"models": [__name__]})
        await Tortoise.generate_schemas()
        await seed()
        s = AdminSite("Test", backend=TortoiseBackend())
        s.register(Author, AuthorAdminBase)
        s.register(Book, TortoiseBookAdmin)
        yield s
        await Tortoise.close_connections()


def test_supports() -> None:
    backend = TortoiseBackend()
    assert backend.supports(Book) and not backend.supports(dict)
