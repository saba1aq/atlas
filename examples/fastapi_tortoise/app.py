"""FastAPI + Tortoise ORM (SQLite) example.

uv run uvicorn examples.fastapi_tortoise.app:app --reload
open http://127.0.0.1:8000/admin  (login: admin / admin)
"""

from __future__ import annotations

import enum
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI
from tortoise import Tortoise, fields
from tortoise.models import Model

from atlas import AdminSite, ModelAdmin, SimpleAuth
from atlas.backends.tortoise import TortoiseBackend
from atlas.transports.starlette import mount

DB_PATH = Path(__file__).with_name("example.db")


class Priority(enum.IntEnum):
    low = 1
    medium = 2
    high = 3


class Project(Model):
    id = fields.IntField(primary_key=True)
    name = fields.CharField(max_length=80)
    created_at = fields.DatetimeField(auto_now_add=True)

    def __str__(self) -> str:
        return self.name


class Task(Model):
    id = fields.IntField(primary_key=True)
    title = fields.CharField(max_length=200, description="Short summary")
    done = fields.BooleanField(default=False)
    priority = fields.IntEnumField(Priority, default=Priority.medium)
    due = fields.DateField(null=True)
    notes = fields.TextField(null=True)
    project: fields.ForeignKeyNullableRelation[Project] = fields.ForeignKeyField(
        "models.Project", related_name="tasks", null=True
    )
    watchers: fields.ManyToManyRelation[Project] = fields.ManyToManyField(
        "models.Project", related_name="watched_tasks"
    )


async def seed() -> None:
    if await Project.all().count():
        return
    core = await Project.create(name="Core")
    docs = await Project.create(name="Docs")
    for i in range(1, 21):
        t = await Task.create(
            title=f"Task {i}",
            done=i % 4 == 0,
            priority=list(Priority)[i % 3],
            project=core if i % 2 else docs,
        )
        if i % 5 == 0:
            await t.watchers.add(core, docs)


@asynccontextmanager
async def lifespan(app: FastAPI):  # type: ignore[no-untyped-def]
    await Tortoise.init(db_url=f"sqlite://{DB_PATH}", modules={"models": [__name__]})
    await Tortoise.generate_schemas()
    await seed()
    yield
    await Tortoise.close_connections()


site = AdminSite(
    "Tasks Admin",
    backend=TortoiseBackend(),
    auth=SimpleAuth("change-me-in-production", {"admin": "admin"}),
)


@site.register(Project)
class ProjectAdmin(ModelAdmin):
    search_fields = ["name"]


@site.register(Task)
class TaskAdmin(ModelAdmin):
    list_display = ["id", "title", "done", "priority", "project", "due"]
    search_fields = ["title", "notes"]
    ordering = ["-id"]


app = FastAPI(lifespan=lifespan)
mount(app, site, path="/admin")
