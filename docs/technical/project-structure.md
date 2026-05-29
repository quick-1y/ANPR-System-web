# Структура проекта

Этот файл содержит вынесенное дерево проекта и краткие пояснения по директориям. Он удобен для навигации по репозиторию без перегрузки корневого README.

## Дерево проекта

```text
ANPR-System-v0.8_web/
├── anpr/                          # ANPR core: detection, recognition, pipeline
│   ├── countries/                 # YAML-конфиги форматов номеров
│   ├── detection/                 # YOLO detector, motion detector
│   ├── models/                    # ML-модели YOLO и OCR
│   │   ├── ocr_crnn/
│   │   └── yolo/
│   ├── pipeline/                  # ANPRPipeline, TrackAggregator, factory
│   ├── postprocessing/            # Валидация номера, загрузка country configs
│   ├── preprocessing/             # Предобработка изображения номера
│   ├── recognition/               # CRNN recognizer
│   └── model_config.py            # Конфигурация путей к моделям
├── app/                           # Application layer
│   ├── api/                       # Основной FastAPI API server
│   │   ├── routers/               # Channels, events, zones, settings, data, debug, auth, users, ...
│   │   ├── auth_utils.py
│   │   ├── container.py
│   │   ├── deps.py
│   │   ├── main.py
│   │   └── schemas.py
│   ├── shared/                    # Общие сервисы приложения
│   │   ├── backup_service.py
│   │   └── data_lifecycle.py
│   ├── web/                       # Статический frontend
│   │   ├── js/                    # JS-модули SPA
│   │   │   ├── api.js
│   │   │   ├── app.js
│   │   │   ├── backup.js
│   │   │   ├── channels.js
│   │   │   ├── controllers.js
│   │   │   ├── debug.js
│   │   │   ├── events.js
│   │   │   ├── help.js
│   │   │   ├── journal.js
│   │   │   ├── lists.js
│   │   │   ├── plate-size-editor.js
│   │   │   ├── roi-editor.js
│   │   │   ├── settings.js
│   │   │   ├── state.js
│   │   │   ├── ui.js
│   │   │   ├── users.js
│   │   │   ├── video-grid.js
│   │   │   └── zones.js
│   │   ├── assets/
│   │   ├── favicon/
│   │   └── images/
│   └── worker/                    # Retention worker service
│       └── main.py
├── common/                        # Общие утилиты
│   └── logging.py
├── config/                        # Управление настройками
│   ├── settings.yaml
│   ├── settings_manager.py
│   ├── settings_normalizer.py
│   ├── settings_repository.py
│   └── settings_schema.py
├── controllers/                   # Интеграция с аппаратными контроллерами
│   ├── adapters/
│   │   └── dtwonder2ch.py
│   ├── base.py
│   ├── registry.py
│   └── service.py
├── database/                      # Репозитории и схема БД
│   ├── postgres/
│   │   └── schema.sql
│   ├── base.py
│   ├── channel_repository.py
│   ├── controller_repository.py
│   ├── errors.py
│   ├── lists_repository.py
│   ├── postgres_event_repository.py
│   ├── user_repository.py
│   └── zones_repository.py
├── nginx/                         # Конфиг reverse proxy
│   └── default.conf
├── runtime/                       # Выполнение каналов и runtime-сервисы
│   ├── channel_runtime.py
│   ├── debug.py
│   └── event_bus.py
├── tests/                         # Тесты ключевых компонентов
│   ├── test_auth_deps.py
│   ├── test_auth_router.py
│   ├── test_auth_utils.py
│   ├── test_channel_repository_zones.py
│   ├── test_direction_estimator.py
│   ├── test_events_repository_zones.py
│   ├── test_lists_repository.py
│   ├── test_motion_detector.py
│   ├── test_permission_guards.py
│   ├── test_plate_validator.py
│   ├── test_settings_storage_cleanup.py
│   ├── test_track_aggregator.py
│   ├── test_user_repository.py
│   ├── test_users_router.py
│   ├── test_zone_eligibility.py
│   └── test_zones_repository.py
├── .planning/
│   └── codebase/                  # Аналитические markdown-файлы по проекту
├── AGENTS.md
├── Dockerfile
├── LICENSE
├── README.md
├── docker-compose.yml
├── pyproject.toml
├── poetry.lock
└── .env.example
```

## Как читать структуру

### `anpr/`
Ядро распознавания. Здесь сосредоточены детекция номера, motion gate, OCR, агрегация результатов по треку, постобработка и country-конфиги.

### `app/`
Прикладной слой. Содержит основной API, web UI, retention worker и shared-сервисы.

### `runtime/`
Потоковое выполнение каналов. Здесь живут поток канала, preview cache, event bus и debug state.

### `config/`
Центральная точка управления настройками, их нормализацией и сохранением.

### `database/`
Слой доступа к данным: события, каналы, контроллеры, списки и клиенты (номера), SQL-схема PostgreSQL. Каждый репозиторий наследует `PooledDatabase` и выполняет lazy bootstrap своей схемы.

### `controllers/`
Интеграция с внешними аппаратными контроллерами реле и шлагбаумов.

### `common/`
Общие утилиты, прежде всего логирование.

### `tests/`
Набор тестов для критичных частей логики распознавания и обработки.

### `.planning/codebase/`
Служебные аналитические документы по архитектуре, стеку, структуре, интеграциям и соглашениям. Полезны при сопровождении документации и работе агентов.

## Связанные документы

- Деплой и конфигурация: [`setup.md`](../guides/setup.md)
- Аутентификация и пользователи: [`auth.md`](auth.md)
- API endpoints: [`endpoints.md`](endpoints.md)
- Диаграммы: [`diagrams.md`](diagrams.md)
- Описание модулей: [`modules.md`](modules.md)
- Технологический стек: [`technology-stack.md`](technology-stack.md)
- ANPR pipeline: [`anpr-pipeline.md`](anpr-pipeline.md)
- Roadmap inference-настроек: [`inference-roadmap.md`](inference-roadmap.md)
