"""Backend-agnostic scenarios. Every backend test module subclasses ``ContractTests`` and
provides a ``site`` fixture with the standard dataset:

Authors: 1 Ursula Le Guin (1929-10-21, inactive), 2 Ted Chiang (1967-01-01), 3 Ann Leckie (born NULL)
Books:   1 The Dispossessed 341p sf author=1 tags=[1,2]
         2 Exhalation 350p sf author=2 tags=[]
         3 Ancillary Justice 416p sf author=3 tags=[3]
         4 A Wizard of Earthsea 183p fantasy author=1 tags=[]

Admins: AuthorAdmin(search_fields=[name], ordering=[name]);
        BookAdmin(list_display=[id,title,author], ordering=[-pages], page_size=2, action make_classic,
        validate pages >= 0).
"""

from __future__ import annotations

from typing import Any

import pytest

from atlas import ModelAdmin, ValidationError, action
from tests.conftest import Client, body


class AuthorAdminBase(ModelAdmin):
    search_fields = ["name"]
    ordering = ["name"]


class BookAdminBase(ModelAdmin):
    list_display = ["id", "title", "author"]
    ordering = ["-pages"]
    page_size = 2

    @action("Mark as classic", confirm="Really?")
    async def make_classic(self, request: Any, objs: list[Any]) -> str:
        repo = self.site.resource("book").repository
        for o in objs:
            title = o["title"] if isinstance(o, dict) else o.title
            await repo.update(o, {"title": f"{title} (classic)"})
        return f"{len(objs)} marked"

    async def validate(self, request: Any, data: dict[str, Any], obj: Any = None) -> None:
        if data.get("pages") is not None and data["pages"] < 0:
            raise ValidationError({"pages": "must be positive"})


class ContractTests:
    @pytest.fixture
    def client(self, site: Any) -> Client:
        return Client(site)

    async def test_site_lists_resources(self, client: Client) -> None:
        data = body(await client.get("/site"))
        assert [x["key"] for x in data["resources"]] == ["author", "book"]

    async def test_schema(self, client: Client) -> None:
        data = body(await client.get("/book/schema"))
        fields = {f["name"]: f for f in data["fields"]}
        assert data["pk_field"] == "id"
        assert fields["id"]["primary_key"] and fields["id"]["read_only"]
        assert fields["title"]["type"] == "string" and fields["title"]["required"]
        assert fields["pages"]["type"] == "integer" and fields["pages"]["nullable"]
        assert fields["genre"]["type"] == "enum"
        assert {c["value"] for c in fields["genre"]["choices"]} == {"sf", "fantasy"}
        assert fields["author"]["relation"] == {"resource": "author", "kind": "many_to_one"}
        assert fields["tags"]["relation"] == {"resource": "author", "kind": "many_to_many"}
        assert fields["created_at"]["type"] == "datetime"
        assert "author_id" not in fields
        author = {f["name"]: f for f in body(await client.get("/author/schema"))["fields"]}
        if "books" in author:  # backends without reverse relations skip this
            assert author["books"]["type"] == "one_to_many" and not author["books"]["in_form"]
        assert author["born"]["type"] == "date" and author["active"]["type"] == "boolean"
        assert author["name"]["max_length"] == 50

    async def test_list_default_ordering_and_pagination(self, client: Client) -> None:
        data = body(await client.get("/book"))
        assert data["total"] == 4
        assert [b["title"] for b in data["items"]] == ["Ancillary Justice", "Exhalation"]
        assert data["items"][0]["author"] == {"id": 3, "label": "Ann Leckie"}
        page2 = body(await client.get("/book", offset="2", limit="2"))
        assert [b["id"] for b in page2["items"]] == [1, 4]

    async def test_list_sort_search_filters(self, client: Client) -> None:
        data = body(await client.get("/book", sort="title"))
        assert data["items"][0]["title"] == "A Wizard of Earthsea"
        data = body(await client.get("/book", sort="-title,id", limit="10"))
        assert data["items"][0]["title"] == "The Dispossessed"
        data = body(await client.get("/author", search="le"))
        assert [a["name"] for a in data["items"]] == ["Ann Leckie", "Ursula Le Guin"]
        data = body(await client.get("/book", search="EXHAL", limit="10"))
        assert [b["id"] for b in data["items"]] == [2]

        assert await self._ids(
            client,
            '{"and": [{"field": "genre", "op": "eq", "value": "sf"}, {"field": "pages", "op": "gt", "value": 345}]}',
        ) == [2, 3]
        assert await self._ids(
            client,
            '{"or": [{"field": "genre", "op": "eq", "value": "fantasy"}, {"field": "author", "op": "in", "value": [2]}]}',
        ) == [2, 4]
        assert await self._ids(client, '[{"field": "author", "op": "eq", "value": 1}]') == [1, 4]
        assert await self._ids(client, '[{"field": "tags", "op": "in", "value": [2, 3]}]') == [1, 3]
        assert await self._ids(
            client, '[{"field": "title", "op": "icontains", "value": "ANC"}]'
        ) == [3]
        assert await self._ids(
            client, '[{"field": "title", "op": "startswith", "value": "The"}]'
        ) == [1]
        assert await self._ids(
            client, '[{"field": "pages", "op": "between", "value": [300, 360]}]'
        ) == [1, 2]
        assert await self._ids(
            client, '[{"field": "pages", "op": "not_in", "value": [341, 350]}]'
        ) == [3, 4]
        assert await self._ids(client, '[{"field": "genre", "op": "ne", "value": "sf"}]') == [4]
        data = body(
            await client.get(
                "/author", filters='[{"field": "born", "op": "is_null", "value": true}]'
            )
        )
        assert [a["id"] for a in data["items"]] == [3]
        data = body(
            await client.get(
                "/author", filters='[{"field": "born", "op": "lt", "value": "1950-01-01"}]'
            )
        )
        assert [a["id"] for a in data["items"]] == [1]
        data = body(
            await client.get("/author", filters='[{"field": "active", "op": "eq", "value": true}]')
        )
        assert [a["id"] for a in data["items"]] == [3, 2]

    async def _ids(self, client: Client, expr: str) -> list[int]:
        return sorted(
            b["id"] for b in body(await client.get("/book", filters=expr, limit="10"))["items"]
        )

    async def test_get_update_delete(self, client: Client) -> None:
        data = body(await client.get("/book/1"))
        assert data["title"] == "The Dispossessed"
        assert data["author"] == {"id": 1, "label": "Ursula Le Guin"}
        assert [t["id"] for t in data["tags"]] == [1, 2]
        assert (await client.get("/book/999")).status == 404
        assert (await client.get("/book/abc")).status in (400, 404)
        r = await client.patch("/book/1", {"pages": 400, "author": 2, "tags": [1, 3], "id": 77})
        assert r.status == 200, body(r)
        data = body(r)
        assert data["id"] == 1 and data["pages"] == 400
        assert data["author"]["id"] == 2 and sorted(t["id"] for t in data["tags"]) == [1, 3]
        r = await client.patch("/book/1", {"author": None, "tags": []})
        assert r.status == 200 and body(r)["author"] is None and body(r)["tags"] == []
        r = await client.patch("/book/1", {"tags": [999]})
        assert r.status == 422
        r = await client.delete("/book/1")
        assert body(r) == {"deleted": 1}
        assert (await client.get("/book/1")).status == 404
        r = await client.delete("/book", {"pks": [2, 3]})
        assert body(r) == {"deleted": 2}
        assert body(await client.get("/book"))["total"] == 1
        assert (await client.delete("/book", {"pks": [999]})).status == 404

    async def test_create(self, client: Client) -> None:
        r = await client.post("/book", {"pages": "12"})
        assert r.status == 422 and body(r)["errors"] == {"title": "This field is required."}
        r = await client.post("/book", {"title": "X", "pages": "abc", "genre": "horror"})
        assert r.status == 422 and set(body(r)["errors"]) == {"pages", "genre"}
        r = await client.post("/book", {"title": "X", "pages": -1})
        assert r.status == 422 and body(r)["errors"] == {"pages": "must be positive"}
        r = await client.post(
            "/book",
            {"title": "New", "pages": "12", "genre": "fantasy", "author": {"id": 1}, "tags": [2]},
        )
        assert r.status == 201, body(r)
        data = body(r)
        assert data["id"] == 5 and data["pages"] == 12 and data["genre"] == "fantasy"
        assert data["author"]["label"] == "Ursula Le Guin"
        assert [t["label"] for t in data["tags"]] == ["Ted Chiang"]
        assert data["created_at"]
        r = await client.post("/author", {"name": "x" * 51})
        assert r.status == 422 and "50" in body(r)["errors"]["name"]
        r = await client.post("/author", {"name": "New", "born": "2000-01-02", "active": "false"})
        assert r.status == 201 and body(r)["born"] == "2000-01-02" and body(r)["active"] is False
        r = await client.post("/author", {"name": "Default"})
        assert r.status == 201 and body(r)["active"] is True

    async def test_options_autocomplete(self, client: Client) -> None:
        data = body(await client.get("/author/options", q="leck"))
        assert [o["label"] for o in data["items"]] == ["Ann Leckie"]
        data = body(await client.get("/author/options", ids="2,1"))
        assert sorted(o["value"] for o in data["items"]) == [1, 2]

    async def test_actions(self, client: Client) -> None:
        r = await client.post("/book/actions/make_classic", {"pks": [1, 2]})
        assert body(r) == {"message": "2 marked"}
        assert body(await client.get("/book/1"))["title"].endswith("(classic)")

    async def test_export(self, client: Client) -> None:
        r = await client.get("/book/export", sort="id")
        lines = r.body.decode().splitlines()
        assert lines[0] == "id,title,author"
        assert lines[1] == "1,The Dispossessed,Ursula Le Guin"
        assert len(lines) == 5
