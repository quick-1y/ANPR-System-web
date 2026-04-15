# Описание модулей

Этот файл содержит краткое описание основных модулей проекта и ключевых файлов. Для навигации по директориям см. также [`project-structure.md`](project-structure.md).

## `app/` — приложение

| Файл / директория | Ответственность |
|---|---|
| `app/api/main.py` | FastAPI app, middleware, роутеры, lifecycle |
| `app/api/auth_utils.py` | JWT-утилиты: `hash_password()`, `verify_password()`, `create_access_token()`, `decode_access_token()` |
| `app/api/container.py` | `AppContainer`: DI-контейнер всех сервисов; `build()`, `startup()`, `shutdown()` |
| `app/api/deps.py` | FastAPI зависимости: `get_container()`, `get_current_user()`, `require_role()`, `require_permission()` |
| `app/api/schemas.py` | Pydantic-модели запросов и ответов (включая `LoginRequest`, `LoginResponse`, `UserOut`, `UserCreate`, `UserUpdate`, `UserPasswordChange`) |
| `app/api/routers/auth.py` | Auth endpoints: `POST /api/auth/login`, `POST /api/auth/logout`, `GET /api/auth/me`, `GET /api/permissions/available` (admin-only, возвращает `{key,label,group}`) |
| `app/api/routers/users.py` | User management (admin-only): list, create, get, update, change password, deactivate |
| `app/api/routers/channels.py` | CRUD каналов, start/stop/restart, snapshot, MJPEG, health — авторизованный |
| `app/api/routers/events.py` | Журнал событий, детали, медиа, SSE-поток — авторизованный |
| `app/api/routers/controllers.py` | CRUD аппаратных контроллеров, тест реле — **только Admin** |
| `app/api/routers/clients.py` | CRUD клиентов, поиск, прикрепление к спискам / открепление — авторизованный |
| `app/api/routers/lists.py` | CRUD списков (plate lists), получение участников списка, поиск по номеру, все номера с типами — авторизованный |
| `app/api/routers/settings.py` | Глобальные настройки и логика перезапуска pipeline — **только Admin** |
| `app/api/routers/data.py` | Retention policy, экспорт, backup / restore — **только Admin** |
| `app/api/routers/system.py` | Health check, CPU/RAM, статус БД, Web UI |
| `app/api/routers/debug.py` | Debug-настройки, overlay state, лог-панель SSE — **только Admin** |
| `app/worker/main.py` | `RetentionScheduler`: async цикл retention; отдельный FastAPI-сервис |
| `app/shared/backup_service.py` | `BackupService`: бэкап и восстановление базы данных и settings.yaml |
| `app/shared/data_lifecycle.py` | `DataLifecycleService`: cleanup событий/медиа, контроль размера, CSV/ZIP export |
| `app/web/index.html` | Единственная HTML-страница SPA; включает `#login-overlay` для аутентификации и кнопку «Выход» в topbar |
| `app/web/js/api.js` | HTTP-слой: `getToken/setToken` (JWT в `localStorage`), `jfetch()` (Bearer), `apiUrl()` (?token=), `loginRequest()`, `getCurrentUser()`, `showLoginOverlay()` |
| `app/web/js/state.js` | Глобальное состояние SPA; `state.currentUser`, `state.allClients`, `state.listMembers`, `state.lists`, `state.plateLookup` и др.; `setCurrentUser()`, `isAdmin()`, `hasPermission(key)` |
| `app/web/js/clients.js` | Модуль клиентов: таблица всех клиентов, карточка клиента (просмотр/редактирование/удаление), прикрепление к списку, отвязка, поиск с дебаунсом |
| `app/web/js/app.js` | Точка входа: проверка JWT при старте, показ login overlay, инициализация после аутентификации, `applyTabVisibility()` после получения пользователя, logout; вызывает `initUsersPane()` для admin |
| `app/web/js/users.js` | Управление пользователями (Settings → Пользователи, admin-only): список, создание, редактирование, смена пароля, деактивация |
| `app/web/js/backup.js` | Backup/restore с JWT Bearer-заголовками |
| `app/web/` | Прочая статика web UI: JS-модули, CSS, иконки, изображения, флаги |

## `runtime/` — выполнение каналов

| Файл / директория | Ответственность |
|---|---|
| `runtime/channel_runtime.py` | `ChannelProcessor`: запуск, остановка и restart потоков каналов; preview cache; метрики; запись событий в PostgreSQL напрямую через `PostgresEventDatabase` |
| `runtime/event_bus.py` | `EventBus`: in-memory pub/sub для SSE на базе `asyncio.Queue` |
| `runtime/debug.py` | `DebugRegistry`: хранение debug overlay state по каналу с TTL |

## `anpr/` — ядро распознавания

| Файл / директория | Ответственность |
|---|---|
| `anpr/detection/yolo_detector.py` | `YOLODetector`: YOLOv8 + tracking; fallback; size filter; bbox padding |
| `anpr/detection/motion_detector.py` | `MotionDetector`: motion gate и гистерезис по счётчикам кадров |
| `anpr/preprocessing/plate_preprocessor.py` | `PlatePreprocessor`: CLAHE, морфология, перспективная коррекция, выравнивание |
| `anpr/recognition/crnn_recognizer.py` | `CRNNRecognizer`: INT8 CRNN; `recognize_batch()`; CTC decode |
| `anpr/recognition/crnn.py` | Архитектура CRNN (Conv + RNN backbone) |
| `anpr/pipeline/anpr_pipeline.py` | `ANPRPipeline`, `TrackAggregator`, `TrackDirectionEstimator` |
| `anpr/pipeline/factory.py` | Сборка компонентов pipeline и shared OCR singleton |
| `anpr/postprocessing/validator.py` | `PlatePostProcessor`: нормализация, коррекции, валидация |
| `anpr/postprocessing/country_config.py` | `CountryConfigLoader`: загрузка YAML-конфигов стран и компиляция regex |
| `anpr/model_config.py` | `AnprModelConfig`: пути к моделям и связанные параметры |
| `anpr/countries/` | YAML-конфиги форматов номеров по странам |
| `anpr/models/` | Файлы моделей YOLO и OCR (обычно не хранятся в git) |

## `controllers/` — аппаратные контроллеры

| Файл / директория | Ответственность |
|---|---|
| `controllers/service.py` | `ControllerService`: отправка HTTP-команд контроллерам; error cooldown; async dispatch |
| `controllers/registry.py` | Реестр типов адаптеров |
| `controllers/base.py` | Базовый интерфейс адаптера |
| `controllers/adapters/dtwonder2ch.py` | Адаптер DTWONDER2CH: построение URL команды по relay index и mode |

## `database/` — хранение данных

| Файл / директория | Ответственность |
|---|---|
| `database/postgres_event_repository.py` | `PostgresEventDatabase`: insert, pagination, fetch, delete, export |
| `database/clients_repository.py` | `ClientDatabase`: CRUD клиентов, поиск, прикрепление/открепление от списка |
| `database/lists_repository.py` | `ListDatabase`: CRUD списков, проверка вхождения номера (`plate_in_list_type`, `plate_in_lists`), обогащение событий клиентом (`find_client_by_plate` — ищет по нормализованному номеру среди всех активных клиентов, вне зависимости от наличия списка; `list_type`/`list_name` будут `None` если клиент не прикреплён к списку) |
| `database/user_repository.py` | `UserDatabase`: CRUD пользователей, seed admin по умолчанию |
| `database/channel_repository.py` | `ChannelDatabase`: CRUD каналов и всех их настроек; нормализация данных (region, direction, controller_id, фильтры) |
| `database/controller_repository.py` | `ControllerDatabase`: CRUD аппаратных контроллеров (name, type, address, password, relays) |
| `database/postgres/schema.sql` | SQL-схема инициализации PostgreSQL (events, users); каналы и контроллеры бутстрапятся в своих репозиториях |
| `database/errors.py` | Ошибки слоя хранения, включая `StorageUnavailableError` |

## `config/` — конфигурация

| Файл / директория | Ответственность |
|---|---|
| `config/settings_manager.py` | `SettingsManager`: оркестрация глобальных настроек (тема, grid, reconnect, storage, logging и др.); каналы и контроллеры хранятся в БД |
| `config/settings_repository.py` | Чтение и запись `settings.yaml` с file lock |
| `config/settings_normalizer.py` | Нормализация, дефолты, upgrade legacy-конфигов |
| `config/settings_schema.py` | Схема и дефолты всех секций |
| `config/settings_migrations/` | Миграции формата настроек |
| `config/settings.yaml` | Рабочая runtime-конфигурация |

## `common/` — общие утилиты

| Файл / директория | Ответственность |
|---|---|
| `common/logging.py` | `configure_logging()`: `HourlyFileHandler`, `LiveDebugHandler`, `ServiceNameFilter` |

## Остальные важные директории

| Директория / файл | Назначение |
|---|---|
| `tests/` | Тесты ключевых компонентов: validator, motion detector, direction estimator, track aggregator, user repository, JWT utils, auth deps, auth router, permission guards; `test_lists_repository.py` — тесты `ListDatabase` и `ClientDatabase` (нормализация номеров, CRUD, прикрепление/открепление, channel automation methods) |
| `nginx/` | Конфигурация reverse proxy |
| `.planning/codebase/` | Аналитические markdown-файлы по архитектуре, стеку, структуре, соглашениям и интеграциям |
| `Dockerfile` | Сборка приложения |
| `docker-compose.yml` | Компоновка сервисов `nginx`, `api`, `retention_worker`, `postgres` |
| `pyproject.toml` | Python-зависимости проекта (Poetry) |
