from __future__ import annotations

from collections.abc import AsyncIterator
from pathlib import Path

import httpx
import pytest
from fastapi import FastAPI

from atlas import AdminSite, SimpleAuth
from atlas.transports.starlette import mount
from tests.contract import AuthorAdminBase as AuthorAdmin
from tests.test_memory import Author, Book, make_backend
from tests.test_memory import MemoryBookAdmin as BookAdmin


@pytest.fixture
async def client(tmp_path: Path) -> AsyncIterator[httpx.AsyncClient]:
    static = tmp_path / "static"
    (static / "assets").mkdir(parents=True)
    (static / "assets" / "app.js").write_text("console.log('ok')")
    (static / "index.html").write_text(
        "<html><head><script>window.__ATLAS__=__ATLAS_CONFIG__</script>"
        '<script src="/__ATLAS_BASE__/assets/app.js"></script></head></html>'
    )
    site = AdminSite("My Admin", backend=make_backend(), auth=SimpleAuth("s3cret", {"root": "pw"}))
    site.register(Author, AuthorAdmin)
    site.register(Book, BookAdmin)
    app = FastAPI()
    mount(app, site, path="/admin", static_dir=static)
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app), base_url="http://test"
    ) as c:
        yield c


async def test_index_injects_config(client: httpx.AsyncClient) -> None:
    r = await client.get("/admin/")
    assert r.status_code == 200
    assert '"basePath": "/admin"' in r.text and '"apiPath": "/admin/_api"' in r.text
    assert 'src="/admin/assets/app.js"' in r.text
    r = await client.get("/admin/book/1")  # SPA deep link
    assert r.status_code == 200 and "__ATLAS__" in r.text
    r = await client.get("/admin/assets/app.js")
    assert r.status_code == 200 and "console.log" in r.text


async def test_api_roundtrip_with_cookies(client: httpx.AsyncClient) -> None:
    r = await client.get("/admin/_api/site")
    assert r.status_code == 401
    r = await client.post("/admin/_api/auth/login", json={"username": "root", "password": "pw"})
    assert r.status_code == 200 and "atlas_session" in r.cookies
    r = await client.get("/admin/_api/site")
    assert r.status_code == 200 and r.json()["user"]["username"] == "root"
    r = await client.get(
        "/admin/_api/book",
        params={
            "sort": "-pages",
            "limit": 1,
            "filters": '[{"field":"genre","op":"eq","value":"sf"}]',
        },
    )
    assert r.json()["total"] == 3 and r.json()["items"][0]["title"] == "Ancillary Justice"
    r = await client.patch("/admin/_api/book/1", json={"pages": 1})
    assert r.status_code == 200 and r.json()["pages"] == 1
    r = await client.request("DELETE", "/admin/_api/book", json={"pks": [4]})
    assert r.status_code == 200 and r.json() == {"deleted": 1}
    r = await client.get("/admin/_api/book/export", params={"format": "csv"})
    assert r.headers["content-type"].startswith("text/csv")
    assert r.headers["content-disposition"].endswith('"book.csv"')
    r = await client.post("/admin/_api/auth/logout")
    assert r.status_code == 204 and "atlas_session" not in r.cookies
    assert (await client.get("/admin/_api/site")).status_code == 401
    assert (await client.get("/admin/_api/nope/x/y")).status_code == 404


async def test_placeholder_when_ui_missing(tmp_path: Path) -> None:
    site = AdminSite("Bare", backend=make_backend())
    site.register(Author, AuthorAdmin)
    app = FastAPI()
    mount(app, site, path="/panel", static_dir=tmp_path / "missing")
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://t") as c:
        r = await c.get("/panel/")
        assert r.status_code == 200 and "JSON API is live" in r.text and "/panel/_api" in r.text
        assert (await c.get("/panel/_api/site")).json()["title"] == "Bare"
        assert (await c.get("/panel/_api")).status_code == 404
