# Stack Research: роли, права и аудит

**Domain:** RBAC (роли + права по разделам) для self-hosted FastAPI/PostgreSQL приложения
**Researched:** 2026-09-24
**Confidence:** HIGH (архитектурные рекомендации выведены напрямую из текущего кода `app/api/deps.py`, `auth_utils.py`, `event_bus.py`, `settings_service.py`, `data_lifecycle.py`, `schema.sql`); MEDIUM для внешних фактов об экосистеме (Casbin/Oso/PyJWT — проверено веб-поиском, несколько источников)

## Executive summary

**Новых зависимостей не требуется.** Всё необходимое для ролей с произвольным названием, галочек Просмотр/Изменение/Удаление по разделам, немедленного вступления в силу изменений и журнала действий уже покрывается тем, что в проекте есть: FastAPI `Depends()`, `psycopg`/`psycopg_pool`, `PyJWT`, `bcrypt`, `EventBus`/SSE и паттерн `app_settings_revision`. Решение — это две новые таблицы (`roles`, `user_audit_log`) плюс расширение уже существующих (`users` теряет `permissions JSONB`, получает `role_id`), без новых библиотек и без ORM.

Ключевое наблюдение по коду: `get_current_user` в `app/api/deps.py` **уже** перечитывает пользователя из БД на каждый запрос (`container.user_db.find_by_id(user_id)`), а не берёт роль/права из тела JWT. Поле `role` в самом токене (`auth_utils.create_access_token`) нигде не используется для авторизации — оно декоративное. Это значит, что «немедленное вступление в силу» для HTTP API **уже решено архитектурой**: блокировка пользователя, смена роли, правка прав — всё видно на следующий же запрос без какого-либо token versioning, blacklist или укорачивания TTL. Единственное реальное белое пятно — уже открытые SSE-соединения (`/api/events/stream`), которые не переаутентифицируются после первого подключения; для них нужен один маленький, самодельный кусок логики, переиспользующий существующий `EventBus`.

## Recommended Stack

### Core Technologies (изменений нет)

| Technology | Version | Purpose | Why Recommended |
|------------|---------|---------|-----------------|
| FastAPI `Depends()` | текущая (unpinned, уже в `pyproject.toml`) | DI-based проверка доступа на эндпоинте | Уже используется (`require_role`, `require_permission`, `require_access` в `app/api/deps.py`); для плоской модели «роль → JSON-карта прав по разделам» никакой отдельный authorization-фреймворк не даёт ничего, чего не даёт обычная функция-зависимость с SQL-запросом внутри |
| psycopg[binary] + psycopg_pool | текущая (unpinned) | Хранение и чтение ролей/прав/аудита | Тот же пул, что уже используют `PostgresEventDatabase`/`ListDatabase`; для join `users ⋈ roles` и вставки в `user_audit_log` не нужен ORM — обычный `SELECT`/`INSERT` через тот же `ConnectionPool` |
| PyJWT | 2.13.0 (последняя на сентябрь 2026, unpinned в проекте — совместимо) | Подпись/проверка identity-токена | Токен остаётся тонким: `sub` (id пользователя) + `exp` + `iat`. Роль/права в payload не нужны и не должны использоваться для решений о доступе — decode только устанавливает личность, а `get_current_user` всегда идёт в БД за актуальным состоянием |
| bcrypt | текущая (unpinned) | Хеширование паролей | Без изменений — блокировка пользователя не требует ничего от bcrypt |

### Supporting additions (новый код, не новые пакеты)

| Компонент | Где живёт | Purpose | When to Use |
|---|---|---|---|
| Таблица `roles` (`id SERIAL`, `name TEXT UNIQUE`, `permissions JSONB`, `created_at`, `updated_at`) | `database/postgres/schema.sql` + новый `database/roles_repository.py` | Произвольные роли с картой прав `{section: {view, edit, delete}}` | Заменяет захардкоженные строки `role` + плоский `permissions: list[str]` на `users` |
| `users.role_id BIGINT REFERENCES roles(id)` вместо `users.role TEXT` + `users.permissions JSONB` | `schema.sql`, `database/*_repository.py` (там, где сейчас читается `users`) | Одна роль на пользователя, многие пользователи на одну роль | Прямая замена по политике проекта (без миграции старых значений — см. `AGENTS.md` "Development And Rollback Policy") |
| `require_permission(section, action)` — переписанная версия текущей функции в `app/api/deps.py` | `app/api/deps.py` | Проверка `Просмотр/Изменение/Удаление` по разделу через JOIN `users → roles` | Заменяет сегодняшние `require_permission("tab:settings")`-строки (roadmap phase 11 это и планировал) |
| `user_audit_log` (append-only) | `database/postgres/schema.sql` + `database/audit_repository.py` | Кто/когда открыл шлагбаум, изменил роль, удалил канал | INSERT из `AppContainer`-сервисов в точках мутации (роутеры), не из middleware — чтобы в `details JSONB` попадал осмысленный контекст действия, а не сырой HTTP-запрос |
| Расширение `EventBus` (`runtime/event_bus.py`): подписчик хранит `user_id`, добавляется `publish_to_user()` / `close_user_sessions()` | `runtime/event_bus.py`, `app/api/routers/events.py` | Немедленное закрытие уже открытых SSE-сессий заблокированного/изменённого пользователя | Только для UX/безопасности живого потока; HTTP API и так проверяет права заново на каждый вызов |
| `retention.audit_log_retention_days` в `config/registry.py` + метод `cleanup_old_audit_log()` в `app/shared/data_lifecycle.py` | `config/registry.py`, `app/shared/data_lifecycle.py` | Ретеншн журнала действий | Копирует существующий паттерн `cleanup_old_events()`; выполняется тем же retention-воркером по тому же расписанию |

### Development Tools

Без изменений — pytest, без библиотек моков, тестовые двойники (уже принятый в `AGENTS.md` подход подходит для тестирования `require_permission`/`roles_repository` без БД: простой класс-двойник с фиктивными строками ролей).

## Installation

Новых пакетов ставить не нужно:

```bash
# Ничего не добавляем в pyproject.toml — используем то, что уже есть:
# fastapi, psycopg[binary], psycopg_pool, PyJWT, bcrypt
poetry install --no-root --only main
```

## Alternatives Considered

| Recommended | Alternative | When to Use Alternative |
|-------------|-------------|-------------------------|
| Своя функция-зависимость `require_permission(section, action)` + таблица `roles` | Casbin (PyCasbin) | Только если понадобится реальная политика (ABAC-условия, ограничения по конкретным каналам/объектам, множественные роли с наследованием). Ничего из этого не в scope текущего цикла — "Out of Scope" прямо исключает роль-на-канал и множественные роли |
| Per-request чтение роли из БД (`users JOIN roles`) | Token-versioning (счётчик версии токена в `users`, проверяемый в `get_current_user`) | Если в будущем решат класть права/роль внутрь самого JWT payload ради снижения нагрузки на БД на каждый запрос — тогда понадобится версия, инвалидирующая старые токены. При текущей архитектуре (payload тонкий, база уже читается каждый раз) это не нужно |
| Один SQL JOIN на каждый запрос | Кэш ролей в памяти по паттерну `SettingsService` (TTL + счётчик `revision`, как `app_settings_revision`) | Если профилирование покажет, что JOIN `users ⋈ roles` заметно нагружает пул на высокой частоте запросов (маловероятно для self-hosted инсталляции с несколькими операторами). Паттерн уже есть в `config/settings_service.py` — переиспользовать один в один, не изобретать новый механизм кэширования |
| Самодельный `user_audit_log` (одна таблица, `JSONB details`) | Специализированное решение вроде `pgaudit` (расширение PostgreSQL) | `pgaudit` логирует на уровне SQL-операторов сервера — избыточно и не даёт бизнес-семантику ("кто открыл шлагбаум"), плюс требует ставить/настраивать расширение на управляемом сервере, что выходит за рамки Docker-образа `postgres:16` без пересборки |
| Расширение `EventBus` для точечного закрытия SSE-сессий | Redis pub/sub для broadcast инвалидации сессий между процессами | В проекте явно нет Redis и его специально не заводили (`AGENTS.md`: "Cache / storage: none"); при единственном процессе `api` (см. `docker-compose.yml`) весь `EventBus` живёt в одной памяти — Redis тут не даёт ничего, кроме новой инфраструктуры |

## What NOT to Use

| Avoid | Why | Use Instead |
|-------|-----|-------------|
| **Casbin / PyCasbin** | Полноценный policy-engine (RBAC/ABAC/ACL, свой DSL `model.conf`, `Enforcer`). Официальные адаптеры PostgreSQL для Casbin (`casbin-sqlalchemy-adapter`, `casbin-async-sqlalchemy-adapter`) тянут за собой **SQLAlchemy** — второй слой доступа к БД рядом с уже принятым «сырой psycopg без ORM» (см. `AGENTS.md`: "Do not introduce a new dependency when an existing project dependency can solve the problem"). Модель требований этого цикла — плоская: роль = имя + галочки по разделам, без условий, без иерархий, без ABAC. Casbin решает задачу на порядок сложнее заявленной | Таблица `roles` + JOIN + Python-функция-зависимость |
| **Oso (open-source библиотека `oso`)** | Официально задеприкейчена авторами в пользу платного облачного Oso Cloud (см. `osohq/oso` на GitHub — README помечен Deprecated, `docs/oss/.../deprecation.html`). Устанавливать заведомо неподдерживаемую библиотеку под новую функциональность — риск без пользы | То же — своя функция-зависимость |
| **fastapi-users** | Полный фреймворк управления пользователями «из коробки»: регистрация, верификация email, OAuth, сброс пароля, своя схема на SQLAlchemy/Beanie. У проекта уже есть рабочая, узкая по объёму аутентификация (JWT + bcrypt + собственные роутеры `auth.py`/`users.py`) — замена на fastapi-users означает переписать существующий, работающий и покрытый требованиями код ради возможностей (OAuth, email-верификация), которые не нужны self-hosted системе за периметром организации | Точечное расширение существующих `app/api/routers/auth.py`, `users.py` |
| **fastapi-permissions** | Библиотека для ACL по объектам (Pyramid-style `Allow`/`Deny` на уровне отдельных ресурсов), давно не обновлялась. Даёт мощность, ориентированную на row-level ACL (ограничение по конкретному каналу/объекту), а это прямо в Out of Scope этого цикла | Раздел-уровневые галочки в `roles.permissions JSONB` |
| **Token blacklist / session store в Redis** | В проекте нет Redis и не планируется («no Redis» — явное архитектурное ограничение); а поскольку `get_current_user` и так читает пользователя из БД на каждый запрос, blacklist не даёт ничего нового для HTTP API — он бы дублировал то, что уже делает JOIN по `is_active`/`role_id` | Ничего добавлять не нужно; для SSE — точечное закрытие через `EventBus` |
| **Укорачивание `auth.token_ttl_minutes` как механизм пропагации изменений прав** | Настройка уже существует и управляет временем жизни токена (`config/registry.py`), но использовать её как *единственный* механизм немедленного вступления в силу — плохая идея: между реальным запросом (где права уже проверяются заново) это ничего не решает, а для открытых SSE-сессий короткий TTL не помогает вовсе — SSE не переавторизуется при истечении токена, соединение просто продолжает жить, пока клиент его не закроет | Явное закрытие SSE-подписки при блокировке/смене роли пользователя через `EventBus`, HTTP API и так свежий на каждый запрос |
| **`pgaudit` (расширение PostgreSQL)** | Логирует SQL-операторы на уровне сервера — не бизнес-события ("оператор X открыл шлагбаум 2"), а `UPDATE channels SET ...`. Не даёт `actor`/`action`/`target` семантику, которую требует "Журнал действий пользователей" из `PROJECT.md`. Плюс требует включения расширения в образе `postgres:16`, которого сейчас нет | Собственная таблица `user_audit_log`, наполняемая из бизнес-кода роутеров |

## Stack Patterns by Variant

**Если пользователь заблокирован во время активной сессии (HTTP API):**
- Ничего дополнительно делать не нужно
- Потому что `get_current_user` уже проверяет `is_active` на каждый запрос (строка `if not user.get("is_active"): raise HTTPException(401, ...)` в `app/api/deps.py`) — следующий же вызов API получит 401

**Если у пользователя изменили роль/права во время активной сессии (HTTP API):**
- Ничего дополнительно делать не нужно, кроме замены источника прав с `permissions JSONB` на `roles` через JOIN
- Потому что права читаются заново из БД на каждый запрос, а не из JWT — при переходе на `role_id` это свойство нужно сохранить (не начинать embedding прав в токен)

**Если у пользователя есть открытая SSE-сессия (`/api/events/stream`) на момент блокировки/смены роли:**
- Нужен точечный код: при `PUT /api/users/{id}` (блокировка) или изменении `roles.permissions` для роли пользователя — вызвать `container.event_bus.close_user_sessions(user_id)` (новый метод), который проталкивает управляющее SSE-событие (например, `{"type": "session_invalidated"}`) в очередь конкретного подписчика и удаляет его из `_subscribers`, после чего генератор в `stream_events` естественно завершается
- Потому что `EventBus.subscribe()` сейчас не знает, какому пользователю принадлежит очередь (`_subscribers: List[Queue]` — анонимный список); это единственное место, где по-настоящему нужен новый код, а не переиспользование существующего поведения

**Если много ролей меняются одновременно (например, роль "Оператор" редактируется, а её носят 20 пользователей):**
- Broadcast одного события с `role_id` через тот же `EventBus`, фронтенд каждой открытой вкладки сверяет своё `role_id` (полученное при логине через `/api/auth/me`) и либо мягко обновляет меню (перечитав `/api/auth/me`), либо форсирует релогин, если решение — понижение прав ниже текущего экрана
- Потому что закрывать 20 SSE-сессий из-за правки одной роли — не всегда нужно; для не-разрушительного расширения прав (например, добавили "Изменение" туда, где было только "Просмотр") достаточно, чтобы фронтенд узнал и обновил интерфейс, а бэкенд и так пересчитает права на следующий мутирующий запрос

## Version Compatibility

| Package A | Compatible With | Notes |
|-----------|-----------------|-------|
| PyJWT 2.13.0 | Python 3.13 | Текущая версия (unpinned в `pyproject.toml`, `"*"`) уже разрешается на актуальный релиз; отдельно фиксировать версию не требуется — проект и так держит PyJWT unpinned, как и остальную часть auth-стека |
| psycopg[binary] / psycopg_pool | PostgreSQL 16 | Без изменений; новые таблицы (`roles`, `user_audit_log`) используют тот же синтаксис DDL, что и существующие (`BIGSERIAL`, `JSONB`, `TIMESTAMPTZ NOT NULL DEFAULT now()`), никаких новых типов данных или расширений PostgreSQL не требуется |
| `roles.permissions JSONB` | Формат: `{"obs": {"view": true, "edit": false, "delete": false}, "journal": {...}, ...}` | Валидация формы (допустимые ключи разделов, булевы значения) — на уровне Python (Pydantic-схема запроса `RolePayload`), не через `CHECK`-constraint в БД — согласуется с тем, как уже валидируется `region JSONB`/`min_plate_size JSONB` у `channels` (валидация в Pydantic-схемах, не в SQL) |

## Sources

- Прямое чтение кода: `app/api/deps.py`, `app/api/auth_utils.py`, `app/api/routers/auth.py`, `app/api/routers/users.py`, `app/api/superadmin.py`, `runtime/event_bus.py`, `app/api/routers/events.py`, `config/settings_service.py`, `app/shared/data_lifecycle.py`, `database/postgres/schema.sql` — confidence HIGH (первоисточник, код проекта)
- WebSearch: "Oso Cloud discontinued open source Polar authorization library status" — подтверждено несколькими источниками (`github.com/osohq/oso` README помечен Deprecated, `osohq.com/docs/oss/.../deprecation.html`) — confidence MEDIUM (verified/cross-checked)
- WebSearch: "PyCasbin PostgreSQL adapter without SQLAlchemy" — подтверждено, что официальные PostgreSQL-адаптеры Casbin идут через SQLAlchemy (`apache/casbin-python-sqlalchemy-adapter`, `apache/casbin-python-async-sqlalchemy-adapter`) — confidence MEDIUM
- WebSearch: "PyJWT latest version changelog" — PyJWT 2.13.0 актуален на сентябрь 2026 — confidence MEDIUM
- WebSearch: "fastapi-users vs custom JWT lightweight RBAC FastAPI" — подтверждает, что для проектов с уже существующей узкой auth-реализацией типовая практика — наращивать её точечно, а не переходить на fastapi-users — confidence MEDIUM

---
*Stack research for: RBAC / роли, права, аудит (ANPR-System-web)*
*Researched: 2026-09-24*
