"""FastAPI + SQLAlchemy with a *synchronous* engine (psycopg2, pysqlite, mysqlclient...).

The backend runs sync sessions in a worker thread, so the event loop is never blocked.

    uv run uvicorn examples.fastapi_sqlalchemy_sync.app:app --reload
"""

from __future__ import annotations

import datetime as dt
from pathlib import Path

import sqlalchemy as sa
from fastapi import FastAPI
from sqlalchemy.orm import DeclarativeBase, Mapped, Session, mapped_column, relationship

from atlas import AdminSite, ModelAdmin, SimpleAuth
from atlas.backends.sqlalchemy import SQLAlchemyBackend
from atlas.transports.starlette import mount

engine = sa.create_engine(f"sqlite:///{Path(__file__).with_name('example.db')}")


class Base(DeclarativeBase):
    pass


class Department(Base):
    __tablename__ = "departments"
    id: Mapped[int] = mapped_column(primary_key=True)
    name: Mapped[str] = mapped_column(sa.String(60))
    employees: Mapped[list[Employee]] = relationship(back_populates="department")

    def __str__(self) -> str:
        return self.name


class Employee(Base):
    __tablename__ = "employees"
    id: Mapped[int] = mapped_column(primary_key=True)
    name: Mapped[str] = mapped_column(sa.String(80))
    hired: Mapped[dt.date | None]
    salary: Mapped[int | None]
    department_id: Mapped[int | None] = mapped_column(sa.ForeignKey("departments.id"))
    department: Mapped[Department | None] = relationship(back_populates="employees")


def seed() -> None:
    Base.metadata.create_all(engine)
    with Session(engine) as s:
        if s.scalar(sa.select(sa.func.count()).select_from(Department)):
            return
        eng, ops = Department(name="Engineering"), Department(name="Operations")
        s.add_all([eng, ops])
        for i in range(1, 26):
            s.add(
                Employee(
                    name=f"Employee {i}",
                    hired=dt.date(2020, 1, 1) + dt.timedelta(days=30 * i),
                    salary=3000 + i * 100,
                    department=eng if i % 2 else ops,
                )
            )
        s.commit()


seed()
site = AdminSite(
    "HR Admin", backend=SQLAlchemyBackend(engine), auth=SimpleAuth("change-me", {"admin": "admin"})
)


@site.register(Department)
class DepartmentAdmin(ModelAdmin):
    search_fields = ["name"]


@site.register(Employee)
class EmployeeAdmin(ModelAdmin):
    list_display = ["id", "name", "department", "hired", "salary"]
    list_filter = ["department", "hired", "salary"]
    search_fields = ["name"]
    ordering = ["name"]


app = FastAPI()
mount(app, site, path="/admin")
