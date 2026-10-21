from __future__ import annotations

import json
from typing import Any

import pytest

from atlas.core.http import AdminRequest, AdminResponse


class Client:
    """Drive ``AdminSite.dispatch`` directly, without a web framework."""

    def __init__(self, site: Any) -> None:
        self.site = site
        self.cookies: dict[str, str] = {}
        self.headers: dict[str, str] = {}

    async def request(
        self,
        method: str,
        path: str,
        *,
        query: dict[str, str] | None = None,
        json_body: Any = None,
    ) -> AdminResponse:
        req = AdminRequest(
            method=method,
            path=path,
            query={k: [v] for k, v in (query or {}).items()},
            headers=dict(self.headers),
            cookies=dict(self.cookies),
            body=json.dumps(json_body).encode() if json_body is not None else b"",
        )
        resp = await self.site.dispatch(req)
        for c in resp.cookies:
            if c.max_age == 0:
                self.cookies.pop(c.name, None)
            else:
                self.cookies[c.name] = c.value
        return resp

    async def get(self, path: str, **query: str) -> AdminResponse:
        return await self.request("GET", path, query=query)

    async def post(self, path: str, json_body: Any = None) -> AdminResponse:
        return await self.request("POST", path, json_body=json_body)

    async def patch(self, path: str, json_body: Any = None) -> AdminResponse:
        return await self.request("PATCH", path, json_body=json_body)

    async def delete(self, path: str, json_body: Any = None) -> AdminResponse:
        return await self.request("DELETE", path, json_body=json_body)


def body(resp: AdminResponse) -> Any:
    return json.loads(resp.body) if resp.body else None


@pytest.fixture
def client_factory() -> Any:
    return Client
