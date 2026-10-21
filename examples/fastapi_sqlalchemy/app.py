"""FastAPI + SQLAlchemy (async, SQLite) example.

uv run uvicorn examples.fastapi_sqlalchemy.app:app --reload
open http://127.0.0.1:8000/admin  (login: admin / admin)
"""

from __future__ import annotations

import datetime as dt
import enum
from contextlib import asynccontextmanager
from pathlib import Path
from typing import Any

import sqlalchemy as sa
from fastapi import FastAPI
from sqlalchemy.ext.asyncio import AsyncSession, create_async_engine
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, relationship

from atlas import AdminSite, ModelAdmin, SimpleAuth, action
from atlas.backends.sqlalchemy import SQLAlchemyBackend
from atlas.transports.starlette import mount

DB_PATH = Path(__file__).with_name("example.db")
engine = create_async_engine(f"sqlite+aiosqlite:///{DB_PATH}")


class Base(DeclarativeBase):
    pass


class Status(enum.Enum):
    draft = "draft"
    published = "published"
    archived = "archived"


post_tags = sa.Table(
    "post_tags",
    Base.metadata,
    sa.Column("post_id", sa.ForeignKey("posts.id"), primary_key=True),
    sa.Column("tag_id", sa.ForeignKey("tags.id"), primary_key=True),
)


class User(Base):
    __tablename__ = "users"
    id: Mapped[int] = mapped_column(primary_key=True)
    email: Mapped[str] = mapped_column(sa.String(120), unique=True)
    name: Mapped[str] = mapped_column(sa.String(80))
    is_active: Mapped[bool] = mapped_column(default=True)
    joined_at: Mapped[dt.datetime] = mapped_column(default=dt.datetime.utcnow)
    posts: Mapped[list[Post]] = relationship(back_populates="author")

    def __str__(self) -> str:
        return self.name


class Tag(Base):
    __tablename__ = "tags"
    id: Mapped[int] = mapped_column(primary_key=True)
    name: Mapped[str] = mapped_column(sa.String(40), unique=True)


class Post(Base):
    __tablename__ = "posts"
    id: Mapped[int] = mapped_column(primary_key=True)
    title: Mapped[str] = mapped_column(sa.String(200))
    body: Mapped[str | None] = mapped_column(sa.Text)
    status: Mapped[Status] = mapped_column(sa.Enum(Status, native_enum=False), default=Status.draft)
    rating: Mapped[float | None]
    meta: Mapped[dict[str, Any] | None] = mapped_column(sa.JSON)
    published_on: Mapped[dt.date | None]
    author_id: Mapped[int | None] = mapped_column(sa.ForeignKey("users.id"))
    author: Mapped[User | None] = relationship(back_populates="posts")
    tags: Mapped[list[Tag]] = relationship(secondary=post_tags)


async def seed() -> None:
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    async with AsyncSession(engine) as s:
        if await s.scalar(sa.select(sa.func.count()).select_from(User)):
            return
        alice = User(email="alice@example.com", name="Alice")
        bob = User(email="bob@example.com", name="Bob", is_active=False)
        py, web, db = Tag(name="python"), Tag(name="web"), Tag(name="databases")
        s.add_all([alice, bob, py, web, db])
        await s.flush()
        for i in range(1, 31):
            s.add(
                Post(
                    title=f"Post #{i}",
                    body=f"Body of post {i}",
                    status=list(Status)[i % 3],
                    rating=round(i / 7, 2),
                    meta={"views": i * 10},
                    published_on=dt.date(2024, 1, 1) + dt.timedelta(days=i),
                    author=alice if i % 2 else bob,
                    tags=[py] + ([web] if i % 3 == 0 else []) + ([db] if i % 5 == 0 else []),
                )
            )
        await s.commit()


site = AdminSite(
    "Blog Admin",
    backend=SQLAlchemyBackend(engine),
    auth=SimpleAuth("change-me-in-production", {"admin": "admin"}),
)


@site.register(User)
class UserAdmin(ModelAdmin):
    list_display = ["id", "name", "email", "is_active", "joined_at"]
    search_fields = ["name", "email"]
    readonly_fields = ["joined_at"]
    ordering = ["name"]


@site.register(Tag)
class TagAdmin(ModelAdmin):
    search_fields = ["name"]


@site.register(Post)
class PostAdmin(ModelAdmin):
    list_display = ["id", "title", "status", "author", "rating", "published_on"]
    list_filter = ["status", "author", "tags", "published_on", "rating"]
    search_fields = ["title", "body"]
    ordering = ["-id"]

    @action("Publish", confirm="Publish the selected posts?")
    async def publish(self, request: Any, objs: list[Post]) -> str:
        repo = self.site.resource("post").repository
        for post in objs:
            await repo.update(post, {"status": "published"})
        return f"Published {len(objs)} post(s)"


@asynccontextmanager
async def lifespan(app: FastAPI):  # type: ignore[no-untyped-def]
    await seed()
    yield
    await engine.dispose()


app = FastAPI(lifespan=lifespan)
mount(app, site, path="/admin")


@app.get("/")
def root() -> dict[str, str]:
    return {"admin": "/admin"}
