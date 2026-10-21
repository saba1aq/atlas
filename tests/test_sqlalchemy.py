from __future__ import annotations

import datetime as dt
import enum
from collections.abc import AsyncIterator

import pytest
import sqlalchemy as sa
from sqlalchemy.ext.asyncio import create_async_engine
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, relationship
from sqlalchemy.pool import StaticPool

from atlas import AdminSite
from atlas.backends.sqlalchemy import SQLAlchemyBackend
from tests.contract import AuthorAdminBase, BookAdminBase, ContractTests


class Base(DeclarativeBase):
    pass


class Genre(enum.Enum):
    sf = "sf"
    fantasy = "fantasy"


book_tags = sa.Table(
    "book_tags",
    Base.metadata,
    sa.Column("book_id", sa.ForeignKey("author_books.id"), primary_key=True),
    sa.Column("author_id", sa.ForeignKey("authors.id"), primary_key=True),
)


class Author(Base):
    __tablename__ = "authors"
    id: Mapped[int] = mapped_column(primary_key=True)
    name: Mapped[str] = mapped_column(sa.String(50))
    born: Mapped[dt.date | None]
    active: Mapped[bool] = mapped_column(default=True)
    books: Mapped[list[Book]] = relationship(back_populates="author", foreign_keys="Book.author_id")


class Book(Base):
    __tablename__ = "author_books"
    id: Mapped[int] = mapped_column(primary_key=True)
    title: Mapped[str] = mapped_column(sa.String(200))
    pages: Mapped[int | None]
    genre: Mapped[Genre | None] = mapped_column(sa.Enum(Genre, native_enum=False))
    author_id: Mapped[int | None] = mapped_column(sa.ForeignKey("authors.id"))
    author: Mapped[Author | None] = relationship(back_populates="books", foreign_keys=[author_id])
    tags: Mapped[list[Author]] = relationship(secondary=book_tags)
    created_at: Mapped[dt.datetime] = mapped_column(default=lambda: dt.datetime(2024, 1, 1, 12, 0))


def seed(session: sa.orm.Session) -> None:
    a1 = Author(id=1, name="Ursula Le Guin", born=dt.date(1929, 10, 21), active=False)
    a2 = Author(id=2, name="Ted Chiang", born=dt.date(1967, 1, 1), active=True)
    a3 = Author(id=3, name="Ann Leckie", born=None, active=True)
    session.add_all([a1, a2, a3])
    session.flush()
    session.add_all(
        [
            Book(
                id=1, title="The Dispossessed", pages=341, genre=Genre.sf, author=a1, tags=[a1, a2]
            ),
            Book(id=2, title="Exhalation", pages=350, genre=Genre.sf, author=a2),
            Book(id=3, title="Ancillary Justice", pages=416, genre=Genre.sf, author=a3, tags=[a3]),
            Book(id=4, title="A Wizard of Earthsea", pages=183, genre=Genre.fantasy, author=a1),
        ]
    )
    session.commit()


class SABookAdmin(BookAdminBase):
    pass


def make_site(backend: SQLAlchemyBackend) -> AdminSite:
    site = AdminSite("Test", backend=backend)
    site.register(Author, AuthorAdminBase)
    site.register(Book, SABookAdmin)
    return site


class TestSQLAlchemySync(ContractTests):
    @pytest.fixture
    def site(self) -> AdminSite:
        engine = sa.create_engine(
            "sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool
        )
        Base.metadata.create_all(engine)
        with sa.orm.Session(engine) as s:
            seed(s)
        return make_site(SQLAlchemyBackend(engine))


class TestSQLAlchemyAsync(ContractTests):
    @pytest.fixture
    async def site(self) -> AsyncIterator[AdminSite]:
        engine = create_async_engine("sqlite+aiosqlite://", poolclass=StaticPool)
        async with engine.begin() as conn:
            await conn.run_sync(Base.metadata.create_all)
        async with engine.connect() as conn:
            await conn.run_sync(lambda c: seed(sa.orm.Session(bind=c)))
        yield make_site(SQLAlchemyBackend(engine))
        await engine.dispose()


def test_supports_and_bind_types() -> None:
    engine = sa.create_engine("sqlite://")
    backend = SQLAlchemyBackend(sa.orm.sessionmaker(engine))
    assert backend.supports(Book) and not backend.supports(dict)
    assert not backend.is_async
    with pytest.raises(TypeError):
        SQLAlchemyBackend(object())  # type: ignore[arg-type]
