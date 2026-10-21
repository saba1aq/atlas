"""Starlette / FastAPI transport.

    from atlas.transports.starlette import mount
    mount(app, site, path="/admin")

The admin is an ASGI sub-application: ``/_api/...`` goes to ``AdminSite.dispatch``, everything
else serves the built single-page UI (or a placeholder page if the UI bundle is not installed).
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from starlette.applications import Starlette
from starlette.requests import Request
from starlette.responses import HTMLResponse, JSONResponse, Response
from starlette.routing import Mount, Route
from starlette.staticfiles import StaticFiles

from atlas.core.http import AdminRequest, AdminResponse
from atlas.core.site import AdminSite

STATIC_DIR = Path(__file__).resolve().parent.parent / "static"
API_PREFIX = "/_api"

_PLACEHOLDER = """<!doctype html><html><head><meta charset="utf-8"><title>{title}</title>
<style>
body {{ font: 16px/1.5 system-ui; margin: 4rem auto; max-width: 40rem; color: #222 }}
code {{ background: #eee; padding: .1em .3em }}
</style></head><body><h1>{title}</h1>
<p>The Atlas Admin UI bundle is not installed in this package build, but the JSON API is live.</p>
<ul>
<li><code>GET {api}/site</code></li>
<li><code>GET {api}/&lt;resource&gt;/schema</code></li>
<li><code>GET {api}/&lt;resource&gt;?limit=25&amp;offset=0&amp;sort=-id&amp;search=</code></li>
</ul>
<p>Build the UI with <code>pnpm --dir ui build</code> or install a release wheel.</p>
</body></html>"""


async def to_admin_request(request: Request, path: str) -> AdminRequest:
    query: dict[str, list[str]] = {}
    for k, v in request.query_params.multi_items():
        query.setdefault(k, []).append(v)
    body = await request.body()
    return AdminRequest(
        method=request.method,
        path="/" + path.strip("/"),
        query=query,
        headers={k.lower(): v for k, v in request.headers.items()},
        cookies=dict(request.cookies),
        body=body,
        state={"starlette_request": request},
    )


def to_starlette_response(resp: AdminResponse) -> Response:
    out = Response(content=resp.body, status_code=resp.status, media_type=resp.media_type)
    for k, v in resp.headers.items():
        out.headers[k] = v
    for c in resp.cookies:
        if c.max_age == 0:
            out.delete_cookie(c.name, path=c.path)
        else:
            out.set_cookie(
                c.name,
                c.value,
                max_age=c.max_age,
                path=c.path,
                httponly=c.http_only,
                samesite=c.same_site,  # type: ignore[arg-type]
                secure=c.secure,
            )
    return out


def create_app(site: AdminSite, *, static_dir: Path | str | None = None) -> Starlette:
    """Build the admin ASGI sub-application. Mount it under any prefix."""
    static = Path(static_dir) if static_dir else STATIC_DIR
    index_file = static / "index.html"
    index_html = index_file.read_text(encoding="utf-8") if index_file.exists() else None

    async def api(request: Request) -> Response:
        admin_req = await to_admin_request(request, request.path_params.get("path", ""))
        return to_starlette_response(await site.dispatch(admin_req))

    async def api_root(request: Request) -> Response:
        return JSONResponse({"error": "not found"}, status_code=404)

    async def index(request: Request) -> Response:
        base = request.scope.get("root_path", "").rstrip("/")
        config = {"basePath": base, "apiPath": f"{base}{API_PREFIX}", "title": site.title}
        if index_html is None:
            return HTMLResponse(_PLACEHOLDER.format(title=site.title, api=config["apiPath"]))
        html = (
            index_html.replace("__ATLAS_CONFIG__", json.dumps(config))
            .replace("/__ATLAS_BASE__/", "__ATLAS_BASE__/")  # vite prefixes base with "/"
            .replace("__ATLAS_BASE__/", f"{base}/")
        )
        return HTMLResponse(html, headers={"cache-control": "no-store"})

    routes: list[Any] = [
        Route(
            f"{API_PREFIX}/{{path:path}}", api, methods=["GET", "POST", "PUT", "PATCH", "DELETE"]
        ),
        Route(API_PREFIX, api_root),
    ]
    assets = static / "assets"
    if assets.is_dir():
        routes.append(Mount("/assets", StaticFiles(directory=assets), name="atlas-assets"))
    routes.append(Route("/{path:path}", index, methods=["GET"]))
    routes.append(Route("/", index, methods=["GET"]))
    return Starlette(routes=routes)


def mount(app: Any, site: AdminSite, path: str = "/admin", **kwargs: Any) -> Starlette:
    """Mount the admin onto a Starlette or FastAPI application at ``path``."""
    admin_app = create_app(site, **kwargs)
    app.mount(path.rstrip("/") or "/", admin_app, name="atlas")
    return admin_app


__all__ = ["create_app", "mount", "to_admin_request", "to_starlette_response"]
