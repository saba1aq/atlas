"""FastAPI + Beanie ODM.

docker run -d --rm -p 27017:27017 --name mongo mongo:7
uv run uvicorn examples.fastapi_beanie.app:app --reload
open http://127.0.0.1:8000/admin  (login: admin / admin)
"""

from __future__ import annotations

import datetime as dt
import os
from contextlib import asynccontextmanager
from typing import Any

from beanie import Document, Link, init_beanie
from fastapi import FastAPI
from pydantic import Field
from pymongo import AsyncMongoClient

from atlas import AdminSite, ModelAdmin, SimpleAuth
from atlas.backends.beanie import BeanieBackend
from atlas.transports.starlette import mount

MONGO_URL = os.environ.get("MONGO_URL", "mongodb://127.0.0.1:27017")


class Category(Document):
    name: str = Field(max_length=60)

    class Settings:
        name = "categories"


class Product(Document):
    title: str = Field(max_length=120)
    price: float = 0
    in_stock: bool = True
    category: Link[Category] | None = None
    related: list[Link[Product]] = []
    created_at: dt.datetime = Field(default_factory=dt.datetime.utcnow)

    class Settings:
        name = "products"


async def seed() -> None:
    if await Category.count():
        return
    cats = [await Category(name=n).insert() for n in ("Books", "Games", "Music")]
    prev: Product | None = None
    for i in range(1, 31):
        p = await Product(
            title=f"Product {i}",
            price=i * 3.5,
            in_stock=i % 4 != 0,
            category=cats[i % 3],
            related=[prev] if prev else [],
        ).insert()
        prev = p


site = AdminSite(
    "Catalog Admin", backend=BeanieBackend(), auth=SimpleAuth("change-me", {"admin": "admin"})
)


@site.register(Category)
class CategoryAdmin(ModelAdmin):
    search_fields = ["name"]


@site.register(Product)
class ProductAdmin(ModelAdmin):
    list_display = ["id", "title", "price", "in_stock", "category"]
    list_filter = ["in_stock", "category", "price"]
    search_fields = ["title"]
    ordering = ["-created_at"]


@asynccontextmanager
async def lifespan(app: FastAPI):  # type: ignore[no-untyped-def]
    client: AsyncMongoClient[Any] = AsyncMongoClient(MONGO_URL)
    await init_beanie(database=client["atlas_beanie_example"], document_models=[Category, Product])
    await seed()
    yield
    await client.close()


app = FastAPI(lifespan=lifespan)
mount(app, site, path="/admin")
