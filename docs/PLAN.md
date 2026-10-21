# Atlas Admin — план проекта

Фреймворко‑независимая админ‑панель для Python: один пакет, который подключается
к FastAPI, Flask и Django и работает поверх SQLAlchemy, Tortoise ORM и Django ORM.

Дата: 2026‑10‑21. Статус: черновик плана после web research.

> **Решение от 2026‑10‑21:** первый релиз поддерживает только **SQLAlchemy** и **Tortoise ORM**.
> Django ORM, MongoDB и прочие бэкенды подключаем позже через тот же интерфейс `Repository`.
> Транспорты в первом релизе: Starlette/FastAPI; Flask и Django добавляются следующими этапами.
>
> **Статус на 2026‑10‑21:** этапы 0–2 реализованы: core, бэкенды memory/SQLAlchemy (sync+async)/Tortoise,
> транспорт Starlette, React UI (список, фильтры, формы, связи, bulk actions, экспорт), два примера в `examples/`.
>
> **Обновление 2026‑10‑21 (вечер):** добавлены бэкенды MongoDB (PyMongo sync/async, Motor; модели Pydantic + `Ref`)
> и Beanie ODM (`Link`/`BackLink`, DBRef-совместимость). 86 тестов, контракт гоняется на 8 конфигурациях.
> Следующее: Flask-транспорт, inline-связи, audit log, i18n.

---

## 1. Что уже есть на рынке и чему учимся

| Проект | Фреймворк | ORM | UI | Что берём |
|---|---|---|---|---|
| **starlette-admin** | Starlette/FastAPI | SQLAlchemy, SQLModel, MongoEngine, ODMantic, custom | Jinja + Tabler | Самая зрелая абстракция слоя данных: `BaseModelView` с 7 async‑методами (`find_all`, `count`, `find_by_pk`, `find_by_pks`, `create`, `edit`, `delete`) + `FilterGroup`, фабрика полей из колонок, `AuthProvider` как middleware + routes |
| **sqladmin** | Starlette/FastAPI | только SQLAlchemy | WTForms + Tabler | Простота API (`ModelView` + `column_list`), хуки `check_can_*`, audit‑бэкенды, JSON editor |
| **flask-admin 2.x** | Flask | SQLAlchemy, Peewee, pymongo, MongoEngine | Jinja + Bootstrap | Per‑ORM `ModelView` поверх общего `BaseModelView`, extras в pip (`[sqlalchemy]`, `[peewee]`) |
| **fastapi-admin** (long2ice) | FastAPI | только Tortoise | Tabler | Единственная рабочая Tortoise‑админка, ориентир по маппингу Tortoise‑полей |
| **piccolo-admin** | ASGI | только Piccolo | Vue SPA + REST | Headless‑архитектура: бэкенд отдаёт REST + OpenAPI, фронт отдельный SPA, bulk actions, CSV export, media в S3 |
| **fastapi-amis-admin** | FastAPI | SQLAlchemy/SQLModel | Baidu Amis (JSON‑driven UI) | Идея «сервер описывает UI как JSON‑схему, клиент рендерит» |
| **jet-bridge** | любой (отдельный процесс) | reflection БД | SaaS | Подтверждает спрос на «админка для любого приложения», но UI закрыт |
| **django-unfold** | Django | Django ORM | Tailwind | Планка современного UI: dark mode, command palette, sidebar, dashboards |

**Ключевой вывод.** Ни один проект не закрывает одновременно 3 фреймворка и 3 ORM.
Все серверные админки (starlette‑admin, sqladmin, flask‑admin) рендерят HTML через
Jinja и жёстко привязаны к роутингу своего фреймворка. Поэтому «портировать»
их на другой фреймворк дорого. Piccolo‑admin показывает выход: **headless‑ядро +
JSON‑протокол + SPA**. Тогда интеграция с фреймворком сводится к ~10 JSON‑эндпоинтам
и раздаче статики, а это пишется за день под каждый фреймворк.

---

## 2. Архитектура

```
┌──────────────────────────── atlas (python) ────────────────────────────┐
│                                                                              │
│  transports/            core/                         backends/              │
│  ├─ starlette (FastAPI) │  ├─ AdminSite (реестр)      ├─ sqlalchemy          │
│  ├─ flask    (WSGI)     │  ├─ ModelAdmin (конфиг)     ├─ tortoise            │
│  └─ django   (urls)     │  ├─ Protocol (JSON API)     └─ django              │
│                         │  ├─ Fields / Schema                                │
│   ↕ Request/Response    │  ├─ Filters / Search / Sort        ↕ Repository    │
│     DTO (без фреймв.)   │  ├─ Actions, Export, Audit           (async)       │
│                         │  └─ Auth / Permissions                             │
└──────────────────────────────────────────────────────────────────────────────┘
                     ▲ JSON over HTTP
┌─────────────────── atlas-ui (React + TS, статика в wheel) ─────────────┐
│  список / фильтры / детальная / формы / связи / bulk actions / dashboard     │
└──────────────────────────────────────────────────────────────────────────────┘
```

### 2.1 Три слоя и правило зависимостей

1. **core** — чистый Python, без импорта Starlette/Flask/Django/ORM. Принимает
   нейтральный `AdminRequest` (method, path, query, json body, headers, cookies, user)
   и возвращает `AdminResponse` (status, json/bytes, headers). Вся логика
   админки здесь.
2. **backends** — реализация интерфейса `Repository` под конкретную ORM плюс
   `ModelIntrospector`, который по классу модели строит `ModelSchema` (поля,
   типы, PK, связи, choices, nullable, default).
3. **transports** — тонкие адаптеры: конвертируют фреймворковый request в
   `AdminRequest`, вызывают `AdminSite.dispatch()`, отдают ответ, раздают статику SPA.

Зависимость только вниз: transports → core ← backends. Ни один backend не знает
о транспорте, и наоборот. Это даёт матрицу 3×3 бесплатно.

### 2.2 Интерфейс Repository (контракт для ORM‑адаптеров)

Берём за основу контракт starlette‑admin, он проверен на 4 бэкендах.

```python
class Repository(Protocol[T]):
    async def list(self, q: ListQuery) -> Page[T]          # filters, search, sort, offset/limit
    async def count(self, q: ListQuery) -> int
    async def get(self, pk: Any) -> T | None
    async def get_many(self, pks: list[Any]) -> list[T]
    async def create(self, data: dict) -> T
    async def update(self, pk: Any, data: dict) -> T
    async def delete(self, pks: list[Any]) -> int
    async def related_options(self, field: str, search: str, limit: int) -> list[Option]  # autocomplete FK/M2M
    def transaction(self) -> AsyncContextManager                                            # для bulk actions

class ListQuery:
    filters: FilterGroup        # дерево AND/OR из (field, op, value); op ∈ eq, ne, in, lt, gt, contains, is_null, between…
    search: str | None
    sort: list[tuple[str, Literal["asc","desc"]]]
    offset: int
    limit: int
```

Интерфейс **async**. Это осознанный выбор:

| ORM | Как реализуем |
|---|---|
| SQLAlchemy 2.0 | `AsyncSession` нативно; sync `Session` через `anyio.to_thread.run_sync` (так делает starlette‑admin) |
| Tortoise | нативно async |
| Django ORM | `aget`, `acount`, `async for` (Django ≥ 4.2), `prefetch_related` в `aiterator`; транзакции и M2M‑save через `sync_to_async(thread_sensitive=True)` |

Для Flask (WSGI) транспорт запускает async‑ядро через `asgiref.sync.async_to_sync`
на каждый запрос. Для Django поддерживаем оба режима: ASGI напрямую, WSGI через `async_to_sync`.

### 2.3 JSON‑протокол (стабильный контракт фронт ↔ бэк)

| Метод | Путь | Назначение |
|---|---|---|
| GET | `/_api/site` | Меню, ресурсы, права текущего юзера, брендинг |
| GET | `/_api/{resource}/schema` | `ModelSchema`: поля, типы, виджеты, фильтры, сортируемые, actions |
| GET | `/_api/{resource}` | Список: `?filters=…&search=…&sort=…&offset=…&limit=…` → `{items, total}` |
| GET | `/_api/{resource}/{pk}` | Детальная |
| POST | `/_api/{resource}` | Создание (JSON body, валидация → 422 с ошибками по полям) |
| PATCH | `/_api/{resource}/{pk}` | Обновление |
| DELETE | `/_api/{resource}` | Удаление `{pks: [...]}` |
| POST | `/_api/{resource}/actions/{name}` | Bulk / row action |
| GET | `/_api/{resource}/options/{field}?q=` | Autocomplete для FK/M2M |
| GET | `/_api/{resource}/export?format=csv` | Экспорт по текущим фильтрам |
| POST/DELETE | `/_api/auth/session` | Login / logout (если включён встроенный auth) |
| GET | `/{path:path}` | SPA `index.html` + статика |

Протокол описываем в OpenAPI‑файле в репозитории и тестируем контрактными тестами.
Это одновременно даёт сторонним фронтам (react‑admin, refine) возможность подключаться.

### 2.4 Публичный API для пользователя библиотеки

Единый стиль, напоминающий Django admin, чтобы не было порога входа:

```python
# FastAPI + SQLAlchemy
from atlas import AdminSite, ModelAdmin
from atlas.backends.sqlalchemy import SQLAlchemyBackend
from atlas.transports.starlette import mount

site = AdminSite(title="Atlas", backend=SQLAlchemyBackend(session_factory))

@site.register(User)
class UserAdmin(ModelAdmin):
    list_display = ["id", "email", "is_active", "created_at"]
    list_filter = ["is_active", "created_at"]
    search_fields = ["email", "name"]
    readonly_fields = ["created_at"]
    actions = ["deactivate"]

    async def deactivate(self, request, objs): ...

mount(app, site, path="/admin")

# Flask:   atlas.transports.flask.register(app, site, url_prefix="/admin")
# Django:  path("admin/", include(atlas.transports.django.urls(site)))
#          backend=DjangoBackend() — модели берутся из apps.get_models() или явно
# Tortoise: backend=TortoiseBackend()
```

Один `AdminSite` может держать несколько бэкендов одновременно (например, Django ORM + SQLAlchemy для legacy‑базы), бэкенд выбирается per‑ModelAdmin.

### 2.5 Фронтенд

- **React 19 + TypeScript + Vite**, UI на shadcn/ui + Tailwind, таблицы на TanStack Table,
  данные через TanStack Query, формы на react‑hook‑form + zod (схема генерируется из `ModelSchema`).
- Собранный бандл кладётся в wheel (`atlas/static/`), пользователю Node не нужен.
- Виджеты по типу поля: text, textarea, number, boolean, date/datetime, enum/select,
  FK‑autocomplete, M2M‑multiselect, JSON‑editor, file/image, rich text (позже).
- Тёмная тема, command palette (⌘K), сохранённые фильтры, адаптив под мобильный.
- Точки расширения: кастомные страницы (iframe или удалённые React‑компоненты позже),
  дашборд с виджетами, слоты в детальной странице.

Альтернатива (HTMX + Jinja) рассматривалась и отклонена: пришлось бы рендерить
шаблоны в каждом транспорте, что ломает принцип «транспорт тонкий».

### 2.6 Auth и права

- `AuthProvider` (Protocol): `authenticate(request) -> User | None`, `login(credentials)`, `logout()`.
- Встроенные: `SessionAuth` (cookie + password hash, таблица пользователей в любом бэкенде),
  `DjangoAuthProvider` (переиспользует `django.contrib.auth` и `is_staff`),
  `CallableAuth` (пользователь передаёт свою функцию, для JWT/SSO).
- Права: `has_view / has_add / has_change / has_delete / has_action` на уровне `ModelAdmin`
  с доступом к объекту, плюс row‑level через `get_queryset(request)`.
- CSRF для cookie‑сессии, `allowed_hosts`, rate‑limit на логин.

---

## 3. Структура репозитория

```
atlas/
├─ packages/
│  ├─ atlas/            # python, uv, src-layout
│  │  └─ src/atlas/
│  │     ├─ core/             # site, model_admin, schema, fields, filters, protocol, actions, export, audit, auth
│  │     ├─ backends/         # sqlalchemy/, tortoise/, django/   (каждый — optional extra)
│  │     ├─ transports/       # starlette.py, flask.py, django/
│  │     └─ static/           # собранный SPA (генерируется CI)
│  └─ atlas-ui/         # React, pnpm, Vite
├─ examples/                  # 9 комбинаций фреймворк × ORM, каждый — запускаемое приложение
├─ docs/                      # mkdocs-material
└─ tests/                     # unit (core), contract (протокол), matrix (backends × transports × БД)
```

pip extras: `atlas[sqlalchemy]`, `[tortoise]`, `[django]`, `[fastapi]`, `[flask]`.
Тулинг: uv, ruff, mypy strict для core, pytest + hypothesis для фильтров, Playwright для e2e.

---

## 4. Этапы

### Этап 0. Спецификация (1 неделя)
- Зафиксировать `Repository`, `ModelSchema`, `FilterGroup` и JSON‑протокол (OpenAPI).
- Написать `InMemoryBackend` для тестов ядра без БД.
- Решения, которые надо принять до кода: имя пакета, лицензия (MIT/BSD), минимальные версии
  (Python 3.11+, SQLAlchemy 2.0+, Django 4.2+, Tortoise 0.21+).

### Этап 1. Вертикальный срез (3–4 недели)
- core: AdminSite, ModelAdmin, dispatch, list/get/create/update/delete, валидация, пагинация, сортировка, поиск.
- backend: **SQLAlchemy** (async + sync), introspection колонок и relationship.
- transport: **Starlette/FastAPI**.
- UI: логин, список с таблицей, детальная, форма create/edit, delete.
- Результат: работающая админка для FastAPI + SQLAlchemy, пример в `examples/`.

### Этап 2. Второй бэкенд и матрица (2 недели)
- backend **Tortoise**: introspection `_meta.fields_map`, FK/M2M, `Tortoise.init` lifecycle.
- Контрактные тесты на оба бэкенда поверх одного набора сценариев.
- (Отложено) backend **Django ORM** и transport **Django**: `urls()` + views, `DjangoAuthProvider`, WSGI и ASGI.

### Этап 3. Flask и релиз 0.1 (1–2 недели)
- transport **Flask** через Blueprint + `async_to_sync`.
- CI‑матрица: 3 ORM × 3 транспорта × (SQLite, PostgreSQL).
- Документация quickstart для каждой из 9 комбинаций, публикация на PyPI.

### Этап 4. Паритет с Django admin (4–6 недель)
- Фильтры (date range, FK, enum, boolean, custom), сохранённые фильтры.
- Связи: FK/M2M autocomplete, inline‑редактирование дочерних записей.
- Bulk actions и row actions с подтверждением и формой параметров.
- Экспорт CSV/JSON/XLSX, импорт CSV.
- Audit log (кто/что/когда, diff), хуки `before_*/after_*`.
- Права на уровне модели и строки.

### Этап 5. Полировка и экосистема (ongoing)
- Дашборд с виджетами и графиками, кастомные страницы.
- Файлы и изображения: локальное хранилище и S3.
- i18n (ru/en из коробки), темы/брендинг.
- Адаптер под SQLModel (бесплатно поверх SQLAlchemy), Piccolo/Peewee по запросу сообщества.
- Плагин‑система: регистрация бэкендов, виджетов и страниц через entry points.

---

## 5. Риски и как их закрываем

| Риск | Митигация |
|---|---|
| Sync Django ORM в async‑ядре: `SynchronousOnlyOperation`, thread‑sensitivity | Только `a*`‑методы и `sync_to_async(thread_sensitive=True)` для транзакций; тесты под ASGI и WSGI |
| Разные модели фильтрации в трёх ORM | `FilterGroup` ограничен фиксированным набором операторов; бэкенд объявляет `supported_ops` per‑type, UI скрывает лишнее |
| Транзакции в bulk actions у разных ORM | `Repository.transaction()` как асинхронный контекст, реализация у каждого бэкенда своя |
| Объём SPA и поддержка фронта | Единый протокол позволяет заменить фронт; минимальный набор виджетов в 0.1 |
| Конфликт с существующим Django admin на `/admin/` | Документируем монтирование на `/atlas/`; возможность регистрировать модели из `admin.site._registry` |
| Производительность списков с большими связями (известная боль sqladmin #704) | Для списков не грузим relationship целиком, только `str()` + pk через отдельный lightweight select |

---

## 6. Источники

- starlette-admin: https://github.com/jowilf/starlette-admin , https://pypi.org/project/starlette-admin/
- sqladmin: https://pypi.org/project/sqladmin/ , https://github.com/aminalaee/sqladmin/releases , https://github.com/aminalaee/sqladmin/issues
- flask-admin: https://flask-admin.readthedocs.io/en/stable/changelog/ , https://flask-admin.readthedocs.io/en/latest/introduction/
- fastapi-admin (Tortoise): https://github.com/long2ice/fastapi-admin , https://pypi.org/project/fastapi-admin/
- piccolo-admin: https://github.com/piccolo-orm/piccolo_admin , https://piccolo-admin.readthedocs.io/en/latest/
- fastapi-amis-admin: https://github.com/amisadmin/fastapi-amis-admin , https://docs.amis.work/
- jet-bridge: https://github.com/jet-admin/jet-bridge
- django-unfold: https://github.com/unfoldadmin/django-unfold , https://www.djangoproject.com/weblog/2025/apr/18/admin-theme-roundup/
- Обзор альтернатив Django admin: https://leapcell.io/blog/beyond-django-admin-exploring-alternative-python-admin-interfaces
- a2wsgi (ASGI↔WSGI): https://pypi.org/project/a2wsgi/ , https://fastapi.tiangolo.com/advanced/wsgi/
- Django ASGI deploy / embed: https://docs.djangoproject.com/en/5.2/howto/deployment/asgi , https://til.simonwillison.net/django/datasette-django
- Django async ORM: https://forum.djangoproject.com/t/release-4-2a-async-querysets-with-prefetch-related/18767 , https://leapcell.io/blog/embracing-asynchronous-power-in-django-4-x-for-scalable-backends
- react-admin data provider (референс headless‑протокола): https://marmelab.com/react-admin/DataProviders.html
