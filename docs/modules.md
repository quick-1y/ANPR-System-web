# Описание модулей

Этот файл содержит краткое описание основных модулей проекта и ключевых файлов. Для навигации по директориям см. также [`project-structure.md`](project-structure.md).

## `app/` — приложение

| Файл / директория | Ответственность |
|---|---|
| `app/api/main.py` | FastAPI app, middleware, роутеры, lifecycle |
| `app/api/auth.py` | `APIKeyMiddleware`: валидация ключа из заголовка / query param; исключения для health, SSE, preview |
| `app/api/container.py` | `AppContainer`: DI-контейнер всех сервисов; `build()`, `startup()`, `shutdown()` |
| `app/api/deps.py` | FastAPI зависимости (`get_container()`) |
| `app/api/schemas.py` | Pydantic-модели запросов и ответов |
| `app/api/routers/channels.py` | CRUD каналов, start/stop/restart, snapshot, MJPEG, health |
| `app/api/routers/events.py` | Журнал событий, детали, медиа, SSE-поток |
| `app/api/routers/controllers.py` | CRUD аппаратных контроллеров, тест реле |
| `app/api/routers/lists.py` | Управление списками и клиентами |
| `app/api/routers/settings.py` | Глобальные настройки и логика перезапуска pipeline при изменении параметров |
| `app/api/routers/data.py` | Retention policy, ручной запуск, экспорт, backup / restore |
| `app/api/routers/system.py` | Health check, CPU/RAM, статус БД, Web UI |
| `app/api/routers/debug.py` | Debug-настройки, overlay state, лог-панель SSE |
| `app/worker/main.py` | `RetentionScheduler`: async цикл retention; отдельный FastAPI-сервис |
| `app/shared/data_lifecycle.py` | `DataLifecycleService`: cleanup событий/медиа, контроль размера, CSV/ZIP export |
| `app/web/` | Статика web UI: HTML, JS, CSS, иконки, изображения, флаги |

## `runtime/` — выполнение каналов

| Файл / директория | Ответственность |
|---|---|
| `runtime/channel_runtime.py` | `ChannelProcessor`: запуск, остановка и restart потоков каналов; preview cache; метрики |
| `runtime/event_bus.py` | `EventBus`: in-memory pub/sub для SSE на базе `asyncio.Queue` |
| `runtime/event_sink.py` | `EventSink`: запись событий в PostgreSQL через репозиторий |
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
| `database/lists_repository.py` | `ListDatabase`: CRUD для списков и клиентов, проверка вхождения номера |
| `database/postgres/schema.sql` | SQL-схема инициализации PostgreSQL |
| `database/errors.py` | Ошибки слоя хранения, включая `StorageUnavailableError` |

## `config/` — конфигурация

| Файл / директория | Ответственность |
|---|---|
| `config/settings_manager.py` | `SettingsManager`: оркестрация настроек и API доступа ко всем секциям |
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
| `tests/` | Тесты ключевых компонентов, включая validator, motion detector, direction estimator и track aggregator |
| `nginx/` | Конфигурация reverse proxy |
| `.planning/codebase/` | Аналитические markdown-файлы по архитектуре, стеку, структуре, соглашениям и интеграциям |
| `Dockerfile` | Сборка приложения |
| `docker-compose.yml` | Компоновка сервисов `nginx`, `api`, `retention_worker`, `postgres` |
| `pyproject.toml` | Python-зависимости проекта (Poetry) |
