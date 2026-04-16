# REST и streaming endpoints

Кратко:
- Web UI: корневая страница `/`;
- Channels / Events / Controllers / Lists / Settings — основное API оператора;
- Debug и telemetry endpoints — для наблюдения и диагностики;
- Worker endpoints — для retention и фоновых сервисных операций.

---

## REST и streaming endpoints

### Web UI

| Метод | Путь | Описание |
|---|---|---|
| `GET` | `/` | Операторская панель (index.html) |

### Auth

| Метод | Путь | Описание | Доступ |
|---|---|---|---|
| `POST` | `/api/auth/login` | Аутентификация (логин + пароль) -> JWT | Публичный |
| `POST` | `/api/auth/logout` | Аудит-лог выхода; клиент удаляет токен | Авторизованный |
| `GET` | `/api/auth/me` | Текущий пользователь (роль, разрешения) | Авторизованный |
| `GET` | `/api/permissions/available` | Список ключей разрешений с метаданными `{key, label, group}` | *Требует tab:settings* |

Все остальные API-эндпоинты (кроме `/api/health`) требуют валидный JWT-токен в заголовке `Authorization: Bearer <token>` или query-параметре `?token=<jwt>`.

**Уровни доступа:**
- *Публичный* — без токена
- *Авторизованный* — любой активный пользователь с валидным JWT
- **Только superadmin** — требует роль `superadmin` (технический root-аккаунт)
- *Требует tab:settings* — доступно пользователям с разрешением `tab:settings` (или superadmin)

**Детали аутентификации:**
- `POST /api/auth/login` — брутфорс-защита: макс. 5 неудачных попыток в минуту с одного IP (`HTTP 429`). Счётчик сбрасывается при успешном входе.
- `POST /api/auth/login` — поле `warn_default_password: bool` в ответе: `true`, если пароль superadmin ни разу не менялся (поле `password_changed_at IS NULL`).
- `POST /api/auth/logout` — требует токен; фиксирует выход в аудит-лог.
- Аутентификация только через JWT. Статические API-ключи не поддерживаются.

### Users *(требует tab:settings)*

| Метод | Путь | Описание |
|---|---|---|
| `GET` | `/api/users` | Список всех пользователей |
| `POST` | `/api/users` | Создать пользователя |
| `GET` | `/api/users/{id}` | Получить пользователя по ID |
| `PUT` | `/api/users/{id}` | Обновить роль, разрешения, статус активности |
| `PUT` | `/api/users/{id}/password` | Сменить пароль (admin — любой; пользователь — только свой) |
| `DELETE` | `/api/users/{id}` | Деактивировать пользователя (мягкое удаление; нельзя применить к себе) |

Защита от самоблокировки администратора:
- Нельзя деактивировать собственную учётную запись.
- Нельзя снять роль `admin` с себя, если вы единственный активный администратор.

### Channels

| Метод | Путь | Описание |
|---|---|---|
| `GET` | `/api/channels` | Список каналов с метриками и debug state |
| `POST` | `/api/channels` | Создать канал |
| `PUT` | `/api/channels/{channel_id}` | Обновить канал |
| `GET` | `/api/channels/last-plates` | Последний распознанный номер по каждому каналу |
| `GET` | `/api/channels/{channel_id}/config` | Получить конфигурацию канала |
| `PUT` | `/api/channels/{channel_id}/config` | Обновить базовую конфигурацию |
| `PUT` | `/api/channels/{channel_id}/ocr` | Обновить OCR-параметры (best_shots, cooldown, confidence, max_ocr_attempts) |
| `PUT` | `/api/channels/{channel_id}/filter` | Обновить фильтры размера и plate lists |
| `DELETE` | `/api/channels/{channel_id}` | Удалить канал |
| `POST` | `/api/channels/{channel_id}/start` | Запустить поток канала |
| `POST` | `/api/channels/{channel_id}/stop` | Остановить поток канала |
| `POST` | `/api/channels/{channel_id}/restart` | Перезапустить поток канала |
| `GET` | `/api/channels/{channel_id}/health` | Метрики канала |
| `GET` | `/api/channels/{channel_id}/snapshot.jpg` | Единичный JPEG кадр |
| `GET` | `/api/channels/{channel_id}/preview/status` | Готовность preview |
| `GET` | `/api/channels/{channel_id}/preview.mjpg` | MJPEG-поток (`multipart/x-mixed-replace`) |

### Zones

| Метод | Путь | Описание |
|---|---|---|
| `GET` | `/api/zones` | Список всех зон (id, name, capacity, occupied, free) |
| `POST` | `/api/zones` | Создать зону |
| `GET` | `/api/zones/{zone_id}` | Детали зоны: name, capacity, occupancy, список привязанных каналов |
| `PUT` | `/api/zones/{zone_id}` | Обновить название и вместимость зоны |
| `DELETE` | `/api/zones/{zone_id}` | Удалить зону; каскадно снимает назначение zone_id/zone_channel_type у привязанных каналов |

### Events

| Метод | Путь | Описание |
|---|---|---|
| `GET` | `/api/events` | Журнал событий; параметры: `limit`, `before_ts`, `before_id`, `channel_id`, `plate`; сортировка `time DESC, id DESC` |
| `GET` | `/api/events/item/{event_id}` | Детали события |
| `GET` | `/api/events/item/{event_id}/media/{kind}` | Медиафайл события (`kind=frame` или `plate`) |
| `GET` | `/api/events/stream` | SSE-поток live событий (`text/event-stream`; keepalive `: ping`; auto-retry) |

### Controllers *(только superadmin)*

| Метод | Путь | Описание |
|---|---|---|
| `GET` | `/api/controllers` | Список контроллеров |
| `POST` | `/api/controllers` | Создать контроллер |
| `PUT` | `/api/controllers/{controller_id}` | Обновить контроллер |
| `DELETE` | `/api/controllers/{controller_id}` | Удалить контроллер (блокируется, если используется каналом) |
| `POST` | `/api/controllers/{controller_id}/test` | Отправить тестовую команду реле |

### Clients

| Метод | Путь | Описание |
|---|---|---|
| `GET` | `/api/clients` | Список всех клиентов (включая неприкреплённых к спискам) |
| `POST` | `/api/clients` | Создать клиента (без привязки к списку) |
| `GET` | `/api/clients/search?q=` | Поиск клиентов по ФИО и номеру (ILIKE) |
| `GET` | `/api/clients/{client_id}` | Получить клиента по ID |
| `PUT` | `/api/clients/{client_id}` | Обновить поля клиента |
| `DELETE` | `/api/clients/{client_id}` | Мягкое удаление клиента |
| `POST` | `/api/clients/{client_id}/attach` | Прикрепить клиента к списку (`{list_id: int}`) |
| `DELETE` | `/api/clients/{client_id}/attach` | Открепить клиента от списка (list_id → NULL) |

### Plate Lists

| Метод | Путь | Описание |
|---|---|---|
| `GET` | `/api/lists` | Список всех plate lists |
| `POST` | `/api/lists` | Создать список |
| `PUT` | `/api/lists/{list_id}` | Обновить метаданные списка |
| `DELETE` | `/api/lists/{list_id}` | Удалить список (клиенты сохраняются, list_id → NULL) |
| `GET` | `/api/lists/{list_id}/clients` | Клиенты, прикреплённые к этому списку |
| `GET` | `/api/lists/entry-by-plate` | Найти клиента по номеру (используется обогащением событий) |
| `GET` | `/api/lists/plates` | Все номера с типами списков (используется фильтрацией каналов) |

### Settings *(только superadmin)*

| Метод | Путь | Описание |
|---|---|---|
| `GET` | `/api/settings` | Все глобальные настройки |
| `PUT` | `/api/settings` | Обновить настройки (изменение параметров распознавания номеров и DSN перезапускает pipeline) |
| `GET` | `/api/countries` | Список доступных конфигураций стран |

### Data & Export *(только superadmin)*

| Метод | Путь | Описание |
|---|---|---|
| `GET` | `/api/data/policy` | Retention policy |
| `PUT` | `/api/data/policy` | Обновить retention policy |
| `POST` | `/api/data/retention/run` | Запустить retention cycle вручную |
| `GET` | `/api/data/export/events.csv` | Экспорт событий в CSV |
| `POST` | `/api/data/export/bundle` | Экспорт событий в ZIP (с медиа по выбору) |
| `GET` | `/api/data/backup/database` | Скачать бэкап базы данных (ZIP с JSON-дампом и манифестом) |
| `POST` | `/api/data/backup/database/restore` | Восстановить БД из бэкапа (multipart upload). Полностью перезаписывает текущие данные, затем перезапускает приложение |
| `GET` | `/api/data/backup/settings` | Скачать текущий settings.yaml |
| `POST` | `/api/data/backup/settings/restore` | Восстановить settings.yaml из файла (multipart upload). Валидирует, нормализует и атомарно сохраняет настройки, перезапускает pipeline |

### System & Telemetry

| Метод | Путь | Описание |
|---|---|---|
| `GET` | `/api/health` | Health check API |
| `GET` | `/api/system/resources` | CPU и RAM (psutil) |
| `GET` | `/api/storage/status` | Статус PostgreSQL |
| `GET` | `/api/telemetry/channels` | Метрики каналов (FPS, latency, reconnect_count и др.) |

### Debug *(только superadmin)*

| Метод | Путь | Описание |
|---|---|---|
| `GET` | `/api/debug/settings` | Debug-настройки |
| `PUT` | `/api/debug/settings` | Обновить debug-настройки |
| `GET` | `/api/debug/channels` | Метрики + debug state каналов |
| `GET` | `/api/debug/state` | Агрегированный debug state (overlay: bbox, OCR, direction) |
| `GET` | `/api/debug/logs` | Последние логи (snapshot) |
| `GET` | `/api/debug/logs/stream` | SSE-поток логов в реальном времени |

Debug overlay (bbox, OCR-текст, direction) — только данные; отрисовка выполняется в web UI поверх `<img>`. Overlay очищается по TTL.

### Worker

| Метод | Путь | Описание |
|---|---|---|
| `GET` | `/worker/health` | Health check worker |
| `POST` | `/worker/retention/run` | Ручной запуск retention cycle через worker |
