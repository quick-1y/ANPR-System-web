# Независимые задачи на реализацию
## ANPR System v0.8 Web — дорожная карта очистки и оптимизации

**Дата ревью:** 2026-04-14  
**Источник:** `REVIEW_FULL_REPORT.md`, `REVIEW_MIGRATION_COMPAT.md`, `REVIEW_UNUSED_AND_LEGACY.md`

Каждая задача является самодостаточной. Задачи не зависят друг от друга, если это не указано явно. Их можно передавать на реализацию по одной.

---

## TASK-01: Удалить migration-блоки DO $$ из schema.sql

**Проблема:**  
`database/postgres/schema.sql` содержит два migration guard-блока `DO $$` (строки 17-26 и 49-58), которые проверяют `information_schema.columns` перед добавлением колонок. Обе колонки (`plate_display`, `password_changed_at`) уже объявлены в расположенных выше `CREATE TABLE`. На чистой БД эти блоки выполняют два лишних запроса к `information_schema` при каждом cold start.

**Что изменить:**  
Удалить строки 17-26 (migration-блок для `plate_display`) и строки 49-58 (migration-блок для `password_changed_at`) из `database/postgres/schema.sql`. Больше никаких изменений не требуется.

**Затронутые файлы / модули:**  
- `database/postgres/schema.sql`

**Ожидаемый результат:**  
Файл схемы станет короче и будет отражать только текущее намерение схемы, а не историю миграций. Время cold start немного сократится. Функциональных изменений для чистой БД не будет.

**Уровень риска:** low — колонки уже присутствуют в `CREATE TABLE`. Единственный риск: если существующая инсталляция использует этот файл как механизм миграции старой БД без этих колонок. Сначала подтвердить, что деплой действительно работает только с fresh DB.

---

## TASK-02: Удалить backward-compat строки ALTER TABLE из ListDatabase._schema_sql()

**Проблема:**  
`database/lists_repository.py` в строках 62-74 содержит 7 выражений `ALTER TABLE … ADD COLUMN IF NOT EXISTS` и один `DROP INDEX IF EXISTS`. Все эти колонки уже объявлены в `CREATE TABLE clients` на строках 51-70. Эти `ALTER TABLE` существуют только ради старых БД, появившихся до добавления этих полей.

**Что изменить:**  
В `database/lists_repository.py`, внутри `_schema_sql()`, удалить строки 62-73 (7 выражений `ALTER TABLE ADD COLUMN` и `DROP INDEX`). Оставить строку 74 (`CREATE UNIQUE INDEX IF NOT EXISTS uq_clients_list_plate`). В результате должно остаться: `CREATE TABLE lists`, `CREATE TABLE clients` со всеми колонками, затем только `CREATE INDEX`.

**Затронутые файлы / модули:**  
- `database/lists_repository.py`

**Ожидаемый результат:**  
`_schema_sql()` будет содержать только DDL, описывающий актуальную схему. Без истории миграций. Тесты должны продолжить проходить.

**Уровень риска:** low — то же замечание про fresh DB, что и в TASK-01.

---

## TASK-03: Удалить очистку legacy-полей из SettingsNormalizer

**Проблема:**  
`config/settings_normalizer.py` молча удаляет два поля из конфигов настроек, которые существовали в старых версиях схемы:
- `storage.export_dir` (строки 76-79)
- `ocr.confidence_threshold` (строки 120-124)

Эти поля больше не существуют в текущей схеме. На новой установке файл настроек никогда их не содержит. Код очистки ничего полезного не делает и только усложняет понимание.

**Что изменить:**  
1. В `_fill_storage_defaults()`: удалить строки 76-79 (блок `if "export_dir" in storage:`).  
2. В `_fill_ocr_defaults()`: удалить строки 120-124 (блок `if "confidence_threshold" in ocr:` и его комментарий).

**Затронутые файлы / модули:**  
- `config/settings_normalizer.py`

**Ожидаемый результат:**  
Нормализатор будет только добавлять недостающие ключи и больше не будет молча удалять старые поля. Существующие тесты должны проходить. Для актуальных конфигов функциональных изменений не будет.

**Уровень риска:** low. Примечание: если какой-то существующий `settings.yaml` всё ещё содержит эти поля, они больше не будут удаляться при загрузке. Это нормально — лишние неизвестные ключи безвредны.

---

## TASK-04: Удалить избыточные индексы базы данных

**Проблема:**  
`database/postgres/schema.sql` содержит две пары избыточных индексов:
- `idx_events_timestamp ON events(timestamp DESC)` полностью покрывается индексом `idx_events_ts_id_desc ON events(timestamp DESC, id DESC)`
- `idx_events_channel_id ON events(channel_id, timestamp DESC)` полностью покрывается индексом `idx_events_channel_id_ts_id_desc ON events(channel_id, timestamp DESC, id DESC)`

PostgreSQL умеет использовать composite indexes как prefix scans. Более узкие индексы зря занимают место и замедляют `INSERT/UPDATE`.

**Что изменить:**  
Удалить из `schema.sql`:
```sql
CREATE INDEX IF NOT EXISTS idx_events_timestamp ON events(timestamp DESC);
CREATE INDEX IF NOT EXISTS idx_events_channel_id ON events(channel_id, timestamp DESC);
```
Оставить `idx_events_ts_id_desc` и `idx_events_channel_id_ts_id_desc`.

**Затронутые файлы / модули:**  
- `database/postgres/schema.sql`

**Ожидаемый результат:**  
На два индекса меньше. Запись событий станет немного быстрее. Все существующие паттерны запросов продолжат использовать composite indexes. Изменения в коде приложения не нужны.

**Уровень риска:** low.

---

## TASK-05: Исправить XSS — заменить innerHTML с данными из БД в events.js

**Проблема:**  
`app/web/js/events.js:96` устанавливает `div.innerHTML` с `displayPlate` (из `event.plate_display`) и `channelName` (из `event.channel`). Это значения, пришедшие из базы данных, и они могут содержать HTML. Возможна stored XSS-атака.

**Что изменить:**  
В функции `makeItem()` (`events.js`) заменить единственное присваивание `div.innerHTML = ...` на последовательность операций `createElement` / `textContent`. Собрать внутренние элементы так:
- `ev-plate` span: `span.textContent = displayPlate`
- `ev-direction` span: `span.textContent = direction.label`
- `ev-meta-channel` span: `span.textContent = channelName`
- `ev-meta-time` span: `span.textContent = timeStr`
- `ev-conf` span: `span.textContent = conf.toFixed(2)`
- `flagHtml(item.country)` — здесь нужно убедиться, что вставляется только заранее известный emoji-флаг или безопасный SVG

Также исправить `openEventDetails()` (строка 220): присваивание `meta.innerHTML` строит строки из значений БД (`payload.channel`, поля клиента). Заменить это на явное построение DOM или использовать helper `esc()` для HTML-экранирования.

**Затронутые файлы / модули:**  
- `app/web/js/events.js`

**Ожидаемый результат:**  
Лента событий и модальное окно деталей события больше не могут быть инъецированы через номер машины или имя канала. Внешний вид остаётся идентичным текущему.

**Уровень риска:** medium — нужно проверить, что рендеринг флага и CSS-классы после рефакторинга работают корректно. Проверить в браузере.

---

## TASK-06: Исправить XSS — заменить innerHTML с данными из БД в clients.js, lists.js, journal.js

**Проблема:**  
Несколько присваиваний `innerHTML` используют данные из БД (номера, имена клиентов, названия списков) без HTML-экранирования:
- `clients.js:26-32` — `tr.innerHTML` с plate, last_name, first_name, phone, car
- `clients.js:162` — `row.innerHTML` с названием списка
- `lists.js:65` — `div.innerHTML` с названием списка
- `lists.js:94-98` — `tr.innerHTML` с plate, first_name, last_name, phone, car, comment
- `lists.js:129-133` — `innerHTML` строки пикера с label клиента и номером
- `journal.js:76` — `tr.innerHTML` с временем, номером, каналом, страной, confidence, direction

**Что изменить:**  
Создать общий helper `esc(str)` в `ui.js`:
```javascript
export function esc(str) {
    return String(str ?? '').replace(/&/g,'&amp;').replace(/</g,'&lt;').replace(/>/g,'&gt;').replace(/"/g,'&quot;');
}
```
Импортировать его и использовать во всех template literal-присваиваниях в перечисленных выше файлах.

**Затронутые файлы / модули:**  
- `app/web/js/ui.js` (добавить helper `esc`)
- `app/web/js/clients.js`
- `app/web/js/lists.js`
- `app/web/js/journal.js`

**Ожидаемый результат:**  
Все значения из БД будут HTML-экранироваться перед вставкой. Визуально всё останется как сейчас (HTML-сущности будут отображаться как обычные символы).

**Уровень риска:** low — подход с `esc()` минимален и не ломает поведение.

---

## TASK-07: Добавить публичный метод TrackAggregator.has_active_tracks()

**Проблема:**  
`runtime/channel_runtime.py:549` читает `pipeline.aggregator._track_states.values()` — это приватный атрибут. Такое обращение создаёт жёсткую связность между `channel_runtime` (runtime layer) и `anpr_pipeline` (domain layer).

**Что изменить:**  
1. Добавить в `TrackAggregator` в `anpr/pipeline/anpr_pipeline.py`:
```python
def has_active_tracks(self) -> bool:
    """Return True if any track is still being processed (not yet finalized)."""
    return any(not s.finalized for s in self._track_states.values())
```
2. В `runtime/channel_runtime.py:547-553` заменить:
```python
active_tracks = sum(
    1 for s in pipeline.aggregator._track_states.values()
    if not s.finalized
)
if active_tracks == 0:
```
на:
```python
if not pipeline.aggregator.has_active_tracks():
```

**Затронутые файлы / модули:**  
- `anpr/pipeline/anpr_pipeline.py`
- `runtime/channel_runtime.py`

**Ожидаемый результат:**  
Инкапсуляция восстановлена. Поведение adaptive stride остаётся прежним. Внешний код больше не читает приватный словарь.

**Уровень риска:** low.

---

## TASK-08: Корректно завершать _io_pool в ChannelProcessor

**Проблема:**  
`runtime/channel_runtime.py:95` создаёт `ThreadPoolExecutor(max_workers=2)` и сохраняет его в `self._io_pool`. Этот пул никогда не завершается при остановке процессора или когда `restart_processor_for_settings()` создаёт новый экземпляр `ChannelProcessor`. Заброшенные пулы оставляют фоновые потоки.

**Что изменить:**  
1. Добавить метод `shutdown(wait=True)` в `ChannelProcessor`:
```python
def shutdown_io_pool(self) -> None:
    self._io_pool.shutdown(wait=True, cancel_futures=False)
```
2. В `AppContainer.shutdown()` (`app/api/container.py:134-137`) после остановки всех каналов вызвать:
```python
self.processor.shutdown_io_pool()
```
3. В `AppContainer.restart_processor_for_settings()` (`container.py:154-166`) перед созданием нового процессора вызвать:
```python
old_processor = self.processor
...
self.processor = self._create_processor()
...
old_processor.shutdown_io_pool()
```

**Затронутые файлы / модули:**  
- `runtime/channel_runtime.py`
- `app/api/container.py`

**Ожидаемый результат:**  
Потоки записи JPEG будут корректно завершаться при shutdown. После перезапуска процессора не останется orphaned threads.

**Уровень риска:** low. `wait=True` действительно будет блокировать завершение до конца текущих операций записи, и это правильное поведение.

---

## TASK-09: Синхронизировать processor._lists_db после refresh_storage_clients()

**Проблема:**  
`app/api/container.py:208-226` (`refresh_storage_clients()`) пересоздаёт все DB-объекты, включая `self.lists_db = ListDatabase(dsn)`, но запущенный `ChannelProcessor` продолжает держать ссылку на старый экземпляр `ListDatabase` через `self.processor._lists_db`. После refresh процессор выполняет поиск клиентов через старый connection pool.

**Что изменить:**  
В `refresh_storage_clients()` сразу после строки `self.lists_db = ListDatabase(dsn)` добавить:
```python
self.processor._lists_db = self.lists_db
```

**Затронутые файлы / модули:**  
- `app/api/container.py`

**Ожидаемый результат:**  
После смены DSN (или любого сохранения настроек, которое вызывает `refresh_storage_clients`) процессор каналов будет использовать актуальное подключение к базе. Поиск клиентов в recognition loop станет согласованным с остальной частью приложения.

**Уровень риска:** low — исправление в одну строку. Поле `_lists_db` не защищено lock’ом в `ChannelProcessor`, но это простое присваивание ссылки (атомарное под GIL Python). В худшем случае поток канала, уже выполняющий `find_client_by_plate` на старом объекте, завершит текущий вызов на старом пуле и начнёт использовать новый объект со следующего события.

---

## TASK-10: Переименовать SQL alias `e` в `c` в lists_repository.py

**Проблема:**  
`database/lists_repository.py` использует `e` как alias таблицы `clients` во всех SQL-запросах (строки 85, 172, 189, 211, 243). Alias `e` обычно ассоциируется с `events`. Это создаёт путаницу при чтении запросов, где `clients` соединяется с `lists`.

**Что изменить:**  
В `database/lists_repository.py` заменить все вхождения:
- `FROM clients e` → `FROM clients c`
- `JOIN clients e ON` → `JOIN clients c ON`
- `LEFT JOIN clients e ON` → `LEFT JOIN clients c ON`
- `e.plate_normalized` → `c.plate_normalized`
- `e.id` → `c.id` (в контексте join с clients)
- `e.list_id` → `c.list_id`
- `e.is_deleted` → `c.is_deleted`
- `e.plate` → `c.plate` (в клиентском контексте)
- `e.last_name`, `e.first_name` и т.д. → `c.last_name`, `c.first_name` и т.д.

Важно: менять alias только в клиентских запросах, чтобы случайно не затронуть возможные будущие join с `events`.

**Затронутые файлы / модули:**  
- `database/lists_repository.py`

**Ожидаемый результат:**  
Весь SQL в файле будет использовать понятные и привычные alias. Функциональных изменений не будет.

**Уровень риска:** low. После изменения прогнать тесты (`pytest tests/test_lists_repository.py`).

---

## TASK-11: Усилить защиту JWT_SECRET_KEY — падать на старте, если не задан

**Проблема:**  
`app/api/auth_utils.py:15`:
```python
JWT_SECRET_KEY = os.getenv("JWT_SECRET_KEY", "anpr-default-secret-change-me")
```
Если переменная окружения не задана, приложение стартует с широко известным секретом, который виден в исходниках. Любой атакующий, увидевший этот код, сможет подделывать валидные JWT-токены для любого пользователя.

**Что изменить:**  
```python
JWT_SECRET_KEY = os.getenv("JWT_SECRET_KEY", "").strip()
if not JWT_SECRET_KEY:
    raise RuntimeError(
        "JWT_SECRET_KEY environment variable is required. "
        "Set it to a random secret before starting the application."
    )
```
Также обновить `.env.example`, явно задокументировав это требование.

**Затронутые файлы / модули:**  
- `app/api/auth_utils.py`
- `.env.example`

**Ожидаемый результат:**  
Приложение откажется стартовать без секрета. Больше не будет тихого продакшен-деплоя с дефолтными учётными данными.

**Уровень риска:** low с точки зрения prod-безопасности. Примечание: тесты, которые не задают `JWT_SECRET_KEY`, начнут падать. Нужно либо установить его в test fixtures, либо добавить `os.environ.setdefault("JWT_SECRET_KEY", "test-secret-only")` в тестовый `conftest`.

---

## TASK-12: Добавить bulk import endpoint для CSV-импорта списка

**Проблема:**  
`app/web/js/lists.js:229-250` импортирует строки CSV по одной, делая 2 HTTP-запроса на каждую строку (POST `/api/clients`, затем POST `/api/clients/{id}/attach`). CSV на 500 строк = 1000 последовательных HTTP-запросов, что даёт медленный импорт и лишнюю нагрузку на подключения к БД.

**Что изменить:**  
1. Добавить endpoint `POST /api/lists/{list_id}/import` в `app/api/routers/lists.py`:
   - принимать `application/json` с телом: `{"clients": [{plate, first_name, last_name, ...}, ...]}`
   - вставлять всех клиентов в одной транзакции и привязывать к списку в одном цикле
   - возвращать `{"imported": N, "skipped": N, "errors": [...]}`  
2. Добавить соответствующий метод `ClientDatabase.bulk_create_and_attach(list_id, clients)` в `database/clients_repository.py`  
3. Обновить `importCurrentListCSV()` в `lists.js`, чтобы он отправлял batch-POST на новый endpoint

**Затронутые файлы / модули:**  
- `app/api/routers/lists.py`
- `app/api/schemas.py` (новая Pydantic-схема для payload bulk import)
- `database/clients_repository.py`
- `app/web/js/lists.js`

**Ожидаемый результат:**  
CSV импорт выполняется одним HTTP-запросом. Время импорта для 1000 строк снижается примерно с 5-10 секунд до менее чем 1 секунды.

**Уровень риска:** medium — новый endpoint, новый DB-метод. Нужно протестировать на больших CSV (1000+ строк) и проверить обработку дубликатов номеров.

---

## TASK-13: Переименовать router-функции в lists.py для консистентности

**Проблема:**  
`app/api/routers/lists.py` содержит имена функций с лишним префиксом `plate`, который не соответствует контексту модуля: `list_plate_lists`, `delete_plate_list`, `update_plate_list`.

**Что изменить:**  
Переименовать:
- `list_plate_lists` → `list_lists`
- `create_plate_list` → `create_list`
- `delete_plate_list` → `delete_list`
- `update_plate_list` → `update_list`
- `all_plates` → `plates_by_type` (или `list_plates_with_type`)

Это внутренние имена Python-функций; API routes (`/api/lists`, `/api/lists/{id}`) не меняются.

**Затронутые файлы / модули:**  
- `app/api/routers/lists.py`

**Ожидаемый результат:**  
Единообразный нейминг по всему роутеру. Контракт API остаётся прежним.

**Уровень риска:** very low — меняются только внутренние имена.

---

## TASK-14: Удалить fallback-конструирование БД в ChannelProcessor

**Проблема:**  
`runtime/channel_runtime.py:85-87`:
```python
self._events_db = events_db if events_db is not None else PostgresEventDatabase(
    str(self._storage_settings.get("postgres_dsn", ""))
)
```
Fallback создаёт `PostgresEventDatabase` с потенциально пустым DSN. На практике `AppContainer._create_processor()` всегда передаёт `events_db`. Этот fallback — мёртвый код, который может тихо создать сломанный DB-клиент с `dsn=""`.

**Что изменить:**  
Заменить fallback на:
```python
if events_db is None:
    raise ValueError("events_db is required for ChannelProcessor")
self._events_db = events_db
```

**Затронутые файлы / модули:**  
- `runtime/channel_runtime.py`

**Ожидаемый результат:**  
Ошибка программирования будет выявляться сразу при инициализации, а не приведёт к тихой деградации во время runtime.

**Уровень риска:** low. Единственный риск: если какой-то тест создаёт `ChannelProcessor` без `events_db`, он теперь упадёт с понятной ошибкой вместо тихого поведения. Такие тесты нужно обновить и передавать mock/stub.

---

## Примечания по приоритетам

Рекомендуемый порядок по соотношению эффект / усилия:

| Приоритет | Задачи |
|----------|-------|
| Сделать сначала | TASK-05, TASK-06 (исправления XSS) |
| Сделать скоро | TASK-09 (устаревшая ссылка lists_db), TASK-11 (JWT secret) |
| Очистка | TASK-01, TASK-02, TASK-03, TASK-04 (миграции / compat / индексы) |
| Рефакторинг | TASK-07, TASK-08, TASK-10, TASK-13, TASK-14 |
| Фича | TASK-12 (bulk import) |
