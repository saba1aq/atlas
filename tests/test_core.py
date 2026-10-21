"""Core behaviour via the in-memory backend: routing, coercion, filters, auth, actions."""

from __future__ import annotations

import datetime as dt
from typing import Any

import pytest

from atlas import AdminSite, ModelAdmin, SimpleAuth, ValidationError, action
from atlas.backends.memory import MemoryBackend
from atlas.core.schema import Choice, FieldSchema, FieldType, ModelSchema, Relation
from tests.conftest import Client, body


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
            FieldSchema("id", FieldType.INTEGER, primary_key=True, read_only=True),
            FieldSchema("name", FieldType.STRING, required=True, nullable=False, max_length=50),
            FieldSchema("born", FieldType.DATE),
            FieldSchema("active", FieldType.BOOLEAN, nullable=False, has_default=True),
            FieldSchema(
                "books",
                FieldType.ONE_TO_MANY,
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
            FieldSchema("id", FieldType.INTEGER, primary_key=True, read_only=True),
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
            FieldSchema("created_at", FieldType.DATETIME, read_only=True),
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
            },
            {"id": 2, "title": "Exhalation", "pages": 350, "genre": "sf", "author": 2, "tags": []},
            {
                "id": 3,
                "title": "Ancillary Justice",
                "pages": 416,
                "genre": "sf",
                "author": 3,
                "tags": [3],
            },
            {
                "id": 4,
                "title": "A Wizard of Earthsea",
                "pages": 183,
                "genre": "fantasy",
                "author": 1,
                "tags": [],
            },
        ],
    )
    return backend


class AuthorAdmin(ModelAdmin):
    search_fields = ["name"]
    ordering = ["name"]


class BookAdmin(ModelAdmin):
    list_display = ["id", "title", "author"]
    ordering = ["-pages"]
    page_size = 2

    @action("Mark as classic", confirm="Really?")
    async def make_classic(self, request: Any, objs: list[dict[str, Any]]) -> str:
        for o in objs:
            o["title"] = f"{o['title']} (classic)"
        return f"{len(objs)} marked"

    async def validate(self, request: Any, data: dict[str, Any], obj: Any = None) -> None:
        if data.get("pages") is not None and data["pages"] < 0:
            raise ValidationError({"pages": "must be positive"})


@pytest.fixture
def site() -> AdminSite:
    s = AdminSite("Test", backend=make_backend())
    s.register(Author, AuthorAdmin)
    s.register(Book, BookAdmin)
    return s


@pytest.fixture
def client(site: AdminSite) -> Client:
    return Client(site)


async def test_schema_links_relations_and_config(client: Client) -> None:
    data = body(await client.get("/book/schema"))
    fields = {f["name"]: f for f in data["fields"]}
    assert fields["author"]["relation"] == {"resource": "author", "kind": "many_to_one"}
    assert fields["tags"]["relation"]["resource"] == "author"
    assert fields["title"]["in_list"] is True and fields["pages"]["in_list"] is False
    assert fields["author"]["sortable"] is False
    assert [f["name"] for f in data["fields"]][:3] == ["id", "title", "author"]
    assert data["page_size"] == 2 and data["ordering"] == ["-pages"]
    assert (
        data["actions"][0]["name"] == "make_classic" and data["actions"][0]["confirm"] == "Really?"
    )
    assert data["permissions"] == {"create": True, "edit": True, "delete": True}
    author = body(await client.get("/author/schema"))
    books = next(f for f in author["fields"] if f["name"] == "books")
    assert books["in_list"] is False and books["in_form"] is False


async def test_list_rejects_bad_params(client: Client) -> None:
    assert (await client.get("/book", sort="nope")).status == 400
    assert (await client.get("/book", sort="author")).status == 400
    assert (await client.get("/book", filters="{bad")).status == 400
    assert (await client.get("/book", filters='[{"field":"x","op":"eq"}]')).status == 400
    assert (await client.get("/book", filters='[{"field":"title","op":"zzz"}]')).status == 400
    assert (await client.get("/book", limit="abc")).status == 400
    assert (await client.get("/nothing")).status == 404
    assert (await client.request("PUT", "/book")).status == 405


async def test_create_validation_and_coercion(client: Client) -> None:
    r = await client.post("/book", {"pages": "12"})
    assert r.status == 422
    assert body(r)["errors"] == {"title": "This field is required."}
    r = await client.post(
        "/book", {"title": "X", "pages": "abc", "genre": "horror", "author": {"id": 1}}
    )
    assert r.status == 422
    assert set(body(r)["errors"]) == {"pages", "genre"}
    r = await client.post("/book", {"title": "X", "pages": -1})
    assert r.status == 422 and body(r)["errors"] == {"pages": "must be positive"}
    r = await client.post(
        "/book",
        {"title": "New", "pages": "12", "genre": "fantasy", "author": {"id": 1}, "tags": ""},
    )
    assert r.status == 201, body(r)
    data = body(r)
    assert data["id"] == 5 and data["pages"] == 12 and data["author"]["label"] == "Ursula Le Guin"
    assert data["tags"] == []
    r = await client.post("/author", {"name": "x" * 51})
    assert body(r)["errors"]["name"].startswith("Ensure this value has at most 50")
    r = await client.post("/author", {"name": "New", "born": "2000-01-02", "active": "false"})
    assert r.status == 201
    assert body(r)["born"] == "2000-01-02" and body(r)["active"] is False
    r = await client.post("/author", {"name": "Null", "born": None})
    assert r.status == 201 and body(r)["born"] is None
    r = await client.post("/author", {"name": "x", "active": None})
    assert r.status == 201  # has_default -> omitted


async def test_export_csv_and_json(client: Client) -> None:
    r = await client.get("/book/export", sort="id")
    assert r.status == 200 and r.media_type.startswith("text/csv")
    lines = r.body.decode().splitlines()
    assert lines[0] == "id,title,author"
    assert lines[1] == "1,The Dispossessed,Ursula Le Guin"
    assert len(lines) == 5  # export ignores page_size
    r = await client.get("/book/export", format="json")
    assert body(r)[0].keys() == {"id", "title", "author"}


async def test_permissions(site: AdminSite) -> None:
    class LockedAdmin(ModelAdmin):
        can_create = False

        async def has_delete_permission(self, request: Any, obj: Any = None) -> bool:
            return obj is None or obj["id"] != 1

    locked = AdminSite("T", backend=make_backend())
    locked.register(Book, LockedAdmin)
    c = Client(locked)
    assert (await c.post("/book", {"title": "x"})).status == 403
    assert (await c.delete("/book/1")).status == 403
    assert (await c.delete("/book/2")).status == 200
    assert body(await c.get("/book/schema"))["permissions"]["create"] is False


async def test_auth_flow() -> None:
    site = AdminSite("T", backend=make_backend(), auth=SimpleAuth("secret", {"admin": "pw"}))
    site.register(Author, AuthorAdmin)
    c = Client(site)
    assert (await c.get("/site")).status == 401
    assert (await c.post("/auth/login", {"username": "admin", "password": "bad"})).status == 401
    r = await c.post("/auth/login", {"username": "admin", "password": "pw"})
    assert r.status == 200 and "atlas_session" in c.cookies
    assert body(await c.get("/site"))["user"]["username"] == "admin"
    assert body(await c.get("/auth/me"))["user"]["username"] == "admin"
    token = r.headers["x-atlas-token"]
    bearer = Client(site)
    bearer.headers["authorization"] = f"Bearer {token}"
    assert (await bearer.get("/author")).status == 200
    assert (await c.post("/auth/logout")).status == 204
    assert "atlas_session" not in c.cookies
    assert (await c.get("/site")).status == 401
    c.cookies["atlas_session"] = "garbage.sig"
    assert (await c.get("/site")).status == 401


def test_registration_errors() -> None:
    site = AdminSite("T", backend=make_backend())
    site.register(Book, BookAdmin)
    with pytest.raises(ValueError, match="already registered"):
        site.register(Book, BookAdmin)

    class Bad(ModelAdmin):
        list_display = ["nope"]

    site2 = AdminSite("T", backend=make_backend())
    site2.register(Book, Bad)
    with pytest.raises(ValueError, match="unknown fields"):
        _ = site2.resource("book").schema

    with pytest.raises(TypeError, match="async def"):

        class _Bad(ModelAdmin):
            @action()
            def sync_action(self, request: Any, objs: Any) -> None: ...


def test_decorator_registration() -> None:
    site = AdminSite("T", backend=make_backend())

    @site.register(Author, key="writers")
    class _A(ModelAdmin):
        label = "Writer"

    assert "writers" in site.resources
    assert site.resource("writers").schema.label == "Writer"
