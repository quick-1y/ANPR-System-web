# Architecture Research — RBAC, блокировка пользователей, немедленное применение прав, аудит

**Domain:** Brownfield-интеграция ролевой модели доступа (роли + права Просмотр/Изменение/Удаление по разделам) в существующий FastAPI + PostgreSQL ANPR-бэкенд
**Researched:** 2026-09-24
**Confidence:** HIGH по инвентаризации эндпоинтов и текущим паттернам кода (прочитаны все роутеры, `deps.py`, `schema.sql`, `superadmin.py`, `user_repository.py`); MEDIUM по предлагаемой схеме БД и разбивке эндпоинтов на разделы (новая сущность, владелец ещё не утверждал конкретную схему); LOW/гипотеза — вопросы, явно помеченные как нерешённые самим `PROJECT.md` (контроллеры, право на управление ролями/пользователями)

Это исследование **не переоткрывает** архитектуру ANPR-конвейера — оно расширяет существующую систему авторизации (`app/api/deps.py`, `database/user_repository.py`, `database/postgres/schema.sql`) ровно в тех точках, где сегодня зафиксирован временный шов (`docs/roadmap/configuration-architecture.md`, раздел 4.11) и где `PROJECT.md` фиксирует решения владельца текущего цикла (фаза 11 этого roadmap).

---

## 1. Что уже есть и что меняется

| Сегодня | Становится |
|---|---|
| `users.role` (TEXT: `operator`\|`admin`\|`superadmin`), `users.permissions` (JSONB, только `tab:*`) | `users.role_id` (FK на новую таблицу `roles`), `users.full_name`; `role`/`permissions` как колонки удаляются целиком (чистая схема, без миграции — политика проекта) |
| `require_role("superadmin")` (11 мест), `require_permission("tab:settings")` (18 мест), голый `Depends(get_current_user)` (46 мест) | единый `require_section(section, action)` в `app/api/deps.py`, обёрнутый вокруг таблицы `role_permissions` |
| `tab:*` — 5 навигационных прав, из них реально проверяется на бэкенде только `tab:settings` | тот же набор из 5 разделов (Наблюдение/Журнал/Зоны/Клиенты/Настройки) становится реальными правами с тремя действиями каждое, и именно они управляют видимостью вкладки — `tab:*` как отдельная сущность исчезает |
| Деактивация пользователя = `is_active = false` (уже есть, уже это и есть блокировка) | тот же столбец, переосмысленный как «Блокировка» в UI/аудите — новый столбец не нужен |
| Нет журнала действий | `audit_log`, append-only, аналог существующего `app_settings.updated_by` по духу |
| `superadmin` — синтетическая учётная запись без строки в `users`, читается из `.env` каждый логин (`app/api/superadmin.py`) | не меняется вообще; остаётся единственным входом в раздел «Разработка» и аварийным способом создать первого администратора |

---

## 2. Компоненты и границы

```text
┌──────────────────────────────────────────────────────────────────────┐
│ app/web/js/ (frontend)                                                │
│  ui.js: applyTabVisibility(sectionPermissions) ─┐                    │
│  users.js: редактор ролей (чекбоксы В/И/У)      │  читает каталог     │
│  api.js: /api/auth/me → { role_name,            │  разделов+действий  │
│           section_permissions, is_blocked }     │  из ответа сервера, │
└──────────────────────────────────────────────────┼─не хранит его сам─┘
                                                     │
┌────────────────────────────────────────────────────▼─────────────────┐
│ app/api/ (FastAPI)                                                    │
│                                                                        │
│  config/permissions.py  ──────────┐  (новый модуль, класс C)          │
│  PERMISSION_CATALOGUE:            │  единый источник истины:          │
│   obs/journal/zones/clients/      │  разделы × действия               │
│   settings, действия view/edit/   │  потребляется тремя местами ↓     │
│   delete                          │                                   │
│         │                         │                                   │
│         ├──▶ app/api/deps.py: require_section(section, action)        │
│         │      резолвит current_user["section_permissions"]           │
│         │      (см. §5 — DB per-request, без токен-версии)            │
│         │                                                              │
│         ├──▶ app/api/routers/roles.py (новый): CRUD ролей,             │
│         │      валидирует payload по каталогу, отдаёт каталог         │
│         │      фронтенду (`GET /api/permissions/catalogue`)           │
│         │                                                              │
│         └──▶ app/api/routers/*.py (79 существующих эндпоинтов):        │
│                заменяют Depends(get_current_user) /                   │
│                require_permission("tab:settings") /                   │
│                require_role("superadmin") на require_section(...)     │
│                                                                        │
│  app/api/deps.py: get_current_user()                                  │
│    — как сегодня: JWT → user_id → DB-чтение строки users              │
│    — НОВОЕ: JOIN users→roles→role_permissions на каждый запрос,       │
│      блок проверяется тем же is_active, что и сегодня                 │
│    — superadmin: синтетический словарь, section_permissions           │
│      формируется программно (всё кроме «Разработки»), без строки БД   │
│                                                                        │
│  common/audit.py (новый): record_audit(container, current_user,       │
│    action, target=None, detail=None) — тонкая обёртка над              │
│    audit_db.record(...) + logger.info(...), вызывается из             │
│    обработчиков роутеров сразу после успешной мутации (§7)            │
└────────────────────────────────────────────────────────────────────────┘
                          │
┌─────────────────────────▼──────────────────────────────────────────────┐
│ database/ (PostgreSQL, psycopg_pool)                                    │
│  role_repository.py       — RoleDatabase: roles, role_permissions       │
│                              (сидирует дефолтные роли в _ensure_schema) │
│  user_repository.py       — UserDatabase: +role_id, +full_name          │
│  audit_log_repository.py  — AuditLogDatabase: append-only               │
│  (без изменений: channel/controller/zone/lists/clients/settings repo)   │
└───────────────────────────────────────────────────────────────────────┘
```

**Границы (кто с кем говорит):**

- `config/permissions.py` не зависит ни от чего (чистые данные, как `config/registry.py`) — это соответствует правилу AGENTS.md «Keep `config/` independent from domain logic».
- `app/api/deps.py` — единственное место, знающее *механизм* проверки (как сегодня `require_access` — единственный адаптер уровня). `require_section` заменяет `require_permission`/часть `require_role`, но `require_role("superadmin")` остаётся жить отдельно для «Разработки» — это осознанное исключение вне модели разделов (см. §6).
- `database/` не импортирует из `app/api/` (существующее правило) — поэтому хеширование пароля дефолтных `admin`/`operator` пользователей не может жить в `role_repository.py`/`user_repository.py`; оно остаётся в `app/api/` (см. §8).
- Фронтенд не хранит копию каталога прав в JS (в отличие от сегодняшнего дублирования `tab:*` строк одновременно в `auth.py` и в разметке `index.html`) — весь каталог отдаёт `GET /api/permissions/catalogue`, а текущие права пользователя — `GET /api/auth/me`.

---

## 3. Схема БД (предложение)

```sql
-- ── Роли ─────────────────────────────────────────────────────────────
CREATE TABLE IF NOT EXISTS roles (
    id          BIGSERIAL PRIMARY KEY,
    name        TEXT NOT NULL UNIQUE,
    created_at  TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at  TIMESTAMPTZ NOT NULL DEFAULT now()
);

-- Права роли: одна строка на (роль, раздел), три независимые галочки.
-- section — TEXT, а не enum/CHECK, намеренно: набор разделов расширяется
-- в коде (config/permissions.py), не требует ALTER TABLE при добавлении
-- нового раздела (например, когда решится вопрос контроллеров, см. §6).
CREATE TABLE IF NOT EXISTS role_permissions (
    role_id     BIGINT NOT NULL REFERENCES roles(id) ON DELETE CASCADE,
    section     TEXT NOT NULL,
    can_view    BOOLEAN NOT NULL DEFAULT FALSE,
    can_edit    BOOLEAN NOT NULL DEFAULT FALSE,
    can_delete  BOOLEAN NOT NULL DEFAULT FALSE,
    PRIMARY KEY (role_id, section)
);

-- ── Пользователи (изменения) ────────────────────────────────────────
-- role TEXT и permissions JSONB удаляются целиком (чистая схема,
-- PROJECT.md Out of Scope: миграция users.role/permissions не делается).
ALTER TABLE users DROP COLUMN IF EXISTS role;
ALTER TABLE users DROP COLUMN IF EXISTS permissions;
ALTER TABLE users ADD COLUMN IF NOT EXISTS role_id BIGINT NOT NULL REFERENCES roles(id) ON DELETE RESTRICT;
ALTER TABLE users ADD COLUMN IF NOT EXISTS full_name TEXT NOT NULL DEFAULT '';
-- is_active остаётся; это уже и есть "блокировка без удаления" —
-- deactivate() уже делает ровно то, что просит PROJECT.md. Переименование
-- нужно только в UI/аудите ("Заблокировать" вместо "Деактивировать"),
-- новый столбец is_blocked не нужен (см. §5).

-- ON DELETE RESTRICT на role_id: удаление роли, на которую ссылается хотя
-- бы один пользователь, должно быть запрещено на уровне БД как последний
-- рубеж — прикладной код (roles-роутер) обязан проверять это заранее и
-- отдавать 409, как уже делает delete_controller() для controller_id
-- в channels (см. app/api/routers/controllers.py:39-54), а не полагаться
-- на исключение БД.

-- ── Журнал действий ──────────────────────────────────────────────────
CREATE TABLE IF NOT EXISTS audit_log (
    id          BIGSERIAL PRIMARY KEY,
    at          TIMESTAMPTZ NOT NULL DEFAULT now(),
    actor_id    BIGINT REFERENCES users(id) ON DELETE SET NULL,
    actor_login TEXT NOT NULL,   -- денормализовано: superadmin не имеет
                                  -- строки в users (audit_user_id() уже
                                  -- сегодня возвращает NULL для него —
                                  -- app/api/superadmin.py:56), а обычный
                                  -- пользователь может быть впоследствии
                                  -- удалён; запись обязана остаться читаемой
    action      TEXT NOT NULL,   -- 'channels.delete', 'controllers.trigger',
                                  -- 'roles.update', 'users.block', ...
    target      TEXT,            -- 'channel:12', 'user:7', 'controller:3#relay:0'
    detail      JSONB,           -- произвольный контекст (старое/новое значение)
    ip          TEXT
);
CREATE INDEX IF NOT EXISTS idx_audit_log_at_id_desc ON audit_log(at DESC, id DESC);
CREATE INDEX IF NOT EXISTS idx_audit_log_actor ON audit_log(actor_id) WHERE actor_id IS NOT NULL;
```

**Почему не нужен столбец версии прав/токена.** См. §5 — `get_current_user()` уже сегодня читает строку `users` из БД на *каждый* запрос (`container.user_db.find_by_id(user_id)` в `app/api/deps.py:46`), а не кэширует её в JWT. JWT несёт `role` в payload (`app/api/auth_utils.py:38-43`), но этот claim нигде не читается обратно — `get_current_user` определяет личность только по `sub`, а роль/права всегда берёт из БД заново. Это значит нужная архитектура для немедленного применения прав **уже существует** для блокировки (`is_active`) и тривиально расширяется на `role_id`/`role_permissions` без добавления версии/кэша.

---

## 4. Каталог прав как источник истины в коде

Новый модуль `config/permissions.py` (по аналогии с `config/registry.py`, но не смешивается с операционными настройками — это отдельный домен):

```python
from __future__ import annotations
from dataclasses import dataclass

ACTIONS = ("view", "edit", "delete")

@dataclass(frozen=True)
class PermissionSection:
    key: str     # 'obs' | 'journal' | 'zones' | 'clients' | 'settings'
    label: str   # для UI редактора ролей и для подписи вкладки

PERMISSION_CATALOGUE: tuple[PermissionSection, ...] = (
    PermissionSection("obs", "Наблюдение"),
    PermissionSection("journal", "Журнал"),
    PermissionSection("zones", "Зоны"),
    PermissionSection("clients", "Клиенты"),
    PermissionSection("settings", "Настройки"),
)
```

Потребители (три места, как и требует вопрос исследования):

1. **`app/api/deps.py`** — `require_section(section, action)` проверяет `current_user["section_permissions"][section][action]`, `section` и `action` валидируются по каталогу при регистрации роутов (программная защита от опечатки в новом эндпоинте — аналог задачи 11.5 «добавление эндпоинта без объявленного уровня доступа не проходит тесты»).
2. **`app/api/routers/roles.py`** (новый) — `GET /api/permissions/catalogue` отдаёт `PERMISSION_CATALOGUE` фронтенду (заменяет сегодняшний `GET /api/permissions/available`, который отдавал захардкоженный `AVAILABLE_PERMISSIONS` из `auth.py:25-31`); `POST/PUT /api/roles` валидирует, что во входящем JSON нет разделов вне каталога.
3. **Фронтенд `ui.js`** — `applyTabVisibility` перестаёт читать плоский список `tab:*` строк и вместо этого проверяет `section_permissions[section].view` для каждой вкладки; сам каталог (список разделов) не хардкодится в JS — он приходит с сервера один раз при загрузке, что закрывает класс проблем, аналогичный P14 (дублирование перечислений между слоями), для этой новой сущности.

**Гипотеза, требующая подтверждения владельца:** сохранится ли раздел «Настройки» как единая тройка Просмотр/Изменение/Удаление (моя рекомендация, согласованная со схемой выше) или «одна галочка на весь раздел» в `PROJECT.md` означает буквально один булев флаг без разделения на три действия? Формулировка `PROJECT.md` («Настройки» — одна галочка на весь раздел в этом цикле, дробление на подразделы — позже) естественнее читается как «не делить на подразделы (общие/каналы/контроллеры/пользователи/данные)», а не как «убрать тройку действий» — иначе непонятно, что означало бы «Удаление» для настроек. Ниже (§6) я использую тройку и даю «Удалению» осмысленное содержание (удаление канала/списка как часть настроек), но это решение нужно явно подтвердить на этапе планирования, а не в разработке.

---

## 5. Немедленное применение прав и блокировки

**Рекомендация: постоянное чтение из БД на каждый запрос, без версии токена и без in-process кэша.**

Обоснование:

- Это не новая архитектура, а прямое продолжение существующей: `get_current_user()` уже безусловно делает `container.user_db.find_by_id(user_id)` на каждый вызов (`app/api/deps.py:46`) — кэша нет и сегодня. Блокировка (`is_active`) уже подхватывается «сразу», потому что каждый следующий HTTP-запрос уже забойного пользователя получает 401 (`app/api/deps.py:49-50`) без перевхода и без версии токена.
- Расширение: `find_by_id` (или новый метод `UserDatabase.find_with_permissions(user_id)`) делает один `JOIN users → roles → role_permissions`, агрегирует три булевых поля в `section_permissions: dict[str, dict[str, bool]]` и кладёт в возвращаемый словарь пользователя. Стоимость — один дополнительный JOIN на запрос поверх уже существующего одиночного SELECT; при масштабе self-hosted охранного поста (десятки пользователей, не тысячи) это не бутылочное горлышко, а `psycopg_pool` (min=2, max=10) уже спроектирован под частые короткие запросы такого рода.
- JWT payload не меняется по составу: как и сегодня, роль/права туда не кладутся как источник правды (текущий claim `role` в JWT уже фактически не читается обратно нигде в `get_current_user`, только `sub` — это стоит явно осознать при реализации: он декоративный уже сейчас).

**Альтернатива (не рекомендуется для этого масштаба, но фиксируется как рассмотренная):** «версия прав» — глобальный счётчик по образцу уже существующего `app_settings_revision` (`database/postgres/schema.sql:145-150`, единственная строка `revision`, инвалидирующая in-memory кэш настроек в API и в retention-воркере). Для прав это выглядело бы как `users.permissions_version` (или общий счётчик), кэш `(role_id, version) → section_permissions` в процессе, и на каждый запрос — дешёвая проверка версии вместо JOIN. Оправдано только если профилирование покажет, что JOIN на права ощутимо дороже, чем сегодняшний одиночный SELECT — на старте цикла для этого нет оснований, поэтому не закладывается сразу (YAGNI), но схема (`role_permissions` как отдельная таблица, а не JSONB-снимок на пользователе) не мешает добавить версию позже без миграции пользовательских данных.

**SSE и MJPEG-потоки (открытые долгоживущие соединения).** Сегодня `GET /api/events/stream` (`app/api/routers/events.py:104`) и `GET /api/debug/logs/stream` (`app/api/routers/debug.py:64`) проверяют право один раз — при открытии соединения — и дальше держат его произвольно долго, циклом с `asyncio.wait_for(queue.get(), timeout=15.0)`, который и без того просыпается каждые 15 секунд, чтобы отправить `: ping\n\n` при отсутствии событий. Это готовая точка для повторной проверки:

- На каждый таймаут (~раз в 15 секунд) генератор повторно резолвит права текущего пользователя (тот же путь, что и `get_current_user`, но без нового HTTP-запроса — прямой вызов `container.user_db.find_with_permissions(user_id)`), и если пользователь заблокирован или потерял `view` на раздел, к которому привязан поток (`journal` для `/api/events/stream`, аппаратно жёстко «Разработка»/superadmin для debug-логов) — генератор завершает `yield`, соединение закрывается, `EventSource` на фронтенде переподключается автоматически и при новом подключении получает актуальный (уже негативный) результат проверки.
- Тот же приём применим к MJPEG-превью канала (`GET /api/channels/{id}/preview.mjpg`, `app/api/routers/channels.py:79`) — его цикл `frame_generator()` крутится каждые ~80 мс; там повторную проверку стоит делать не на каждой итерации (дорого/избыточно), а по монотонному таймеру раз в те же ~15 секунд.
- Худший случай задержки применения блокировки для уже открытого потока — интервал до следующего пинга (≤15 секунд для событий/дебага; ≤15 секунд при таймере в MJPEG). Для консоли оператора это практически «немедленно» и не требует новой инфраструктуры (никакого Redis pub/sub, никакого форс-дисконнекта извне — что и требует ограничение стека AGENTS.md «без Redis»).

**Блокировка пользователя — отдельно резюме:** новый столбец не нужен. `is_active` уже реализует «заблокировать без удаления» (`UserDatabase.deactivate()`, `database/user_repository.py:191-200`, уже сегодня НЕ удаляет строку). Меняется только семантика в UI/аудите: `DELETE /api/users/{id}` синтаксически вводит в заблуждение (ничего не удаляет) — стоит рассмотреть замену на `PUT /api/users/{id}` с `is_active: false` (уже поддерживается `UserUpdate.is_active`, `app/api/schemas.py:97`) и явную кнопку «Заблокировать/Разблокировать» вместо «Удалить» в UI, чтобы название API не расходилось с поведением.

---

## 6. Инвентаризация эндпоинтов и предлагаемое отображение (section, action)

Ниже — все обработчики из `app/api/routers/*.py` (79 штук, что совпадает с «80 эндпоинтов» из контекста задания с точностью до пограничного подсчёта `GET /`). Таблицы сгруппированы по файлам роутеров; колонка «Сейчас» — фактический механизм защиты по коду, колонка «Предложение» — раздел.действие в новой модели.

### `app/api/routers/channels.py` (16) — split между «Наблюдение» и «Настройки»

Ключевое предложение: **операционное управление уже запущенным каналом** (смотреть, запускать/останавливать) — это `obs`; **конфигурация самого канала** (создание, ROI, детекция, удаление) — это `settings`, потому что в существующем UI редактор конфигурации канала физически живёт под `Настройки → Каналы` (`index.html:398`, `data-sp="channels"`), а не под вкладкой «Наблюдение». Это прямое следствие уже существующей структуры интерфейса, не новая идея.

| Эндпоинт | Сейчас | Предложение |
|---|---|---|
| `GET /api/channels` | `get_current_user` | `obs.view` |
| `GET /api/channels/last-plates` | `get_current_user` | `obs.view` |
| `GET /api/channels/{id}/snapshot.jpg` | `get_current_user` | `obs.view` |
| `GET /api/channels/{id}/preview/status` | `get_current_user` | `obs.view` |
| `GET /api/channels/{id}/preview.mjpg` | `get_current_user` | `obs.view` (+ периодическая перепроверка, см. §5) |
| `GET /api/channels/{id}/health` | `get_current_user` | `obs.view` |
| `POST /api/channels/{id}/start` | `get_current_user` | `obs.edit` |
| `POST /api/channels/{id}/stop` | `get_current_user` | `obs.edit` |
| `POST /api/channels/{id}/restart` | `get_current_user` | `obs.edit` |
| `GET /api/channels/{id}/config` | `get_current_user` | `settings.view` |
| `POST /api/channels` | `get_current_user` | `settings.edit` |
| `PUT /api/channels/{id}` | `get_current_user` | `settings.edit` |
| `PUT /api/channels/{id}/config` | `get_current_user` | `settings.edit` |
| `PUT /api/channels/{id}/ocr` | `get_current_user` | `settings.edit` |
| `PUT /api/channels/{id}/filter` | `get_current_user` | `settings.edit` |
| `DELETE /api/channels/{id}` | `get_current_user` | `settings.delete` |

Все 16 сегодня защищены только фактом входа — это ровно проблема P19 из аудита; `DELETE /api/channels/{id}` (явно названа в аудите как пример) закрывается здесь на `settings.delete`.

### `app/api/routers/events.py` (4) — «Журнал»

| Эндпоинт | Сейчас | Предложение |
|---|---|---|
| `GET /api/events` | `get_current_user` | `journal.view` |
| `GET /api/events/item/{id}` | `get_current_user` | `journal.view` |
| `GET /api/events/item/{id}/media/{kind}` | `get_current_user` | `journal.view` |
| `GET /api/events/stream` | `get_current_user` | `journal.view` (+ перепроверка на пинге, см. §5) |

Действий `edit`/`delete` для журнала сегодня нет (событий нельзя редактировать вручную, массовое удаление — только через retention-политику, которая относится к `settings`, см. ниже) — `journal.edit`/`journal.delete` в каталоге можно объявить, но они останутся невостребованными до появления соответствующих операций (ручная правка/удаление события), либо `edit`/`delete` для этого раздела не выставляются в UI редактора ролей вовсе — решение за владельцем при планировании.

### `app/api/routers/zones.py` (5) — «Зоны»

| Эндпоинт | Сейчас | Предложение |
|---|---|---|
| `GET /api/zones` | `get_current_user` | `zones.view` |
| `GET /api/zones/{id}` | `get_current_user` | `zones.view` |
| `POST /api/zones` | `get_current_user` | `zones.edit` |
| `PUT /api/zones/{id}` | `get_current_user` | `zones.edit` |
| `DELETE /api/zones/{id}` | `get_current_user` | `zones.delete` |

### `app/api/routers/clients.py` (8) + `app/api/routers/lists.py` (7) — «Клиенты»

В интерфейсе нет отдельной вкладки для списков (`index.html` содержит только `obs/journal/zones/clients/settings` — пяти вкладок), значит списки (whitelist/blacklist) управляются из той же вкладки «Клиенты»; логично объединить оба роутера под один раздел `clients`.

| Эндпоинт | Сейчас | Предложение |
|---|---|---|
| `GET /api/clients` | `get_current_user` | `clients.view` |
| `GET /api/clients/search` | `get_current_user` | `clients.view` |
| `GET /api/clients/{id}` | `get_current_user` | `clients.view` |
| `GET /api/lists` | `get_current_user` | `clients.view` |
| `GET /api/lists/plates` | `get_current_user` | `clients.view` |
| `GET /api/lists/{id}/clients` | `get_current_user` | `clients.view` |
| `POST /api/clients` | `get_current_user` | `clients.edit` |
| `PUT /api/clients/{id}` | `get_current_user` | `clients.edit` |
| `POST /api/clients/{id}/attach` | `get_current_user` | `clients.edit` |
| `DELETE /api/clients/{id}/attach` | `get_current_user` | `clients.edit` (отвязка от списка — не удаление клиента) |
| `POST /api/lists` | `get_current_user` | `clients.edit` |
| `PUT /api/lists/{id}` | `get_current_user` | `clients.edit` |
| `POST /api/lists/{id}/import` | `get_current_user` | `clients.edit` |
| `DELETE /api/clients/{id}` | `get_current_user` | `clients.delete` |
| `DELETE /api/lists/{id}` | `get_current_user` | `clients.delete` |

### `app/api/routers/settings.py` (4) + `app/api/routers/data.py` (8) — «Настройки»

| Эндпоинт | Сейчас | Предложение |
|---|---|---|
| `GET /api/countries` | `require_permission("tab:settings")` | `settings.view` |
| `GET /api/settings/schema` | `require_access("authenticated")` | без изменений — это справочник перечислений (не секрет), нужен любому вошедшему для рендера собственного UI |
| `GET /api/settings` | `require_permission("tab:settings")` | `settings.view` |
| `PUT /api/settings` | `require_permission("tab:settings")` | `settings.edit` |
| `GET /api/data/policy` | `require_permission("tab:settings")` | `settings.view` |
| `POST /api/data/retention/run` | `require_permission("tab:settings")` | `settings.delete` — **не `edit`**: операция необратимо стирает старые события/скриншоты; семантически ближе к удалению, чем к изменению настройки. Флаг для решения на планировании: это пограничный случай, где «действие» не совпадает с HTTP-методом (`POST`, а не `DELETE`) |
| `GET /api/data/export/events.csv` | `require_permission("tab:settings")` | `settings.view` (экспорт — чтение) |
| `POST /api/data/export/bundle` | `require_permission("tab:settings")` | `settings.view` |
| `GET /api/data/backup/database` | `require_permission("tab:settings")` | `settings.view` |
| `POST /api/data/backup/database/restore` | `require_permission("tab:settings")` | `settings.edit` формально, но см. отдельное предупреждение ниже |
| `GET /api/data/backup/settings` | `require_permission("tab:settings")` | `settings.view` |
| `POST /api/data/backup/settings/restore` | `require_permission("tab:settings")` | `settings.edit` |

**Замечание безопасности, не входящее в задачу маппинга, но важное для планирования:** `POST /api/data/backup/database/restore` полностью перезаписывает БД (включая события, каналы, пользователей, роли) и **останавливает и перезапускает процесс** (`app/api/routers/data.py:163-198`). Втискивать это в тот же `settings.edit`, что и смену уровня логирования, — рискованно: любая роль с «Настройки: Изменение» получает возможность одним запросом стереть всю систему. Стоит явно решить на планировании, не ограничить ли восстановление БД дополнительно ролью `superadmin` (как сегодня фактически ограничены `controllers`/`debug`), независимо от общей модели разделов — это тот же класс решения, что и «Разработка» в §7.

### `app/api/routers/auth.py` (4) — не вписывается в модель разделов

| Эндпоинт | Сейчас | Предложение |
|---|---|---|
| `POST /api/auth/login` | публичный | `public` — без изменений |
| `POST /api/auth/logout` | `get_current_user` | `self` |
| `GET /api/auth/me` | `get_current_user` | `self` — ответ расширяется: `role_name`, `section_permissions`, `is_blocked` вместо плоского `role`+`permissions` |
| `GET /api/permissions/available` | `require_permission("tab:settings")` | заменяется на `GET /api/permissions/catalogue`, уровень `authenticated` (это статический список разделов/действий из кода, не секрет — нужен редактору ролей, который живёт под `admin-users`, но сам каталог не обязан быть настолько же закрытым) |

### `app/api/routers/users.py` (6) + новый `app/api/routers/roles.py` — своя область, а не часть 5 разделов

Это прямо то, что просит пометить задание. Управление пользователями и ролями концептуально не «раздел» в списке `PROJECT.md` (Наблюдение/Журнал/Зоны/Клиенты/Настройки) — это управление самой моделью доступа, и предоставление его через `settings.edit` создаёт риск самоэскалации: любая кастомная роль с правом «Настройки: Изменение» смогла бы создать пользователя с ролью «Администратор» (все права) или отредактировать собственную роль, выдав себе больше прав. `PROJECT.md` этот вопрос явно не решает (в Key Decisions нет пункта про иерархию ролей).

**Рекомендация:** отдельный уровень доступа `admin-users` (как и предусмотрено 4.11 roadmap — он уже перечислен в списке уровней `app/api/deps.py:99-101`, но сегодня не используется ни одним эндпоинтом). Реализуется как ещё один адаптер в `deps.py`, сегодня технически совпадающий по механике с `settings.edit` (т.е. первая итерация — тот же чек), но как отдельная точка переключения, чтобы позже можно было сузить круг (например, только `superadmin` или отдельная галочка «Управление пользователями») без переписывания всех вызывающих мест — это тот же приём, что уже применён для `admin-*` уровней в 4.11.

| Эндпоинт | Сейчас | Предложение |
|---|---|---|
| `GET /api/users` | `require_permission("tab:settings")` | `admin-users` |
| `POST /api/users` | `require_permission("tab:settings")` | `admin-users` |
| `GET /api/users/{id}` | `require_permission("tab:settings")` | `admin-users` |
| `PUT /api/users/{id}` | `require_permission("tab:settings")` | `admin-users` |
| `PUT /api/users/{id}/password` | инлайн-проверка в теле (`current_user["role"] == "superadmin" or "tab:settings" in permissions`, `app/api/routers/users.py:142`) | заменить на два явных случая через зависимости: смена **своего** пароля — `self`; смена **чужого** пароля — `admin-users`. Убирает P-подобный анти-паттерн, прямо осуждённый в AGENTS.md («Preferred Patterns... Patterns To Avoid Copying») |
| `DELETE /api/users/{id}` | `require_permission("tab:settings")` | `admin-users` (по факту — блокировка, см. §5) |
| `GET /api/roles` (новый) | — | `admin-users` (чтение может быть доступно как `view`, если решится дробление) |
| `POST /api/roles` (новый) | — | `admin-users` |
| `PUT /api/roles/{id}` (новый) | — | `admin-users` |
| `DELETE /api/roles/{id}` (новый) | — | `admin-users`; должен возвращать 409, если на роль ссылается хотя бы один пользователь (по образцу `delete_controller`, `app/api/routers/controllers.py:39-54`) |

**Открытый вопрос для планирования, не решённый здесь:** нужна ли защита от самоэскалации (роль X не может назначить/отредактировать роль с большим набором прав, чем у неё самой)? `PROJECT.md` этого не требует явно, а модель «одна произвольная роль, любой набор галочек» такую иерархию не подразумевает. Фиксирую как гипотезу к обсуждению на планировании, не как решение.

### `app/api/routers/debug.py` (6) — «Разработка», вне модели разделов целиком

| Эндпоинт | Сейчас | Предложение |
|---|---|---|
| все 6 (`/api/debug/*`) | `require_role("superadmin")` | без изменений — `PROJECT.md` прямо фиксирует: «superadmin — единственный, кому доступен раздел «Разработка»... через него можно создать первого администратора» |

### `app/api/routers/system.py` (6) — не вписывается ни в один раздел

| Эндпоинт | Сейчас | Предложение |
|---|---|---|
| `GET /` | без проверки | `public` |
| `GET /api/health` | без проверки | `public` (нужен для healthcheck контейнера — нельзя требовать авторизацию) |
| `GET /api/system/time` | `require_access("authenticated")` | без изменений |
| `GET /api/system/resources` | `get_current_user` | `authenticated` (низкая чувствительность — CPU/RAM инстанса) |
| `GET /api/storage/status` | `get_current_user` | `authenticated` |
| `GET /api/telemetry/channels` | `get_current_user` | можно оставить `authenticated`, либо `obs.view`, если телеметрию считать частью наблюдения — рекомендую `obs.view` для согласованности с остальными телеметрическими эндпоинтами каналов |

### `app/api/routers/controllers.py` (5) — контроллеры: открытое решение

**Задание прямо просит не принимать решение здесь.** Ниже — варианты для владельца/плана, без выбора:

| Эндпоинт | Сейчас |
|---|---|
| `GET/POST/PUT/DELETE /api/controllers[/{id}]` | `require_role("superadmin")` |
| `POST /api/controllers/{id}/test` (ручное срабатывание реле — тот же путь, что и хоткей активации из UI, `controllers.js:143-145`) | `require_role("superadmin")` |

**Вариант A — статус-кво.** Оставить весь роутер на `require_role("superadmin")` до завершения отдельного исследования аналогов (Trassir/AutoTrassir), как и зафиксировано в `PROJECT.md` Out of Scope («Дробление... отложено до исследования работы с контроллерами»). Самый безопасный выбор для этого цикла: ничего не ломается, охранник-оператор физически не может открыть шлагбаум через API до отдельного решения.

**Вариант B — разделить «настройку» и «использование».** CRUD контроллера (создание/правка/удаление, привязка к каналу) остаётся в `settings` (или отдельно под `admin-devices`, как уже предусмотрено в 4.11); `POST /{id}/test` (=ручное открытие/закрытие через хоткей) переезжает под `obs.edit` — по аналогии с `start/stop/restart` канала: это оперативное действие оператора, а не изменение конфигурации оборудования. Это соответствует типичному паттерну охранных систем (разделение «конфигурирование устройства» и «управление устройством в моменте»), но именно это надо подтвердить исследованием, которое `PROJECT.md` ещё не провело.

**Вариант C — отдельный 6-й раздел «Контроллеры».** Даёт максимальную гибкость (своя тройка Просмотр/Изменение/Удаление отдельно от «Настроек»), но добавляет шестую строку в чек-лист ролей сверх пяти, явно перечисленных в `PROJECT.md` для этого цикла — требует отдельного согласования с владельцем, не подразумевается текущей формулировкой требований.

**Вариант D — гибрид.** Как A сейчас (только superadmin), но каталог прав (`config/permissions.py`) с первого дня проектируется так, чтобы добавление раздела `controllers` позже было вставкой одной строки (`role_permissions.section` — TEXT, не enum/CHECK, см. §3) — то есть архитектурно не блокирует последующий выбор B или C, не требуя миграции.

**Рекомендация для build order (не для решения):** реализовать Вариант A/D на этом цикле (без изменений в `controllers.py`, но с готовой к расширению схемой), и явно оставить задачу «применить выбранный вариант B/C» в бэклог после завершения исследования контроллеров.

---

## 7. Аудит-лог: куда вставляется вызов

**Репозиторий, а не middleware.** `database/audit_log_repository.py` → `AuditLogDatabase`, тот же паттерн, что и любой другой репозиторий проекта (`_SCHEMA`, `_ensure_schema()`, методы `record(...)`/`list_recent(...)`), регистрируется в `AppContainer` (dataclass-поле + `build()` + `refresh_storage_clients()`) — по образцу существующих полей `user_db`, `channel_db` и т.д. (`app/api/container.py:36-43, 78-106`).

**Вызов — явный, из тела обработчика роутера, сразу после успешной мутации**, не через ASGI middleware и не через автоматический перехват по HTTP-методу+пути. Причины:

1. Middleware-подход не может содержательно описать *что именно* произошло («удалил канал `id=12`, название "Въезд-1"» vs просто «DELETE /api/channels/12») без хрупкого парсинга тела ответа.
2. В проекте уже есть ad hoc заготовка ровно такого рода записей — `logger.info("Обновлён пользователь id=%s (admin: %s)", ...)` в `app/api/routers/users.py:122-126,155-159,181-185` — то есть текстовый журнал важных действий уже существует как паттерн, просто не персистентен и не структурирован. Новый механизм — это промотирование существующего стиля в БД-таблицу, а не изобретение нового.
3. Соответствует правилу AGENTS.md «авторизация выполняется в зависимостях, а не в телах обработчиков» ровно наоборот для аудита: аудит — это *побочный эффект после* авторизации и мутации, поэтому его естественное место — конец обработчика, а не зависимость (зависимости в FastAPI выполняются до тела и не знают, успешно ли прошла мутация).

**Тонкая обёртка `common/audit.py`:**

```python
def record_audit(
    container: AppContainer,
    current_user: dict,
    action: str,          # 'channels.delete', 'controllers.trigger', 'roles.update', ...
    target: str | None = None,
    detail: dict | None = None,
    request: Request | None = None,
) -> None:
    actor_id = audit_user_id(current_user)          # переиспользует app/api/superadmin.py:56
    actor_login = current_user.get("login", "?")
    container.audit_db.record(
        actor_id=actor_id, actor_login=actor_login,
        action=action, target=target, detail=detail,
        ip=(request.client.host if request and request.client else None),
    )
    logger.info("audit action=%s actor=%s target=%s", action, actor_login, target)
```

Живёт в `common/`, потому что это ровно то, что AGENTS.md определяет для этого каталога — «Cross-cutting utilities» (аналог `common/logging.py`), и не тянет зависимость `database → app/api`, а наоборot: `app/api` вызывает `common`, что не нарушает ни одно из правил размещения.

**Что логировать (минимум, по примерам из `PROJECT.md`: «открыл шлагбаум, изменил роль, удалил канал»):**

| Действие | `action` | Где вызывается |
|---|---|---|
| Ручное срабатывание реле | `controllers.trigger` | `POST /api/controllers/{id}/test` |
| Создание/изменение/удаление роли | `roles.create` / `roles.update` / `roles.delete` | новый `roles.py` |
| Создание/блокировка/разблокировка пользователя, смена чужого пароля | `users.create` / `users.block` / `users.unblock` / `users.password_reset` | `users.py` |
| Удаление канала | `channels.delete` | `channels.py` |
| Восстановление БД / настроек из бэкапа | `data.database_restore` / `data.settings_restore` | `data.py` |
| Запуск retention (удаление старых событий) | `data.retention_run` | `data.py` |
| Удаление зоны/списка/клиента | `zones.delete` / `clients.delete` (list) / `clients.delete` (client) | соответствующие роутеры |
| Вход в систему (в т.ч. под superadmin) | `auth.login` | уже логируется через `logger.info` в `auth.py:112,165` — дублировать в `audit_log` по желанию (полезно для «кто и когда» отчётности), не критично для MVP |

Не логируются GET-запросы (только `view`) — это журнал *действий*, а не журнал доступа; для последнего в проекте уже есть `logging` (сетевые/HTTP-логи Nginx/uvicorn).

---

## 8. Superadmin и бутстрап ролей/пользователей

**Superadmin не меняется.** Остаётся синтетическим (`SUPERADMIN_ID = 0`, без строки в `users`, пароль только из `.env`, `app/api/superadmin.py`). В новой модели он получает `section_permissions`, программно выставленные «всё разрешено» для всех пяти разделов (как и сегодня `require_permission` коротко замыкается на `role == "superadmin"`, `app/api/deps.py:73-74`) плюс эксклюзивный доступ к «Разработке» — единственная асимметрия, которая осознанно остаётся вне модели ролей.

**Бутстрап дефолтных ролей — в репозитории, дефолтных пользователей — в контейнере.** Разделение продиктовано существующим правилом AGENTS.md «`database/` must not depend on `app/api/`» (уже закреплено как правило, само используется как обоснование в `database/user_repository.py:14-16`):

1. **`RoleDatabase._ensure_schema()`** (по образцу `UserDatabase._ensure_schema()`, `database/user_repository.py:61-65`) идемпотентно сидирует только сами роли и их `role_permissions` — чистые данные, без паролей:
   - «Администратор»: `view/edit/delete = true` по всем пяти разделам (кроме «Разработки», которая вне модели);
   - «Оператор»: `obs.view = true`, `zones.view = true`, остальное `false` — по прямому пункту `PROJECT.md` («Оператор по умолчанию: Наблюдение + Зоны»).
   - Обе роли — обычные редактируемые строки таблицы `roles`, без специального флага «системная роль» — ровно как требует `PROJECT.md` («Эти роли — обычные, редактируемые, без особой логики»).
   - Идемпотентность — `INSERT ... ON CONFLICT (name) DO NOTHING`, тот же приём, что уже есть для `app_settings_revision` (`database/postgres/schema.sql:150`).

2. **`AppContainer.build()`** (не репозиторий — здесь нужен `hash_password()` из `app/api/auth_utils.py`, импорт которого недопустим внутри `database/`): после создания `role_db`/`user_db` проверяет, есть ли уже пользователь с ролью «Администратор» (идемпотентность по факту существования, тот же стиль проверки, что уже применён в `_warn_if_legacy_superadmin_row_exists`, `database/user_repository.py:68-86`); если нет — создаёт `admin`/`operator` с bcrypt-хешами дефолтных паролей и логирует **warning** уровня, аналогичный существующему предупреждению о legacy-строке суперадмина, чтобы факт «стоят дефолтные пароли» не был молча невидим при деплое (тот же дух, что и уже зафиксированная в `docs/roadmap/configuration-architecture.md` проблема P13 — «секрет по умолчанию не проверяется» — здесь она не повторяется, а явно закрывается логом).

Это сохраняет ключевое инвариантное требование из roadmap 11.3 («при любом сценарии остаётся хотя бы одна учётная запись, способная управлять пользователями») — даже если кто-то удалит роль «Администратор» и всех admin-пользователей, `superadmin` остаётся аварийным входом, способным создать нового администратора через `admin-users`-эндпоинты (он не заблокирован в `require_section` — коротко замыкается точно так же, как сегодня `require_permission`).

---

## 9. Предлагаемый порядок сборки

Зависимости обозначены явно; шаги без взаимных зависимостей можно вести параллельно.

1. **Каталог прав** (`config/permissions.py`) — без зависимостей, чистые данные, юнит-тестируется отдельно.
2. **Схема БД**: `roles`, `role_permissions`, `audit_log` + `users.role_id`/`full_name`, удаление `users.role`/`permissions` — в `schema.sql` и парных `_SCHEMA` (`tests/test_schema_sync.py` должен остаться зелёным). Зависит от (1) только по форме сидируемых данных.
3. **Репозитории**: `RoleDatabase` (+ сидирование ролей), `AuditLogDatabase`, изменения в `UserDatabase` (role_id/full_name, `find_with_permissions`). Зависит от (2).
4. **`app/api/deps.py`**: `require_section(section, action)`, резолвинг прав в `get_current_user` (JOIN на каждый запрос, без версии — §5), обновление `UserOut`/`LoginResponse` (`role_name`, `section_permissions`, `is_blocked`). Зависит от (1),(3).
5. **Массовая замена guard'ов** во всех роутерах по таблицам §6 (включая `change_password` — убрать инлайн-проверку). Самый крупный механический PR, закрывает P18/P19. Зависит от (4). Решение по контроллерам (§6, варианты A–D) можно принять и встроить в этот же шаг или отложить отдельным PR — не блокирует остальное.
6. **Бутстрап дефолтных пользователей** в `AppContainer.build()` (§8). Зависит от (3),(4).
7. **Роутер ролей** (`app/api/routers/roles.py`) + обновление `users.py` (`full_name`, `role_id` вместо `role`/`permissions`, блокировка вместо «деактивации»). Зависит от (3),(4).
8. **Аудит-лог**: `common/audit.py` + точечные вызовы `record_audit(...)` в обработчиках, уже тронутых на шаге 5 (дёшево добавить в тот же диф, раз guard-строка обработчика и так редактируется). Зависит от (2),(3),(5).
9. **Перепроверка в SSE/MJPEG-потоках** (§5) — `events.py`, `debug.py`, `channels.py` (превью). Зависит от (4).
10. **Фронтенд**: `GET /api/permissions/catalogue` вместо `AVAILABLE_PERMISSIONS`, `applyTabVisibility` на `section_permissions`, редактор ролей (чекбоксы), правки `users.js` (ФИО, блокировка, выбор роли). Зависит от (4),(7).
11. **Тесты и документация**: параметризованная матрица «субъект → эндпоинт → ожидаемый код» (аналог требования 11.5 из roadmap), обновление `docs/technical/auth.md`, `docs/technical/endpoints.md`, раздел «Authorization Model» в `AGENTS.md`, README. Зависит от всего выше.

---

## 10. Итоговая сводка по пометкам «гипотеза / открытый вопрос»

| # | Вопрос | Статус |
|---|---|---|
| 1 | «Настройки» — тройка В/И/У или один флаг | **Гипотеза**: рекомендую тройку (даёт смысл «Удалению» — удаление канала/списка как часть настроек); нужно подтверждение владельца при планировании |
| 2 | Куда едет ручное срабатывание реле контроллера | **Открытое решение** — 4 варианта в §6, ни один не выбран, требуется отдельное исследование аналогов (уже зафиксировано как отложенное в `PROJECT.md`) |
| 3 | Управление пользователями/ролями — отдельный уровень `admin-users` или часть `settings.edit` | **Рекомендация с обоснованием** (риск самоэскалации) — не жёсткое решение, `admin-users` уже существует как неиспользуемый уровень в `deps.py` |
| 4 | Нужна ли иерархия ролей (защита от самоэскалации прав) | **Открытый вопрос**, не поднят в `PROJECT.md` — фиксирую для обсуждения на планировании |
| 5 | `POST /api/data/backup/database/restore` — оставить на `settings.edit` или изолировать сильнее (superadmin) | **Рекомендация к обсуждению**, не решение — блэст-радиус несопоставим с остальными действиями раздела |
| 6 | `POST /api/data/retention/run` — `edit` или `delete` | **Гипотеза**: предлагаю `delete` (необратимо стирает данные), финальный выбор — на планировании |
| 7 | JWT-версия/кэш прав vs чтение из БД на каждый запрос | **Рекомендация, не гипотеза** — чтение из БД без версии обосновано существующим поведением `get_current_user` (см. §5); альтернатива зафиксирована, но не рекомендуется на этом масштабе |
| 8 | Новый столбец `is_blocked` | **Рекомендация против** — `is_active` уже реализует нужную семантику, лишний столбец не нужен |

---

*Architecture research for: RBAC/аудит/блокировка в Web ANPR System*
*Researched: 2026-09-24*
