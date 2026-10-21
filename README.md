# Atlas Admin

Framework‑agnostic admin panel for Python: a headless core with a JSON API, pluggable data
backends (SQLAlchemy sync/async, Tortoise ORM, MongoDB via PyMongo/Motor, Beanie ODM) and thin
transports (Starlette/FastAPI today; Flask and Django next). Ships with a built‑in React UI, no
Node required at install time.

> Status: pre‑alpha. API may change.

## Quickstart (FastAPI + SQLAlchemy)

```bash
uv add "atlas[fastapi,sqlalchemy]"
```

```python
from fastapi import FastAPI
from sqlalchemy.ext.asyncio import create_async_engine

from atlas import AdminSite, ModelAdmin, SimpleAuth, action
from atlas.backends.sqlalchemy import SQLAlchemyBackend
from atlas.transports.starlette import mount

engine = create_async_engine("sqlite+aiosqlite:///app.db")
site = AdminSite("My Admin", backend=SQLAlchemyBackend(engine),
                 auth=SimpleAuth("change-me", {"admin": "admin"}))

@site.register(Post)
class PostAdmin(ModelAdmin):
    list_display = ["id", "title", "status", "author"]
    list_filter = ["status", "author", "tags"]
    search_fields = ["title", "body"]
    ordering = ["-id"]

    @action("Publish", confirm="Publish selected posts?")
    async def publish(self, request, objs):
        repo = self.site.resource("post").repository
        for post in objs:
            await repo.update(post, {"status": "published"})
        return f"Published {len(objs)} post(s)"

app = FastAPI()
mount(app, site, path="/admin")
```

## Backends

| Backend | Install | Usage |
|---|---|---|
| SQLAlchemy 2.x, sync or async | `atlas[sqlalchemy]` | `SQLAlchemyBackend(engine_or_sessionmaker)` |
| Tortoise ORM | `atlas[tortoise]` | `TortoiseBackend()`; run `Tortoise.init()` in your lifespan |
| MongoDB (PyMongo sync, PyMongo async, Motor) | `atlas[mongo]` | `MongoBackend(client["db"])`, models are Pydantic classes |
| Beanie ODM | `atlas[beanie]` | `BeanieBackend()`; run `init_beanie()` in your lifespan |

MongoDB models are plain Pydantic classes; references are declared with `Ref`:

```python
from typing import Annotated
from atlas.backends.mongo import MongoBackend, Ref

class Order(BaseModel):
    id: str                                              # maps to _id (ObjectId hex, int or str)
    number: str = Field(max_length=20)
    customer: Annotated[str | None, Ref(Customer)] = None   # many_to_one
    tags: Annotated[list[str], Ref(Tag)] = []                # many_to_many
```

With Beanie, `Link[T]`, `list[Link[T]]` and `BackLink[T]` are picked up automatically and links are
stored as DBRefs, so documents written by the admin load through Beanie unchanged.

Runnable examples live in `examples/`:

```bash
uv run uvicorn examples.fastapi_sqlalchemy.app:app --reload        # async SQLAlchemy + SQLite
uv run uvicorn examples.fastapi_sqlalchemy_sync.app:app --reload   # sync engine
uv run uvicorn examples.fastapi_tortoise.app:app --reload
docker run -d --rm -p 27017:27017 --name mongo mongo:7
uv run uvicorn examples.fastapi_mongo.app:app --reload             # PyMongo async
uv run uvicorn examples.fastapi_beanie.app:app --reload
# open http://127.0.0.1:8000/admin  (admin / admin)
```

## Architecture

```
transports/   Starlette ──┐
              Flask   (planned)  ──►  core/ (AdminSite, ModelAdmin, schema, filters, auth)
              Django  (planned)  ──┘        ▲
                                            │ Repository / Backend protocols
backends/     sqlalchemy, tortoise, mongo, beanie, memory ─┘
ui/           React SPA, built into src/atlas/static
```

* **core** never imports a web framework or an ORM. It exposes `AdminSite.dispatch(AdminRequest)`.
* **backends** implement `Backend.introspect(model)` → `ModelSchema` and the async `Repository`
  contract (`list`, `count`, `get`, `get_many`, `create`, `update`, `delete`, `to_dict`).
* **transports** map framework requests to `AdminRequest` and serve the UI.

### JSON API

| Method | Path | |
|---|---|---|
| GET | `/_api/site` | resources, current user |
| POST/GET | `/_api/auth/login`, `/_api/auth/logout`, `/_api/auth/me` | session auth |
| GET | `/_api/{resource}/schema` | fields, actions, permissions |
| GET | `/_api/{resource}?offset&limit&sort=-id,name&search=&filters=<json>` | list |
| POST / GET / PATCH / DELETE | `/_api/{resource}`, `/_api/{resource}/{pk}` | CRUD |
| DELETE | `/_api/{resource}` body `{"pks": [...]}` | bulk delete |
| POST | `/_api/{resource}/actions/{name}` body `{"pks": [...]}` | custom action |
| GET | `/_api/{resource}/options?q=` | autocomplete for relations |
| GET | `/_api/{resource}/export?format=csv\|json` | export current view |

Filter tree: `{"and": [{"field": "age", "op": "gte", "value": 18}, {"or": [...]}]}` with ops
`eq ne lt lte gt gte in not_in contains icontains startswith endswith is_null between`.

## Development

```bash
uv sync --all-extras          # python deps
uv run pytest                 # core + backend contract tests + transport tests
docker run -d --rm -p 27017:27017 mongo:7   # Mongo/Beanie tests skip when no server is reachable
uv run ruff check src tests
pnpm --dir ui install && pnpm --dir ui build   # rebuilds src/atlas/static
pnpm --dir ui dev             # UI dev server, proxies /admin/_api to :8000
```

See `docs/PLAN.md` for the roadmap.
