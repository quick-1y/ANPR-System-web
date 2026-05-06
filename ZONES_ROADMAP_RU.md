# ZONES_ROADMAP.md
# Функционал парковочных зон — дорожная карта проектирования и реализации

**Система:** ANPR System v0.8 (web)  
**Функционал:** Опциональный режим зон для отслеживания въезда/выезда в парковочные зоны  
**Предпосылка по БД:** Чистая пустая база данных — скрипты миграции не требуются  
**Дата:** 2026-04-15

> Актуализация 2026-05-06: события зон теперь хранят отдельные поля въезда и выезда: `channel_id_entry` / `channel_id_exit`, `frame_path_entry` / `frame_path_exit`, `plate_path_entry` / `plate_path_exit`. Выездной канал обновляет найденную открытую запись и поднимает её вверх по `time`; если открытого въезда нет или номер не прошёл eligibility, создаётся отдельное событие выездной попытки без вызова реле.

---

## Оглавление

1. [Анализ влияния на текущее состояние](#1-анализ-влияния-на-текущее-состояние)
2. [Проектирование модели данных](#2-проектирование-модели-данных)
3. [Изменения архитектуры бэкенда](#3-изменения-архитектуры-бэкенда)
4. [Изменения потока обработки событий](#4-изменения-потока-обработки-событий)
5. [Логика принятия решения по контроллеру / реле](#5-логика-принятия-решения-по-контроллеру--реле)
6. [Изменения API](#6-изменения-api)
7. [Изменения фронтенда](#7-изменения-фронтенда)
8. [Удаление зоны и поведение сброса](#8-удаление-зоны-и-поведение-сброса)
9. [Совместимость с режимом без зон](#9-совместимость-с-режимом-без-зон)
10. [Краевые случаи и риски](#10-краевые-случаи-и-риски)
11. [Поэтапный план реализации](#11-поэтапный-план-реализации)
12. [План тестирования](#12-план-тестирования)
13. [План обновления документации](#13-план-обновления-документации)

---

## 1. Анализ влияния на текущее состояние

### Что меняется и почему

| Область | Файл(ы) | Характер изменения |
|---|---|---|
| Схема БД | `database/postgres/schema.sql` | Переработка таблицы events; добавление таблицы zones; добавление колонок зон в channels |
| Репозиторий событий | `database/postgres_event_repository.py` | Все запросы, `_to_dict`, новый метод `update_event_exit` |
| Репозиторий каналов | `database/channel_repository.py` | Добавление колонок зон в схему, `SELECT`, `INSERT`, `UPDATE`, `_row_to_dict`, `_normalize` |
| Runtime каналов | `runtime/channel_runtime.py` | Логика маршрутизации зон в `_run_channel`; каналы выезда пропускают `insert`, вместо этого вызывают `update` |
| Автоматизация контроллеров | `controllers/service.py` | Логика принятия решения по реле по структуре не меняется; нужно передавать корректный dict события для канала выезда |
| Контейнер приложения | `app/api/container.py` | Подключение `ZoneDatabase`; передача в processor канала для проверки доступности зоны |
| API роутеры | `app/api/routers/` | Новый роутер `zones.py`; обновление `channels.py` и `events.py` |
| API схемы | `app/api/schemas.py` | Новые payload’ы для зон; расширение `ChannelConfigPayload` |
| Фронтенд | `app/web/js/`, `app/web/index.html` | Новый модуль `zones.js`; обновление `channels.js`, `events.js`, `journal.js`, `app.js` |

### Что НЕ меняется

- `ANPRPipeline`, `TrackAggregator`, `YOLODetector`, `CRNNRecognizer` — без изменений  
- `ControllerAutomationService._resolve_channel_controller_action` — логика принятия решения по реле не меняется  
- Аутентификация, пользователи, списки, клиенты, контроллеры, настройки, debug — без изменений  
- `EventBus`, `DebugRegistry` — без изменений  
- `ChannelProcessor.start/stop/restart`, `_filter_detections_by_roi` — без изменений  
- Оценка направления и фильтрация по направлению — без изменений  

### Ключевые точки связности, которыми нужно управлять осторожно

**`runtime/channel_runtime.py` → `_run_channel()`** — это единственная функция, отвечающая за создание событий. Вся логика зон для ветвления въезд/выезд должна находиться здесь или вызываться отсюда. Сейчас функция безусловно вызывает `self._events_db.insert_event()`. Для каналов выезда это станет условным поведением.

**`ControllerAutomationService.dispatch_event()`** читает `event["plate"]` и `event["channel_id"]` из dict события, затем загружает конфиг канала. Для каналов выезда новое событие не создаётся; при этом мы всё равно должны вызвать `self._event_callback(event)` с синтетическим dict события, чтобы реле сработало корректно. Этот dict обязан содержать `channel_id`, `plate` и `direction`.

**`database/postgres_event_repository.py`** содержит жёстко заданное имя колонки `timestamp` во всех запросах и в `_to_dict`. Переименование её в `time` требует обновления каждого запроса, каждой ссылки на индекс, курсора пагинации `(timestamp, id) < (%s, %s)` и фильтра `fetch_for_export`. Это изменение с наибольшим количеством правок во всём проекте.

---

## 2. Проектирование модели данных

### 2.1 Таблица zones (новая)

```sql
CREATE TABLE IF NOT EXISTS zones (
    id   SERIAL PRIMARY KEY,
    name TEXT    NOT NULL,
    capacity INTEGER NOT NULL DEFAULT 0
);
```

Без soft-delete. Зоны удаляются явно по действию оператора. Каскад на каналы реализуется через FK.

**Примечание по расчёту свободных мест:**  
`free_spaces = capacity - COUNT(*) FROM events WHERE zone_id = zone.id AND time_exit IS NULL`  
Этот запрос выполняется во время чтения (endpoint деталей зоны). Он будет эффективен только при наличии индекса по `(zone_id, time_exit)`. Не нужно кешировать это значение в таблице zones — это потребовало бы обновлять его при каждой вставке события и каждом обновлении выезда, что создаст проблему синхронизации при интенсивной записи.

### 2.2 Таблица events (переработанная)

Полностью заменить текущую таблицу events. Ниже приведено обоснование по каждой колонке.

```sql
CREATE TABLE IF NOT EXISTS events (
    id           BIGSERIAL    PRIMARY KEY,
    time         TIMESTAMPTZ  NOT NULL,
    channel_id   INTEGER,
    plate        TEXT         NOT NULL,
    plate_display TEXT,
    country      TEXT,
    confidence   DOUBLE PRECISION,
    source       TEXT,
    frame_path   TEXT,
    plate_path   TEXT,
    direction    TEXT,
    client_id    BIGINT,
    zone_id      INTEGER,
    time_entry   TIMESTAMPTZ,
    time_exit    TIMESTAMPTZ
);
```

**Удалённые колонки:**  
- `channel` (TEXT) — избыточна по отношению к `channel_id`; имя канала во время запроса берётся через join или lookup на фронтенде. Весь существующий код, который фильтрует/сортирует по текстовому `channel`, должен быть переведён на `channel_id`.

**Переименованные колонки:**  
- `timestamp → time` — `timestamp` является зарезервированным словом SQL; `time` семантически точнее и не требует экранирования. Все запросы, индексы, курсоры пагинации и API-ответы должны использовать `time`.

**Новые колонки:**  
- `zone_id INTEGER` — `NULL` означает, что зона не участвовала. `0` — sentinel-значение, означающее «автомобиль выехал и теперь находится вне зоны». Значения `> 0` соответствуют `zone.id`. Внешний ключ для `zone_id` не нужен: события — это исторические записи, и они должны переживать удаление зоны.
- `time_entry TIMESTAMPTZ` — записывается, когда автомобиль въезжает через канал въезда, работающий с зоной (с учётом допустимости по режиму списков).
- `time_exit TIMESTAMPTZ` — записывается, когда автомобиль выезжает через канал выезда, работающий с зоной (с учётом допустимости по режиму списков).

**Индексы:**

```sql
CREATE INDEX IF NOT EXISTS idx_events_plate
    ON events(plate);

CREATE INDEX IF NOT EXISTS idx_events_time_id_desc
    ON events(time DESC, id DESC);

CREATE INDEX IF NOT EXISTS idx_events_channel_id_time_id_desc
    ON events(channel_id, time DESC, id DESC);

CREATE INDEX IF NOT EXISTS idx_events_client_id
    ON events(client_id) WHERE client_id IS NOT NULL;

-- Для подсчёта заполненности зоны (расчёт свободных мест)
CREATE INDEX IF NOT EXISTS idx_events_zone_active
    ON events(zone_id) WHERE zone_id IS NOT NULL AND zone_id > 0 AND time_exit IS NULL;

-- Для поиска по номеру на канале выезда: найти самый свежий активный въезд для номера в зоне
CREATE INDEX IF NOT EXISTS idx_events_plate_zone_open
    ON events(plate, zone_id, time DESC)
    WHERE zone_id > 0 AND time_exit IS NULL;
```

### 2.3 Таблица channels (расширение)

Добавить две колонки в существующий DDL `channels` в `channel_repository.py`:

```sql
zone_id           INTEGER REFERENCES zones(id) ON DELETE SET NULL,
zone_channel_type TEXT    -- 'entry', 'exit' или NULL (без участия в зоне)
```

`ON DELETE SET NULL` на `zone_id` гарантирует, что при удалении зоны все затронутые каналы автоматически потеряют привязку к зоне. `zone_channel_type` затем также должен быть очищен до `NULL` в той же транзакции — это будет обработано в методе удаления `ZoneDatabase`.

**Допустимые значения `zone_channel_type`:** `'entry'`, `'exit'`, `NULL`  
Ограничение задаётся на уровне валидации приложения в `_normalize()` и в Pydantic-схеме. DB CHECK constraint пока не нужен.

### 2.4 Полный schema.sql

Файл `database/postgres/schema.sql` поднимает все таблицы при старте через `PooledDatabase._ensure_schema()`. Полное новое содержимое:

```sql
-- ── Zones ────────────────────────────────────────────────────────────
CREATE TABLE IF NOT EXISTS zones (
    id       SERIAL  PRIMARY KEY,
    name     TEXT    NOT NULL,
    capacity INTEGER NOT NULL DEFAULT 0
);

-- ── Events ───────────────────────────────────────────────────────────
CREATE TABLE IF NOT EXISTS events (
    id            BIGSERIAL    PRIMARY KEY,
    time          TIMESTAMPTZ  NOT NULL,
    channel_id    INTEGER,
    plate         TEXT         NOT NULL,
    plate_display TEXT,
    country       TEXT,
    confidence    DOUBLE PRECISION,
    source        TEXT,
    frame_path    TEXT,
    plate_path    TEXT,
    direction     TEXT,
    client_id     BIGINT,
    zone_id       INTEGER,
    time_entry    TIMESTAMPTZ,
    time_exit     TIMESTAMPTZ
);

CREATE INDEX IF NOT EXISTS idx_events_plate
    ON events(plate);
CREATE INDEX IF NOT EXISTS idx_events_time_id_desc
    ON events(time DESC, id DESC);
CREATE INDEX IF NOT EXISTS idx_events_channel_id_time_id_desc
    ON events(channel_id, time DESC, id DESC);
CREATE INDEX IF NOT EXISTS idx_events_client_id
    ON events(client_id) WHERE client_id IS NOT NULL;
CREATE INDEX IF NOT EXISTS idx_events_zone_active
    ON events(zone_id) WHERE zone_id IS NOT NULL AND zone_id > 0 AND time_exit IS NULL;
CREATE INDEX IF NOT EXISTS idx_events_plate_zone_open
    ON events(plate, zone_id, time DESC)
    WHERE zone_id > 0 AND time_exit IS NULL;

-- ── Users (auth) ─────────────────────────────────────────────────────
CREATE TABLE IF NOT EXISTS users (
    id                  BIGSERIAL PRIMARY KEY,
    login               TEXT      NOT NULL UNIQUE,
    password            TEXT      NOT NULL,
    role                TEXT      NOT NULL DEFAULT 'operator',
    permissions         JSONB     NOT NULL DEFAULT '[]'::jsonb,
    is_active           BOOLEAN   NOT NULL DEFAULT TRUE,
    created_at          TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at          TIMESTAMPTZ NOT NULL DEFAULT now(),
    password_changed_at TIMESTAMPTZ DEFAULT NULL
);

CREATE UNIQUE INDEX IF NOT EXISTS idx_users_login ON users(login);
```

*(Таблицы channel, list, client, controller создаются своими `_schema_sql()` внутри репозиториев и остаются прежними по структуре, за исключением двух новых колонок зон, добавляемых в `channel_repository.py`.)*

---

## 3. Изменения архитектуры бэкенда

### 3.1 Новый файл: `database/zones_repository.py`

**Ответственность:**  
- CRUD для таблицы `zones`  
- Каскадное снятие зоны с каналов (`zone_id = NULL`, `zone_channel_type = NULL`) при удалении зоны  
- Запрос заполненности зоны: количество активных (ещё не завершённых выездом) въездов по зоне  

**Ключевые методы:**

```python
class ZoneDatabase(PooledDatabase):
    def list_zones(self) -> list[dict]
    def get_zone(self, zone_id: int) -> dict | None
    def create_zone(self, name: str, capacity: int) -> int
    def update_zone(self, zone_id: int, name: str, capacity: int) -> bool
    def delete_zone(self, zone_id: int) -> bool
        # В одной транзакции:
        #   UPDATE channels SET zone_id=NULL, zone_channel_type=NULL WHERE zone_id=%s
        #   DELETE FROM zones WHERE id=%s
    def get_channels_for_zone(self, zone_id: int) -> list[dict]
        # SELECT id, name FROM channels WHERE zone_id = %s
    def get_zone_occupancy(self, zone_id: int) -> int
        # SELECT COUNT(*) FROM events WHERE zone_id = %s AND time_exit IS NULL
```

`ZoneDatabase` использует тот же DSN и общий пул, что и остальные репозитории.

### 3.2 Обновления в `database/postgres_event_repository.py`

**Обновление `_to_dict`** — сопоставить новые позиции колонок. Удалить `channel` (text). Добавить `zone_id`, `time_entry`, `time_exit`.

**Изменение сигнатуры `insert_event`** — добавить опциональные `zone_id`, `time_entry`:

```python
def insert_event(
    self,
    plate: str,
    channel_id: int | None = None,
    ...,
    zone_id: int | None = None,
    time_entry: str | None = None,
) -> int
```

**Новый метод `find_active_entry_and_write_exit`:**

```python
def find_active_entry_and_write_exit(
    self,
    plate: str,
    zone_id: int,
    time_exit_iso: str,
) -> int | None:
    """
    Найти самое свежее открытое событие въезда для `plate` в `zone_id`
    (где time_exit IS NULL), записать time_exit и установить zone_id = 0.
    Возвращает id обновлённого события или None, если открытый въезд не найден.
    """
```

SQL:
```sql
UPDATE events
SET time_exit = %s, zone_id = 0
WHERE id = (
    SELECT id FROM events
    WHERE plate = %s
      AND zone_id = %s
      AND time_exit IS NULL
    ORDER BY time DESC
    LIMIT 1
)
RETURNING id
```

**Все существующие SELECT-запросы** — заменить `timestamp` на `time` везде. Обновить курсор пагинации `(timestamp, id) < (%s, %s)` → `(time, id) < (%s, %s)`. Удалить колонку `channel` из всех списков SELECT. Добавить `zone_id, time_entry, time_exit` во все списки SELECT.

**`fetch_for_export`** — удалить параметр фильтрации по текстовому `channel`. Оставить фильтр по `channel_id`. Обновить ссылки на колонки.

### 3.3 Обновления в `database/channel_repository.py`

**`_SCHEMA`** — добавить в `CREATE TABLE`:

```sql
zone_id           INTEGER,
zone_channel_type TEXT
```

**`_SELECT_COLS`** — дописать `, zone_id, zone_channel_type`

**`_row_to_dict`** — сопоставить два новых поля с позициями 28, 29:

```python
"zone_id": row[28],
"zone_channel_type": row[29],
```

**`_normalize`** — добавить блок нормализации:

```python
zone_id = result.get("zone_id")
if zone_id in (None, 0, "", "0"):
    zone_id = None
else:
    try:
        zone_id = int(zone_id)
        if zone_id <= 0:
            zone_id = None
    except (TypeError, ValueError):
        zone_id = None
result["zone_id"] = zone_id

zone_type = str(result.get("zone_channel_type") or "").strip().lower()
if zone_type not in ("entry", "exit"):
    zone_type = None
# Если зона не назначена, тип тоже очищаем
if zone_id is None:
    zone_type = None
result["zone_channel_type"] = zone_type
```

**`create_channel` и `update_channel`** — включить `zone_id`, `zone_channel_type` в `INSERT` и `UPDATE`.

### 3.4 Обновления в `app/api/container.py`

Импортировать и подключить `ZoneDatabase`:

```python
from database.zones_repository import ZoneDatabase

@dataclass
class AppContainer:
    ...
    zone_db: ZoneDatabase
```

В `AppContainer.build()`:
```python
zone_db = ZoneDatabase(dsn)
```

В `AppContainer.refresh_storage_clients()`:
```python
self.zone_db = ZoneDatabase(dsn)
```

Передавать `zone_db` в processor каналов:
```python
return ChannelProcessor(
    ...
    events_db=self.events_db,
    lists_db=self.lists_db,
    zones_db=self.zone_db,
)
```

### 3.5 Обновления в `runtime/channel_runtime.py`

Подробная логика обработки описана в разделе 4.

**Изменение конструктора** — добавить параметр `zones_db` (опционально для обратной совместимости тестов):

```python
def __init__(self, ..., zones_db=None) -> None:
    ...
    self._zones_db = zones_db
```

---

## 4. Изменения потока обработки событий

### 4.1 Текущий поток (упрощённо)

```
номер обнаружен
  → найти client_id
  → собрать dict события
  → insert_event() → возвращает event_id
  → _event_callback(event)  →  ControllerAutomationService.dispatch_event()
                             →  EventBus.publish()
```

### 4.2 Поток с учётом зон

Проверка зоны выполняется в `_run_channel()` после распознавания номера, до записи в БД. Конфиг канала загружается один раз при старте потока (`channel = dict(ctx.channel)`), поэтому `zone_id` и `zone_channel_type` доступны.

```
номер обнаружен
  → найти client_id через lists_db.find_client_by_plate()
  → zone_id = channel.get("zone_id")
  → zone_type = channel.get("zone_channel_type")   # 'entry', 'exit' или None

  ВЕТКА A: zone_id is None или zone_type is None
    → текущее поведение без изменений
    → insert_event(plate, ..., zone_id=None, time_entry=None)
    → _event_callback(event)

  ВЕТКА B: zone_type == 'entry'
    → определить zone_eligible = _resolve_zone_eligibility(channel, plate)
    → если zone_eligible:
        zone_fields = {"zone_id": zone_id, "time_entry": event_ts.isoformat()}
    → иначе:
        zone_fields = {}
    → insert_event(plate, ..., **zone_fields)
    → _event_callback(event)   [логика реле работает как обычно]

  ВЕТКА C: zone_type == 'exit'
    → определить zone_eligible = _resolve_zone_eligibility(channel, plate)
    → собрать relay_event = {channel_id, plate, direction, ...}  [для запуска реле]
    → если zone_eligible:
        updated_id = events_db.find_active_entry_and_write_exit(plate, zone_id, time_exit_iso)
        if updated_id:
            relay_event["id"] = updated_id
        # Если открытый въезд не найден: реле всё равно срабатывает, но DB-запись для exit-полей не выполняется
    → _event_callback(relay_event)   [логика реле работает как обычно]
    → НЕ вызывать insert_event()
```

### 4.3 Хелпер `_resolve_zone_eligibility(channel, plate)`

Это приватный метод `ChannelProcessor`. Он зеркалит логику принятия решения по реле из `ControllerAutomationService._resolve_channel_controller_action`, но возвращает только допустимость записи полей зоны (True/False). Он НЕ влияет на поведение реле — реле по-прежнему управляется отдельно automation service.

```python
def _resolve_zone_eligibility(self, channel: dict, plate: str) -> bool:
    """
    Определяет, должны ли поля zone_id и time_entry/time_exit
    быть записаны в событие, исходя из list_filter_mode.
    Для номеров из чёрного списка всегда возвращает False.
    """
    if self._lists_db is None:
        return True  # нет list db, считаем это режимом "all"

    if self._lists_db.plate_in_list_type(plate, "black"):
        return False

    mode = str(channel.get("list_filter_mode") or "all").strip().lower()
    if mode == "all":
        return True
    if mode == "whitelist":
        return self._lists_db.plate_in_list_type(plate, "white")
    if mode == "custom":
        list_ids = ControllerAutomationService._normalize_positive_int_ids(
            channel.get("list_filter_list_ids")
        )
        return self._lists_db.plate_in_lists(plate, list_ids)
    return True  # fallback
```

**Почему эта логика дублируется вместо прямого вызова automation service?**  
Automation service запускается после callback события и работает уже по готовому dict события. Допустимость записи полей зоны нужно знать *до* вставки (или обновления). Вынесение логики в общую утилиту, например `controllers/list_filter.py`, — это чистый вариант, если нежелательно дублирование, но для данного объёма задачи такой inline-подход остаётся понятным.

### 4.4 Callback события для каналов выезда

Для каналов выезда `_event_callback` вызывается с синтетическим dict для запуска реле, без нового `id` от вставки (потому что вставки нет). `ControllerAutomationService.dispatch_event()` читает только `channel_id`, `plate` и `direction` из dict события — эти поля всегда есть. Вызов `event_bus.publish()` также получит этот dict; фронтенд покажет его как live event уведомление. Это корректное поведение — оператор всё равно видит, что автомобиль проехал через выездные ворота.

---

## 5. Логика принятия решения по контроллеру / реле

### Что остаётся неизменным

`ControllerAutomationService._resolve_channel_controller_action()` не модифицируется. Он читает `list_filter_mode`, проверяет чёрный список, проверяет белый список или принадлежность выбранным спискам и возвращает `(allowed, reason)`. Это gate для реле, и он остаётся единственным источником истины для решения, срабатывать реле или нет.

Фильтр по направлению в `dispatch_event()` также не меняется.

### Что меняется для каналов выезда

Для каналов выезда реле по-прежнему запускается через `_event_callback(relay_event)`. Передаваемый dict для реле должен содержать:
- `channel_id` — используется для загрузки конфига канала  
- `plate` — используется для проверки принадлежности спискам  
- `direction` — используется фильтром направления  

Все три значения доступны из результата детекции и контекста канала. Изменений в `ControllerAutomationService` не требуется.

### Матрица поведения реле

| Тип канала | Допустима запись зоны? | В чёрном списке? | Направление совпало? | Реле срабатывает? | Поля зоны записываются? |
|---|---|---|---|---|---|
| Без зоны | — | Нет | Да | Да (по режиму) | Нет |
| Въезд | Да | Нет | Да | Да (по режиму) | Да |
| Въезд | Нет | Нет | Да | Да (по режиму) | Нет |
| Въезд | — | Да | Любое | Нет | Нет |
| Выезд | Да | Нет | Да | Да (по режиму) | Да (через update) |
| Выезд | Нет | Нет | Да | Да (по режиму) | Нет |
| Выезд | — | Да | Любое | Нет | Нет |

Колонка про реле полностью определяется `ControllerAutomationService`, и эта логика уже корректна. Допустимость записи полей зоны отдельно определяется через `_resolve_zone_eligibility`.

---

## 6. Изменения API

### 6.1 Новый роутер: `app/api/routers/zones.py`

Зарегистрировать в `app/api/main.py` рядом с существующими роутерами.

| Метод | Путь | Описание |
|---|---|---|
| `GET` | `/api/zones` | Получить список всех зон (id, name, capacity, occupancy) |
| `POST` | `/api/zones` | Создать зону |
| `GET` | `/api/zones/{zone_id}` | Получить детали зоны: name, capacity, occupancy (свободные места), список назначенных каналов |
| `PUT` | `/api/zones/{zone_id}` | Обновить имя/вместимость зоны |
| `DELETE` | `/api/zones/{zone_id}` | Удалить зону (каскадно обнулить zone_id/type у каналов) |

**Форма ответа `GET /api/zones`** для одной зоны:
```json
{
  "id": 1,
  "name": "Парковка А",
  "capacity": 50,
  "occupied": 12,
  "free": 38
}
```
`occupied` = `zone_db.get_zone_occupancy(id)`. Вычисляется на каждый запрос, не хранится.

**`DELETE /api/zones/{zone_id}`** — перед удалением нужно вернуть в ответе список затронутых каналов для подтверждения на фронтенде. Бэкенд всегда выполняет удаление + каскад в одной транзакции, когда endpoint вызван. Фронтенд отвечает за показ предупреждения до вызова endpoint.

**Ответ `GET /api/zones/{zone_id}`** дополнительно содержит:
```json
{
  "channels": [{"id": 3, "name": "Въезд 1"}, {"id": 4, "name": "Выезд 1"}]
}
```

### 6.2 Обновление: `app/api/routers/events.py`

- Все ответы запросов должны включать новые поля: `zone_id`, `time_entry`, `time_exit`
- Удалить `channel` (text) из dict ответов
- Переименование колонок в параметрах `fetch_journal_page`: `before_ts` по-прежнему можно использовать внутри Python, просто теперь он должен маппиться на колонку `time`
- SSE stream события должны включать новые поля (они приходят из dict события, собранного в runtime)

### 6.3 Обновление: `app/api/routers/channels.py`

`PUT /api/channels/{channel_id}/config` — валидировать поле `zone_id`: если оно передано и не `null`, проверить существование зоны через `container.zone_db.get_zone(zone_id)`. Если зона не найдена — возвращать HTTP 400.

Добавить метод в `AppContainer`:
```python
def validate_channel_zone_binding(self, payload: dict) -> None:
    zone_id = payload.get("zone_id")
    if zone_id is None:
        payload["zone_channel_type"] = None
        return
    if not self.zone_db.get_zone(int(zone_id)):
        raise HTTPException(status_code=400, detail=f"Зона #{zone_id} не найдена")
```

### 6.4 Обновление: `app/api/schemas.py`

**Новые схемы:**

```python
class ZonePayload(BaseModel):
    name: str
    capacity: int = Field(default=0, ge=0)

class ZoneUpdatePayload(BaseModel):
    name: str
    capacity: int = Field(ge=0)
```

**Обновлённый `ChannelConfigPayload`:**

```python
zone_id: Optional[int] = None
zone_channel_type: Optional[str] = Field(
    default=None,
    pattern="^(entry|exit)$"
)
```

Валидатор `zone_channel_type`: если `zone_id` равен `None`, то и `zone_channel_type` должен быть `None`.

---

## 7. Изменения фронтенда

### 7.1 Обзор затронутых файлов

| Файл | Тип | Изменение |
|---|---|---|
| `app/web/index.html` | HTML | Добавить вкладку Zones в сайдбар под группой Observation |
| `app/web/js/app.js` | JS | Зарегистрировать route вкладки zones, импортировать модуль zones |
| `app/web/js/zones.js` | JS (новый) | Полноценный UI управления зонами |
| `app/web/js/channels.js` | JS | Добавить секцию настройки зоны в форму конфига канала |
| `app/web/js/events.js` | JS | Показ `time_entry`, `time_exit`, бейджа зоны в live events |
| `app/web/js/journal.js` | JS | Показ новых полей события в журнале; обновить колонку `channel`, чтобы использовать lookup имени |
| `app/web/js/api.js` | JS | Добавить методы API для зон |

### 7.2 Новая вкладка: Zones

Расположение в сайдбаре: под группой **Observation**, после **Events**.

**`app/web/js/zones.js`** — структура модуля:

```
zones.js
  ├── loadZones()          → GET /api/zones
  ├── renderZoneList()     → отрисовать карточки зон
  ├── openZoneSettings()   → показать панель деталей зоны
  ├── createZone()         → POST /api/zones (только имя, вместимость опциональна)
  ├── updateZone()         → PUT /api/zones/{id}
  ├── deleteZone()         → pre-check каналов через GET /api/zones/{id},
  │                          показать confirm modal со списком затронутых каналов,
  │                          затем DELETE /api/zones/{id}
  └── renderOccupancy()    → показать capacity / occupied / free
```

**Макет карточки зоны:**
```
┌─────────────────────────────────────┐
│ Парковка А                          │
│ Вместимость: 50  Занято: 12  Свободно: 38 │
│                        [⚙ Настройки] [✕ Удалить] │
└─────────────────────────────────────┘
```

**Поток удаления:**
1. Пользователь нажимает Delete  
2. Фронтенд вызывает `GET /api/zones/{id}`, чтобы получить список затронутых каналов  
3. Если какие-то каналы используют эту зону, показывается warning modal со списком имён каналов  
4. После подтверждения вызывается `DELETE /api/zones/{id}`  
5. Для каждого затронутого канала бэкенд уже очистил `zone_id` — фронтенд просто перезагружает список каналов  

**Отображение заполненности:**  
Свободные места вычисляются на сервере (`capacity - occupied`). Показывать в UI как: `Свободно: N / Вместимость: M`.  
В интерфейсе стоит указать, что число свободных мест обновляется по мере въезда/выезда автомобилей в реальном времени, но для v1 лучше использовать ручное обновление или reload при активации вкладки.

### 7.3 Секция зоны в настройках канала

В `channels.js`, внутри формы настройки канала, добавить секцию **Зона** ниже секции Controller:

```
[ Зона ─────────────────────────────── ]
  Зона:          [ dropdown / Без зоны ]
  Тип канала:    [ Въезд / Выезд / — ]
  Режим фильтра: (использует существующий list_filter_mode — без изменений)
```

Dropdown зоны загружается из `GET /api/zones`.  
`Тип канала` активен только когда выбрана зона.  
Если в зоне выбрано "Без зоны" (`None`), `zone_channel_type` также очищается.

### 7.4 Отображение событий и журнала

**Live events (`events.js`):**  
- Добавить бейдж зоны: если `zone_id > 0`, показывать бейдж с именем зоны (для этого нужен mapping `zone_id → name`; список зон можно загрузить при init)  
- Показать `time_entry` или `time_exit`, если они есть  

**Журнал (`journal.js`):**  
- Удалить текстовую колонку `channel` — вместо неё показывать имя канала через lookup из списка каналов (он уже загружается в state)  
- Добавить опциональные колонки: `Зона`, `Въезд`, `Выезд`  
- Эти колонки по умолчанию можно скрыть, чтобы не загромождать таблицу; добавить переключатель видимости колонок  

---

## 8. Удаление зоны и поведение сброса

**Триггер:** `DELETE /api/zones/{zone_id}`

**Операции в БД (одна транзакция):**
1. `UPDATE channels SET zone_id = NULL, zone_channel_type = NULL WHERE zone_id = $1`
2. `DELETE FROM zones WHERE id = $1`

**Что происходит с существующими событиями:**  
События с `zone_id = {deleted_zone_id}` **не изменяются**. Это исторические записи, и они должны сохраняться для аудита. Если запрос фильтрует по зоне, он просто больше не найдёт соответствующих каналов, но сами события по-прежнему можно будет запросить напрямую по `zone_id`, если это понадобится.

**Поведение фронтенда:**  
После удаления зоны список каналов должен быть перезагружен, чтобы затронутые каналы показывали "без зоны" в своём конфиге. Вкладка зон должна удалить зону из списка.

**Нет защиты от orphan для `zone_id` в events:**  
Поскольку в событиях `zone_id` используется как денормализованное значение (без FK), никакой cascade не нужен и не подходит. Значение `0` уже используется как sentinel «выехал». ID удалённой зоны становится ссылкой на уже несуществующую зону, но это всё равно имеет смысл как исторические данные (например, когда-то это была зона #3, в которую автомобиль въехал).

---

## 9. Совместимость с режимом без зон

**Инвариант:** Если `channel.zone_id IS NULL` или `channel.zone_channel_type IS NULL`, канал ведёт себя ровно так же, как и сейчас, без каких-либо наблюдаемых отличий.

**На уровне БД:**  
- `zone_id`, `time_entry`, `time_exit` — nullable и по умолчанию `NULL`  
- Ни один существующий запрос по событиям не ломается; все новые колонки являются добавочными  

**На уровне runtime:**  
`_run_channel()` в начале обработки события проверяет `zone_id = channel.get("zone_id")`. Если это `None`, он пропускает всё ветвление по зонам и вызывает `insert_event()` с теми же аргументами, что и сейчас, плюс `zone_id=None, time_entry=None` (это и так значения по умолчанию).

**На уровне API:**  
Существующий `ChannelConfigPayload` расширяется опциональными полями с дефолтом `None`. Клиенты, которые не передают поля зоны, получают каналы, где поля зоны равны `None` — то есть поведение прежнее.

**На уровне фронтенда:**  
`events.js` и `journal.js` проверяют `if (event.zone_id && event.zone_id > 0)` перед рендером UI-элементов зоны. Колонка зоны в журнале по умолчанию скрыта.

---

## 10. Краевые случаи и риски

### 10.1 Выезд без соответствующего события въезда

**Сценарий:** Автомобиль выезжает через канал выезда с зоной, но в `events` нет события въезда для этого номера в этой зоне (например, автомобиль въехал до включения функционала или канал въезда был недоступен).

**Поведение:** `find_active_entry_and_write_exit()` возвращает `None`. Запись в БД для `time_exit` не выполняется. Логика реле при этом всё равно проходит через `_event_callback`. Оператор видит проезд номера в live view.

**Уровень риска:** Низкий. Это ожидаемое поведение во время первичного внедрения и после простоев.

### 10.2 Несколько открытых въездов для одного номера

**Сценарий:** Один и тот же номер дважды проходит через канал въезда без промежуточного выезда. Оба события существуют с `time_exit IS NULL`.

**Поведение:** `find_active_entry_and_write_exit()` использует `ORDER BY time DESC LIMIT 1` — закрывается только самый свежий открытый въезд. Более старый остаётся открытым.

**Уровень риска:** Средний. Это может приводить к завышенному подсчёту занятости. Для v1 это допустимо; нужно задокументировать как известное ограничение. Будущее улучшение: при новом въезде сначала проверять, есть ли уже открытый въезд для этого номера в этой зоне, и закрывать его.

### 10.3 Коллизия sentinel-значения `zone_id = 0`

**Сценарий:** `zone_id = 0` означает «выехал». Если бы когда-либо существовала зона с `id = 0`, это создало бы двусмысленность.

**Решение:** `SERIAL`-ключи начинаются с 1, никогда не с 0. Значение 0 безопасно как sentinel.

### 10.4 Влияние удаления колонки `channel` на экспорт

Существующий `fetch_for_export` принимает параметр фильтрации по текстовому `channel`. После удаления этой колонки фильтр нужно удалить или заменить на `channel_id`. Endpoint экспорта данных (`POST /api/data/export/bundle`) в `app/api/routers/data.py` должен быть обновлён и перестать использовать текстовый фильтр `channel`.

**Уровень риска:** Средний. Нужно проверить endpoint экспорта и `DataLifecycleService` на любые ссылки на колонку `channel`.

### 10.5 Переименование колонки `timestamp` ломает пагинацию журнала

Курсорная пагинация в `fetch_journal_page` использует `(timestamp, id) < (%s, %s)`. Это составной курсор, и его нужно обновить до `(time, id) < (%s, %s)`.

Параметры API `before_ts` и `start_ts`/`end_ts` — это имена параметров в Python, а не имена колонок, их менять не нужно. Меняются только SQL-строки запросов.

**Уровень риска:** Низкий. Это механическое переименование, но его легко пропустить, особенно в export-запросе, так как у него свой отдельный `WHERE` block. Нужно проверить каждый query string в файле.

### 10.6 SSE event dict для каналов выезда

Для каналов выезда `_event_callback` вызывается без предварительного `insert_event`. В dict события нет поля `id`. `EventBus.publish()` отправит этот dict SSE-клиентам. Фронтенд в `events.js` не должен падать, если `event.id` отсутствует у событий выездного канала.

**Решение:** Устанавливать `event["id"] = updated_id or None` и делать защиту на фронтенде: `const eventId = event.id ?? null`.

### 10.7 Подсчёт заполненности зоны под нагрузкой

`get_zone_occupancy()` выполняет `COUNT(*)` на каждый вызов `GET /api/zones`. При высоком потоке событий (много камер, много номеров) этот запрос может стать дорогим.

**Для v1:** Индекс `idx_events_zone_active` должен сделать это достаточно быстрым. Если производительность ухудшится, путь улучшения — материализованный счётчик в таблице zones. Но это потребует либо триггеров, либо инкрементов на уровне приложения. Пока откладывается до фактической необходимости.

### 10.8 Фильтрация по направлению на каналах выезда

У каналов выезда может быть `controller_direction_filter`. В физической полосе выезда ожидаемое направление обычно `RECEDING` (машина удаляется от камеры). Если оператор задаст фильтр `APPROACHING`, реле не будет срабатывать. Это корректное поведение — ответственность за правильную настройку фильтра направления лежит на операторе. Специальная обработка не требуется.

### 10.9 Потокобезопасность проверки допустимости зоны

`_resolve_zone_eligibility()` вызывает `self._lists_db.plate_in_list_type()` и `plate_in_lists()`, которые берут соединение из общего пула БД. Эти вызовы происходят из потока обработки канала. Это полностью аналогично уже существующему вызову `find_client_by_plate()` в этом же потоке — пул по проекту и так потокобезопасен. Новых проблем здесь не возникает.

---

## 11. Поэтапный план реализации

Каждая фаза может быть закоммичена и протестирована независимо.

---

### Фаза 1 — Переработка схемы БД

**Цель:** Чистая схема с новой таблицей events, таблицей zones и колонками зон в channels.  
**Затрагивает:** `database/postgres/schema.sql`

**Задачи:**

1. Заменить `database/postgres/schema.sql` на новую схему (раздел 2.4)
2. Проверить, что схема чисто поднимается на пустой базе, запустив приложение и проверив логи старта

**Готово, когда:** Приложение стартует, схема инициализируется без ошибок, `\d events` в psql показывает правильные колонки.

---

### Фаза 2 — Обновление репозитория событий

**Цель:** `PostgresEventDatabase` работает с новой схемой.  
**Затрагивает:** `database/postgres_event_repository.py`

**Задачи:**

1. Обновить `_to_dict`: удалить `channel`, добавить `zone_id`, `time_entry`, `time_exit`; сопоставить позиции колонок новому порядку схемы
2. Обновить `insert_event`: удалить параметр `channel`; добавить опциональные `zone_id`, `time_entry`
3. Обновить все строки SELECT-запросов: `timestamp` → `time`; удалить `channel` из списка колонок; добавить новые колонки
4. Обновить `fetch_journal_page`: исправить курсор `(timestamp, id)` → `(time, id)`, исправить список колонок, убрать текстовый фильтр по `channel` (оставить `channel_id`)
5. Обновить `fetch_for_export`: убрать текстовый фильтр `channel`; обновить список колонок
6. Добавить метод `find_active_entry_and_write_exit(plate, zone_id, time_exit_iso)`
7. Обновить `delete_before`, чтобы он использовал колонку `time`
8. Обновить `fetch_last_plates_by_channel_ids`, чтобы он использовал `time` и новый список колонок

**Готово, когда:** Все существующие тесты проходят; при ручной проверке insert и fetch возвращают корректные имена полей.

---

### Фаза 3 — Обновление репозитория каналов

**Цель:** Каналы хранят конфиг зон в базе данных.  
**Затрагивает:** `database/channel_repository.py`

**Задачи:**

1. Добавить `zone_id INTEGER, zone_channel_type TEXT` в `_SCHEMA` CREATE TABLE
2. Дописать `zone_id, zone_channel_type` в `_SELECT_COLS`
3. Обновить `_row_to_dict`: сопоставить позиции 28, 29
4. Обновить `_normalize`: добавить блок нормализации `zone_id` и `zone_channel_type` (раздел 3.3)
5. Обновить `create_channel` INSERT: добавить колонки и значения `zone_id, zone_channel_type`
6. Обновить `update_channel` UPDATE SET: добавить `zone_id=%s, zone_channel_type=%s`

**Готово, когда:** Создание и обновление канала с `zone_id=1, zone_channel_type='entry'` сохраняется и корректно читается обратно.

---

### Фаза 4 — Репозиторий зон

**Цель:** Полноценный CRUD для таблицы zones, включая каскадный сброс каналов при удалении.  
**Затрагивает:** `database/zones_repository.py` (новый файл), `app/api/container.py`

**Задачи:**

1. Создать `database/zones_repository.py` с `ZoneDatabase(PooledDatabase)` (раздел 3.1)
2. Добавить `ZoneDatabase` в `AppContainer.build()` и `refresh_storage_clients()`
3. Передать `zone_db` в конструктор `ChannelProcessor` и сохранить как `self._zones_db`
4. Экспортировать `zone_db` через поле dataclass в `AppContainer`

**Готово, когда:** `ZoneDatabase.create_zone()`, `list_zones()`, `delete_zone()` работают, и при удалении зоны срабатывает каскадное очищение каналов.

---

### Фаза 5 — API роутер зон

**Цель:** REST endpoint’ы для управления зонами.  
**Затрагивает:** `app/api/routers/zones.py` (новый), `app/api/main.py`, `app/api/schemas.py`

**Задачи:**

1. Добавить `ZonePayload` и `ZoneUpdatePayload` в `schemas.py`
2. Создать `app/api/routers/zones.py` со всеми endpoint’ами (раздел 6.1)
3. Зарегистрировать роутер в `app/api/main.py`
4. Добавить `validate_channel_zone_binding()` в `AppContainer` (раздел 6.3)
5. Вызывать валидацию зоны в `put_channel_config` в `channels.py`
6. Добавить `zone_id: Optional[int]` и `zone_channel_type: Optional[str]` в `ChannelConfigPayload`

**Готово, когда:** Все endpoint’ы зон возвращают корректные данные; удаление зоны каскадно очищает каналы в БД; создание канала с невалидным `zone_id` возвращает 400.

---

### Фаза 6 — Обработка событий с учётом зон

**Цель:** Каналы въезда записывают поля зоны; каналы выезда обновляют существующие события.  
**Затрагивает:** `runtime/channel_runtime.py`, `controllers/service.py` (изменения не требуются), `app/api/container.py`

**Задачи:**

1. Добавить метод `_resolve_zone_eligibility(channel, plate)` в `ChannelProcessor` (раздел 4.3)
2. Изменить блок создания событий в `_run_channel()`:
   - читать `zone_id` и `zone_channel_type` из dict канала
   - Ветка A (без зоны): оставить текущее поведение
   - Ветка B (канал въезда): вычислять eligibility; передавать `zone_id` и `time_entry` в `insert_event`, если запись допустима
   - Ветка C (канал выезда): вычислять eligibility; если запись допустима, вызывать `find_active_entry_and_write_exit`; собирать `relay_event`; вызывать `_event_callback(relay_event)` без `insert_event`
3. Убедиться, что `relay_event` для каналов выезда всегда содержит `channel_id`, `plate`, `direction`
4. Добавить защиту на `event.get("id")` в callback-пути (для выездных каналов `id` может быть `None`)

**Готово, когда:** 
- Канал без зоны создаёт события точно так же, как и раньше
- Канал въезда в режиме "all" записывает `zone_id` и `time_entry` для каждого номера не из чёрного списка
- Канал выезда находит открытое событие въезда, записывает `time_exit` и ставит `zone_id = 0`, а реле при этом срабатывает
- Канал въезда в режиме "whitelist" записывает поля зоны только для номеров из белого списка, но само событие всё равно создаётся

---

### Фаза 7 — Очистка экспорта и lifecycle

**Цель:** Убедиться, что `fetch_for_export`, lifecycle данных и backup согласованы с новой схемой.  
**Затрагивает:** `app/api/routers/data.py`, `app/shared/data_lifecycle.py`

**Задачи:**

1. Проверить `app/api/routers/data.py` на любые ссылки на текстовую колонку `channel` или колонку `timestamp`
2. Обновить `ExportBundlePayload`, если в нём есть текстовый фильтр `channel` — заменить на `channel_id`
3. Проверить `app/shared/data_lifecycle.py` на обращения к колонкам в `delete_before` или связанных запросах
4. Обновить заголовки CSV-экспорта, чтобы они отражали `time`, `zone_id`, `time_entry`, `time_exit`; удалить `channel` (text)

**Готово, когда:** Export bundle генерирует CSV с правильными колонками; очистка по retention по-прежнему работает.

---

### Фаза 8 — Фронтенд: вкладка Zones

**Цель:** Оператор может создавать, просматривать, настраивать и удалять зоны.  
**Затрагивает:** `app/web/js/zones.js` (новый), `app/web/index.html`, `app/web/js/app.js`, `app/web/js/api.js`

**Задачи:**

1. Добавить методы API зон в `api.js`: `getZones()`, `createZone()`, `getZone(id)`, `updateZone(id, data)`, `deleteZone(id)`
2. Создать `app/web/js/zones.js` со списком зон, созданием, панелью настроек, удалением с предупреждением (раздел 7.2)
3. Добавить пункт Zones в сайдбар в `index.html`
4. Зарегистрировать route вкладки zones в `app.js`

**Готово, когда:** Вкладка Zones загружается, создание/удаление зоны работает, панель настроек зоны показывает name/capacity/occupancy/channels.

---

### Фаза 9 — Фронтенд: настройки зоны для канала

**Цель:** Оператор может назначить каналу зону и тип канала прямо из формы настройки канала.  
**Затрагивает:** `app/web/js/channels.js`

**Задачи:**

1. Загружать список зон при открытии формы настройки канала
2. Добавить dropdown "Зона" (список зон + опция "Без зоны")
3. Добавить select "Тип канала" (Въезд / Выезд), активный только при выбранной зоне
4. При сохранении включать `zone_id` и `zone_channel_type` в payload конфига
5. При загрузке формы заполнять dropdown’ы из текущего конфига канала

**Готово, когда:** Каналу можно назначить зону с типом "entry" или "exit", сохранить и корректно загрузить обратно.

---

### Фаза 10 — Фронтенд: обновление Events и Journal

**Цель:** Live events и журнал отражают поля зон.  
**Затрагивает:** `app/web/js/events.js`, `app/web/js/journal.js`

**Задачи:**

1. `events.js`: показывать бейдж зоны для событий, где `zone_id > 0`; показывать `time_entry`/`time_exit`, если есть
2. `events.js`: добавить защиту от отсутствующего `event.id` (у выездных каналов `id` может не быть)
3. `journal.js`: заменить текстовую колонку `channel` именем канала из списка каналов
4. `journal.js`: добавить опциональные колонки `Зона`, `Въезд`, `Выезд` (по умолчанию скрыты, но переключаемы)
5. `journal.js`: обновить курсор пагинации, чтобы он использовал ключ `time` вместо `timestamp`

**Готово, когда:** В live event строке показывается бейдж имени зоны; таблица журнала рендерится без ошибок; колонки зон можно включать и выключать.

---

## 12. План тестирования

### Unit tests

**`tests/test_zones_repository.py`** — новый файл

- `test_create_zone` — создание возвращает валидный id; `list` возвращает эту зону
- `test_update_zone` — имя и вместимость корректно обновляются
- `test_delete_zone_cascades_channels` — после удаления зоны все каналы с этим `zone_id` имеют `zone_id=NULL` и `zone_channel_type=NULL`
- `test_get_zone_occupancy_empty` — у только что созданной зоны заполненность равна 0
- `test_get_zone_occupancy_counts_only_open_entries` — события с `time_exit=NULL` считаются; события с заполненным `time_exit` не считаются

**`tests/test_events_repository_zones.py`** — новый файл (или расширение `test_events_repository.py`)

- `test_insert_event_with_zone_fields` — `zone_id` и `time_entry` корректно записываются и читаются обратно
- `test_insert_event_no_zone_fields_defaults_null` — поля зоны по умолчанию имеют `NULL`
- `test_find_active_entry_and_write_exit_found` — самый свежий открытый въезд для `plate+zone` получает `time_exit` и `zone_id=0`
- `test_find_active_entry_and_write_exit_not_found` — возвращает `None`, если открытый въезд не найден
- `test_find_active_entry_targets_most_recent` — два открытых въезда для одного номера; выезд закрывает только самый свежий
- `test_fetch_journal_page_uses_time_column` — курсор пагинации работает с переименованной колонкой
- `test_to_dict_no_channel_text_field` — в dict ответа нет ключа `channel`

**`tests/test_channel_repository_zones.py`** — новый файл (или расширение существующего)

- `test_create_channel_with_zone` — `zone_id` и `zone_channel_type` сохраняются
- `test_normalize_clears_zone_type_when_no_zone` — если `zone_id=None`, `zone_channel_type` принудительно становится `None`
- `test_normalize_rejects_invalid_zone_type` — валидны только `"entry"` и `"exit"`; всё остальное превращается в `None`

**`tests/test_zone_eligibility.py`** — новый файл

- `test_all_mode_non_blacklisted_is_eligible`
- `test_all_mode_blacklisted_is_not_eligible`
- `test_whitelist_mode_whitelisted_is_eligible`
- `test_whitelist_mode_not_in_whitelist_not_eligible`
- `test_custom_mode_in_list_is_eligible`
- `test_custom_mode_not_in_list_not_eligible`

### Integration tests (ручные или pytest с реальной БД)

- **Поток въезда, режим "all":** Номер распознан на канале въезда → создаётся событие с `zone_id` и `time_entry`
- **Поток въезда, режим "whitelist":** Номер из белого списка → поля зоны записываются; номер не из белого списка → событие создаётся, но поля зоны не записываются
- **Поток выезда, режим "all":** Номер распознан на канале выезда → существующий открытый въезд обновляется; новое событие не создаётся
- **Поток выезда, нет открытого въезда:** Номер распознан на канале выезда без предыдущего открытого въезда → записи в БД нет, но реле всё равно срабатывает
- **Каскад при удалении зоны:** Удалить зону → `channel_db.get_channel(id)` возвращает `zone_id=None`, `zone_channel_type=None`
- **Канал без зоны:** Канал без назначенной зоны → у события `zone_id=NULL`, `time_entry=NULL`; вся логика реле остаётся без изменений

### Чеклист регрессии

- [ ] Существующие каналы без настроек зон продолжают нормально создавать события
- [ ] Реле контроллера корректно срабатывает для каналов без зон (режимы whitelist, all, custom)
- [ ] Пагинация журнала по-прежнему работает (курсорная, теперь через колонку `time`)
- [ ] Export bundle генерирует корректный CSV (без текстовой колонки `channel`; колонка `time` корректна)
- [ ] SSE stream отдаёт события с `id` для каналов въезда; нет падения для событий каналов выезда
- [ ] Сохранение/восстановление настроек (backup/restore) по-прежнему работает — не затрагивает таблицу events

---

## 13. План обновления документации

Обновить следующие файлы документации после завершения реализации. Это должно быть выполнено либо как часть Фазы 10, либо как отдельная Фаза 11.

### `README.md`

Добавить в раздел **Ключевые возможности**:
- "Режим парковочных зон: учёт въезда и выезда транспортных средств по зонам"

Добавить краткое описание вкладки Zones.

### `docs/endpoints.md`

Добавить новый раздел **Zones**:

| Метод | Путь | Описание |
|---|---|---|
| `GET` | `/api/zones` | Список всех зон с заполненностью |
| `POST` | `/api/zones` | Создать зону |
| `GET` | `/api/zones/{id}` | Детали зоны + назначенные каналы |
| `PUT` | `/api/zones/{id}` | Обновить зону |
| `DELETE` | `/api/zones/{id}` | Удалить зону (каскадно очистить назначения каналов) |

### `docs/architecture.md`

Обновить описание слоя **Storage**:
- Добавить `ZoneDatabase` в список репозиториев
- Отметить значение sentinel `zone_id = 0` в таблице events

Обновить раздел **Data Flow**:
- Добавить ветвление по зонам в описание пайплайна обработки видеокадров (начиная с шага 8)

### `docs/modules.md`

Добавить запись для `database/zones_repository.py`:
- Назначение: CRUD зон и запросы заполненности; каскадное снятие зоны с каналов при удалении

### `docs/project-structure.md`

Добавить `database/zones_repository.py` в дерево директорий.

### `docs/setup.md` (если в нём описывается схема базы данных)

Обновить описание схемы в соответствии с новой структурой таблицы events.

### Новый документ: `docs/zones.md`

Создать отдельную страницу документации по зонам, которая покрывает:
- Что такое зоны и как они взаимодействуют с каналами
- Объяснение типов канала (entry/exit)
- Взаимодействие с режимами списков (как определяется eligibility в каждом режиме)
- Как `zone_id = 0` означает «автомобиль выехал»
- Как рассчитываются свободные места
- Как удаление зоны влияет на каналы
- Известные ограничения: несколько открытых въездов для одного номера, отсутствие push-обновления заполненности в реальном времени, отсутствие кросс-зонной валидации

---

## Итог

| Пункт | Количество |
|---|---|
| Новые файлы | `database/zones_repository.py`, `app/api/routers/zones.py`, `app/web/js/zones.js` |
| Изменённые backend-файлы | 7 (`schema.sql`, `postgres_event_repository.py`, `channel_repository.py`, `container.py`, `channel_runtime.py`, `schemas.py`, `data.py`) |
| Изменённые frontend-файлы | 5 (`index.html`, `app.js`, `api.js`, `channels.js`, `events.js`, `journal.js`) |
| Новые тестовые файлы | 4 |
| Фазы реализации | 10 |
| Файлы документации | 6 обновлённых + 1 новый |

**Сохранённый инвариант:** Каналы без назначенной зоны ведут себя полностью идентично текущей системе во всех наблюдаемых аспектах — создание событий, срабатывание реле, фильтрация по спискам, фильтрация по направлению, API-ответы и отображение на фронтенде.
