# Дорожная карта: рефакторинг разделения клиентов и списков

---

## 1. Анализ текущего состояния

**Как сейчас организован функционал:**

- `database/lists_repository.py` — единый класс `ListDatabase` управляет и таблицей `lists` (метаданные списков), и таблицей `clients` (записи клиентов/номеров). Обе сущности тесно связаны внутри одного модуля.
- `app/api/routers/lists.py` — единый роутер обрабатывает весь CRUD и для списков, и для клиентов (в API они названы как "entries").
- `app/web/js/lists.js` — единый фронтенд-модуль управляет и UI списков, и UI клиентов/entries.
- `app/web/index.html` — содержит одну верхнеуровневую вкладку "Lists".

**Связность между списками и клиентами:**

- `clients.list_id BIGINT NOT NULL REFERENCES lists(id) ON DELETE CASCADE` — клиент **обязан** принадлежать какому-либо списку; отдельных клиентов без списка не существует.
- Все CRUD-эндпоинты клиентов вложены в `/api/lists/{list_id}/entries/*`.
- Состояние фронтенда: `state.selectedListId` определяет, какие entries показываются; независимого состояния клиентов вне выбранного списка нет.

**Рискованные области для фильтрации каналов:**

- `ControllerAutomationService` в `controllers/service.py` напрямую вызывает `lists_db.plate_in_list_type(plate, type)` и `lists_db.plate_in_lists(plate, list_ids)` — это ключевые функции фильтрации для каналов. Любое переименование или изменение сигнатуры сломает автоматизацию реле.
- ?????? `lists_db.find_entry_by_plate(plate)` используется для обогащения событий (подстановка имени клиента в события) — эта логика должна остаться рабочей.
- `channels.list_filter_mode` и `channels.list_filter_list_ids` должны остаться семантически неизменными в БД.

---

## 2. Целевая архитектура

**Структура фронтенда:**

```text
Clients (верхнеуровневая вкладка)
├── Clients (подвкладка)
│   ├── Таблица клиентов (все клиенты, независимо от списков)
│   ├── Кнопка Add Client → переиспользовать существующие поля формы
│   └── Карточка клиента (modal/panel)
│       ├── Просмотр / Редактирование / Удаление
│       ├── Отображение текущего прикрепленного списка
│       ├── Кнопка Attach to List → модальное окно выбора списка
│       └── Кнопка Detach from List
└── Lists (подвкладка)
    ├── Боковая панель списков (как сейчас)
    ├── Редактирование типа/имени списка (как сейчас)
    ├── Таблица участников списка (клиенты, прикрепленные к списку)
    ├── Кнопка Attach Client → модальное окно выбора клиента (с поиском)
    └── Строка клиента → открывает карточку клиента с кнопкой "Detach from List"
```

**Структура backend-модулей:**

```text
database/
├── clients_repository.py   # ClientDatabase — CRUD клиентов + поиск + attach/detach
└── lists_repository.py     # ListDatabase — CRUD списков + поиск номеров (для каналов, событий)

app/api/routers/
├── clients.py              # эндпоинты /api/clients/*
└── lists.py                # эндпоинты /api/lists/* (урезанный — без CRUD clients)
```

**Изменения в модели данных:**

```sql
-- clients: сделать list_id nullable (клиент может существовать без списка)
-- Было: list_id BIGINT NOT NULL REFERENCES lists(id) ON DELETE CASCADE
-- Должно стать: list_id BIGINT REFERENCES lists(id) ON DELETE SET NULL

-- Больше изменений схемы не требуется
-- таблица channels: без изменений
-- таблица lists: без изменений
```

---

## 3. Пошаговая дорожная карта реализации

### Фаза 1 — Backend: схема и разделение репозиториев

**Задача 1.1 — Обновить схему таблицы `clients` в `lists_repository.py`**
- Изменить `list_id BIGINT NOT NULL` → `list_id BIGINT REFERENCES lists(id) ON DELETE SET NULL` (nullable)
- Убрать `ON DELETE CASCADE` из связи list → clients
- Это изменение на уровне CREATE TABLE (БД пересоздается с нуля при каждом запуске)

**Задача 1.2 — Создать `database/clients_repository.py`**
- Новый класс `ClientDatabase` со своим DB pool
- Перенести и переименовать следующие методы из `ListDatabase`:
  - `add_entry()` → `create_client()` (сигнатура: `list_id` не обязателен)
  - `update_entry()` → `update_client()`
  - `delete_entry()` → `delete_client()`
  - `list_entries(list_id)` → оставить в `ListDatabase` как `list_clients_in_list(list_id)` (для отображения участников списка)
  - `find_entry_by_plate()` → переименовать в `find_client_by_plate()` (оставить в `ListDatabase` для обратной совместимости или сделать делегирование)
- Добавить новые методы в `ClientDatabase`:
  - `list_all_clients()` — возвращает всех неудаленных клиентов (без фильтра по списку)
  - `get_client(client_id)` — получить одну запись клиента
  - `search_clients(query)` — поиск по `last_name`, `first_name`, `middle_name`, `plate` (`ILIKE`)
  - `attach_to_list(client_id, list_id)` — устанавливает `clients.list_id = list_id`
  - `detach_from_list(client_id)` — устанавливает `clients.list_id = NULL`

**Задача 1.3 — Упростить `database/lists_repository.py`**
- Удалить: `add_entry()`, `update_entry()`, `delete_entry()`
- Оставить: `create_list()`, `list_lists()`, `update_list()`, `delete_list()`
- Оставить: `list_clients_in_list(list_id)` — используется подвкладкой Lists для отображения участников
- Оставить: `all_plates_with_type()` — используется для поиска/подстановки номеров
- Оставить: `plate_in_list_type()` — используется автоматизацией каналов (**НЕ МЕНЯТЬ СИГНАТУРУ**)
- Оставить: `plate_in_lists()` — используется автоматизацией каналов (**НЕ МЕНЯТЬ СИГНАТУРУ**)
- Оставить: `find_entry_by_plate()` → переименовать в `find_client_by_plate()` и обновить все места вызова

**Задача 1.4 — Подключить `ClientDatabase` в контейнер**
- В `app/api/container.py`: создать `ClientDatabase(dsn)` рядом с существующим `ListDatabase`
- Передать `clients_db` в роутеры, которым он нужен

---

### Фаза 2 — Backend: API-маршруты

**Задача 2.1 — Создать `app/api/routers/clients.py`**

| Метод | Эндпоинт | Действие |
|--------|----------|----------|
| GET | `/api/clients` | Получить список всех клиентов |
| POST | `/api/clients` | Создать клиента (без `list_id` в body) |
| GET | `/api/clients/{id}` | Получить одного клиента |
| PUT | `/api/clients/{id}` | Обновить поля клиента |
| DELETE | `/api/clients/{id}` | Мягко удалить клиента |
| GET | `/api/clients/search?q=` | Поиск клиентов |
| POST | `/api/clients/{id}/attach` | Прикрепить к списку (`{list_id: int}`) |
| DELETE | `/api/clients/{id}/attach` | Открепить от списка |

**Задача 2.2 — Обновить `app/api/routers/lists.py`**
- Удалить: все эндпоинты `/api/lists/{list_id}/entries/*`
- Оставить: `GET /api/lists`, `POST /api/lists`, `PUT /api/lists/{id}`, `DELETE /api/lists/{id}`
- Оставить: `GET /api/lists/plates` (`all_plates_with_type` — не менять URL и поведение)
- Оставить: `GET /api/lists/entry-by-plate` (тот же URL — ничего не ломать)
- Добавить: `GET /api/lists/{list_id}/clients` — получить клиентов списка (замена `/entries`)

**Задача 2.3 — Обновить Pydantic-схемы в `app/api/schemas.py`**
- Добавить: `ClientPayload` (`plate`, `last_name`, `first_name`, `middle_name`, `phone`, `car`, `comment`) — без `list_id`
- Добавить: `AttachClientPayload` (`list_id: int`)
- Оставить: `ListPayload`, `UpdateListPayload` — без изменений
- Удалить: `EntryPayload` (заменяется на `ClientPayload`)

**Задача 2.4 — Зарегистрировать новый роутер в `app/api/main.py`**
- `app.include_router(clients_router)` рядом с существующими роутерами

---

### Фаза 3 — Frontend: HTML-структура

**Задача 3.1 — Обновить `app/web/index.html`**
- Переименовать верхнеуровневую вкладку "Lists" в "Clients"
- Внутри раздела Clients добавить две кнопки подвкладок: "Clients" и "Lists"
- Создать новую панель для подвкладки Clients (таблица клиентов + кнопка добавления)
- Существующую панель Lists оставить как подвкладку Lists
- Добавить новые модальные окна:
  - Карточка клиента (просмотр/редактирование/удаление + информация о прикрепленном списке + кнопки attach/detach)
  - Модальное окно выбора списка (показывается при нажатии "Attach to List" в карточке клиента)
  - Модальное окно выбора клиента (показывается при нажатии "Attach Client" в списке, содержит строку поиска)
- Переиспользовать существующие поля формы entry (`plate`, `last_name`, `first_name` и т.д.) в модальном окне создания клиента

---

### Фаза 4 — Frontend: JavaScript-модули

**Задача 4.1 — Создать `app/web/js/clients.js`**
- Состояние: `state.allClients`, `state.selectedClientId`
- `loadAllClients()` — выполняет `GET /api/clients`
- `renderClientsTable()` — рендерит строки клиентов, каждая строка кликабельна
- `openClientCard(clientId)` — открывает карточку клиента, получает полные данные клиента
- `openAddClientModal()` — переиспользует существующую форму entry, отправляет `POST /api/clients`
- `saveClientChanges(clientId)` — отправляет `PUT /api/clients/{id}`
- `deleteClient(clientId)` — отправляет `DELETE` с подтверждением
- `openListPickerModal(clientId)` — загружает доступные списки, показывает кнопку "Attach" для каждого списка
- `attachClientToList(clientId, listId)` — отправляет `POST /api/clients/{id}/attach`
- `detachClientFromList(clientId)` — отправляет `DELETE /api/clients/{id}/attach`
- `searchClients(query)` — с debounce вызывает `GET /api/clients/search?q=...`, затем перерендеривает таблицу

**Задача 4.2 — Рефакторинг `app/web/js/lists.js`**
- Удалить: `loadEntries()`, `openEditEntryModal()`, `openDeleteEntryModal()`, все привязки формы entry
- Удалить: обработчики add/edit/delete entry
- Оставить: `loadLists()`, `renderLists()`, `refreshPlateLookup()`, `renderCustomListOptions()`
- Оставить: CSV import/export (переиспользовать для участников списка при необходимости либо отложить)
- Добавить: `loadListClients(listId)` — выполняет `GET /api/lists/{id}/clients`
- Добавить: `renderListClientsTable(clients)` — рендерит таблицу участников; каждая строка открывает карточку клиента
- Добавить: `openClientPickerModal(listId)` — показывает всех клиентов с полем поиска; у каждого есть кнопка "Attach"; вызывает `POST /api/clients/{id}/attach`

**Задача 4.3 — Обновить `app/web/js/app.js`**
- Импортировать и инициализировать модуль `clients.js`
- Подключить логику переключения подвкладок (Clients ↔ Lists внутри верхнеуровневой вкладки Clients)
- Убедиться, что при инициализации вызываются и `loadAllClients()`, и `loadLists()`

**Задача 4.4 — Добавить диалоги подтверждения для всех destructive/attach операций**
- Все операции (создание, редактирование, удаление клиента; прикрепление, открепление; удаление списка) должны подтверждаться через модальное окно перед выполнением
- Переиспользовать существующие modal/confirm utilities из `ui.js`

---

### Фаза 5 — Очистка и проверка

**Задача 5.1 — Проверить wiring контейнера в `app/api/container.py`**
- Убедиться, что `lists_db.plate_in_list_type` и `lists_db.plate_in_lists` по-прежнему инжектятся в `ControllerAutomationService` (изменения не нужны, нужна только проверка)

**Задача 5.2 — Переименовать `find_entry_by_plate` → `find_client_by_plate`**
- Обновить метод в `lists_repository.py`
- Найти все места использования (routers, workers, services) и обновить атомарно

**Задача 5.3 — Обновить `tests/test_lists_repository.py`**
- Добавить тесты для методов `ClientDatabase`
- Обновить существующие тесты, которые ссылались на `add_entry` / `delete_entry`, на новые имена

---

## 4. Соображения по API и потокам данных

**Меняющиеся эндпоинты:**

| Старый | Новый | Примечание |
|--------|-------|------------|
| `POST /api/lists/{id}/entries` | `POST /api/clients` | Без `list_id` в body |
| `PUT /api/lists/{id}/entries/{eid}` | `PUT /api/clients/{id}` | Плоская структура, без вложенности |
| `DELETE /api/lists/{id}/entries/{eid}` | `DELETE /api/clients/{id}` | |
| `GET /api/lists/{id}/entries` | `GET /api/lists/{id}/clients` | Та же цель, но имя понятнее |
| *(новый)* | `GET /api/clients` | Все клиенты |
| *(новый)* | `GET /api/clients/search?q=` | Поиск |
| *(новый)* | `POST /api/clients/{id}/attach` | Прикрепить к списку |
| *(новый)* | `DELETE /api/clients/{id}/attach` | Открепить от списка |

**Поток attach/detach:**
- Прикрепление: `POST /api/clients/{id}/attach` с `{list_id: N}` → `UPDATE clients SET list_id = N WHERE id = ?`
- Открепление: `DELETE /api/clients/{id}/attach` → `UPDATE clients SET list_id = NULL WHERE id = ?`
- Клиент может быть только в одном списке одновременно (один внешний ключ `list_id`)
- Если прикрепить клиента к новому списку, когда он уже прикреплен к другому, предыдущее прикрепление неявно заменяется (`UPDATE` перезаписывает значение)

**Поток подтверждений:**
- Фронтенд отправляет запрос только после подтверждения пользователя в модальном окне
- Подтверждение на стороне backend не требуется — это обычные операции изменения данных
- Переиспользовать существующий confirm pattern из `ui.js`

---

## 5. Очистка нейминга

| Текущее имя | Предлагаемое имя | Причина |
|---|---|---|
| `list_entries()` | `list_clients_in_list(list_id)` | `entries` — слишком размыто |
| `add_entry()` | `create_client()` | Соответствует предметной области |
| `update_entry()` | `update_client()` | То же |
| `delete_entry()` | `delete_client()` | То же |
| `find_entry_by_plate()` | `find_client_by_plate()` | Понятнее по домену |
| `EntryPayload` (schema) | `ClientPayload` | Соответствие предметной области |
| `state.currentEntries` | `state.listMembers` | Отличать от общего списка клиентов |
| `openEditEntryModal()` | `openClientCard()` | Отражает новую концепцию UI |
| `/api/lists/{id}/entries` | `/api/lists/{id}/clients` | Соответствует домену |
| `entries_count` (в ответе списка) | `clients_count` | Соответствует домену |

**Имена, которые нельзя менять (критично для фильтрации каналов):**
- `plate_in_list_type()` — вызывается из `ControllerAutomationService`
- `plate_in_lists()` — вызывается из `ControllerAutomationService`
- `all_plates_with_type()` — вызывается фронтендом для plate lookup
- `list_filter_mode`, `list_filter_list_ids` — имена колонок в таблице `channels`

---

## 6. Риски и проверки совместимости

**Риск 1 — `list_id` становится nullable у clients**
- Влияние: `plate_in_lists()` и `plate_in_list_type()` используют `clients JOIN lists` — строки с `NULL list_id` естественным образом не будут участвовать в JOIN, значит, автоматически исключаются из фильтрации каналов
- Действие: проверить условие JOIN в обоих методах после изменения схемы; логика не должна измениться

**Риск 2 — удаление `ON DELETE CASCADE`**
- Раньше удаление списка удаляло и всех его клиентов. Теперь клиенты остаются, а `list_id` становится `NULL`
- Действие: обновить `delete_list()` в `lists_repository.py` — выполнить `UPDATE clients SET list_id = NULL WHERE list_id = ?` до удаления списка либо вместо зависимости от CASCADE

**Риск 3 — инъекция `ControllerAutomationService`**
- Сейчас подключение выглядит так: `plate_in_list_type=lists_db.plate_in_list_type, plate_in_lists=lists_db.plate_in_lists`
- Эти методы должны остаться в `ListDatabase`, а не быть перенесены в `ClientDatabase`
- Действие: убедиться, что эти методы остаются в `lists_repository.py` и сигнатуры не меняются

**Риск 4 — `renderCustomListOptions()` в `lists.js`**
- Вызывается из `channels.js` для рендера чекбоксов списков в конфигурации канала
- Должна остаться в `lists.js` и продолжать корректно экспортироваться
- Действие: не перемещать и не переименовывать эту функцию при разделении логики

**Риск 5 — обогащение событий через `find_entry_by_plate()`**
- Используется для подстановки имени/данных клиента в журнал событий
- Действие: перед переименованием найти все места вызова; обновить их атомарно на этапе 5.2

**Риск 6 — plate lookup (`state.plateLookup`) не должен включать открепленных клиентов**
- `refreshPlateLookup()` вызывает `GET /api/lists/plates` → `all_plates_with_type()`
- Клиент с `list_id = NULL` **не должен** попадать в `all_plates_with_type()` — JOIN с `lists` естественным образом его исключит
- Действие: обязательно проверить это после изменения схемы — это самая важная проверка для корректности поведения каналов

---

## 7. Финальный рекомендуемый порядок выполнения

```text
[ ] 1.1  Схема: сделать clients.list_id nullable, убрать NOT NULL и CASCADE
[ ] 1.2  Создать clients_repository.py с классом ClientDatabase
[ ] 1.3  Упростить lists_repository.py (убрать CRUD entry, оставить критичные для каналов методы)
[ ] 1.4  Подключить ClientDatabase в container.py
[ ] 2.3  Добавить схемы ClientPayload и AttachClientPayload
[ ] 2.1  Создать routers/clients.py со всеми эндпоинтами /api/clients/*
[ ] 2.2  Обновить routers/lists.py (убрать entry endpoints, добавить /api/lists/{id}/clients)
[ ] 2.4  Зарегистрировать clients_router в main.py
[ ] 5.2  Переименовать find_entry_by_plate → find_client_by_plate во всех местах вызова
[ ] 3.1  HTML: переименовать вкладку, добавить подвкладки, добавить новые modals
[ ] 4.1  Создать модуль clients.js
[ ] 4.2  Провести рефакторинг lists.js (убрать entry-логику, добавить список участников + client picker)
[ ] 4.3  Обновить app.js (импорт clients.js, переключение подвкладок)
[ ] 4.4  Добавить диалоги подтверждения для всех операций
[ ] 5.1  Проверить wiring контейнера (functions lists_db для каналов по-прежнему подключены правильно)
[ ] 5.3  Обновить test_lists_repository.py
[ ] --   Ручная проверка: фильтрация каналов по-прежнему работает (plate_in_lists, plate_in_list_type)
[ ] --   Ручная проверка: all_plates_with_type не включает открепленных клиентов
[ ] --   Ручная проверка: обогащение событий (find_client_by_plate) по-прежнему работает
```
