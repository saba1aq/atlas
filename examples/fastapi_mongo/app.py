"""FastAPI + MongoDB via pymongo's async client (raw collections, Pydantic models).

    docker run -d --rm -p 27017:27017 --name mongo mongo:7
    uv run uvicorn examples.fastapi_mongo.app:app --reload
    open http://127.0.0.1:8000/admin  (login: admin / admin)

Swap ``AsyncMongoClient`` for ``MongoClient`` (sync) or ``AsyncIOMotorClient`` (Motor): the
backend handles all three the same way.
"""

from __future__ import annotations

import datetime as dt
import enum
import os
from contextlib import asynccontextmanager
from typing import Annotated, Any

from fastapi import FastAPI
from pydantic import BaseModel, Field
from pymongo import AsyncMongoClient

from atlas import AdminSite, ModelAdmin, SimpleAuth
from atlas.backends.mongo import MongoBackend, Ref
from atlas.transports.starlette import mount

MONGO_URL = os.environ.get("MONGO_URL", "mongodb://127.0.0.1:27017")
client: AsyncMongoClient[Any] = AsyncMongoClient(MONGO_URL)
db = client["atlas_example"]


class Customer(BaseModel):
    id: str  # ObjectId as hex string
    name: str = Field(max_length=80)
    email: str
    vip: bool = False


class Status(enum.StrEnum):
    new = "new"
    paid = "paid"
    shipped = "shipped"


class Order(BaseModel):
    id: str
    number: str = Field(max_length=20, description="Human-readable order number")
    status: Status = Status.new
    total: float = 0
    items: list[dict[str, Any]] = []
    customer: Annotated[str | None, Ref(Customer)] = None
    created_at: dt.datetime = Field(default_factory=dt.datetime.utcnow)


async def seed() -> None:
    if await db["customer"].count_documents({}):
        return
    res = await db["customer"].insert_many(
        [
            {"name": f"Customer {i}", "email": f"c{i}@example.com", "vip": i % 3 == 0}
            for i in range(1, 11)
        ]
    )
    ids = res.inserted_ids
    await db["order"].insert_many(
        [
            {
                "number": f"ORD-{i:04d}",
                "status": list(Status)[i % 3].value,
                "total": round(i * 12.5, 2),
                "items": [{"sku": f"SKU{i}", "qty": i % 4 + 1}],
                "customer": ids[i % len(ids)],
                "created_at": dt.datetime(2024, 1, 1) + dt.timedelta(hours=i),
            }
            for i in range(1, 41)
        ]
    )


site = AdminSite(
    "Shop Admin", backend=MongoBackend(db), auth=SimpleAuth("change-me", {"admin": "admin"})
)


@site.register(Customer)
class CustomerAdmin(ModelAdmin):
    search_fields = ["name", "email"]
    ordering = ["name"]


@site.register(Order)
class OrderAdmin(ModelAdmin):
    list_display = ["id", "number", "status", "total", "customer", "created_at"]
    list_filter = ["status", "customer", "total", "created_at"]
    search_fields = ["number"]
    ordering = ["-created_at"]


@asynccontextmanager
async def lifespan(app: FastAPI):  # type: ignore[no-untyped-def]
    await seed()
    yield
    await client.close()


app = FastAPI(lifespan=lifespan)
mount(app, site, path="/admin")
