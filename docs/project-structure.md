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
│   │   ├── routers/               # Channels, events, settings, data, debug, ...
│   │   ├── auth.py
│   │   ├── container.py
│   │   ├── deps.py
│   │   ├── main.py
│   │   └── schemas.py
│   ├── shared/                    # Общие сервисы приложения
│   │   └── data_lifecycle.py
│   ├── web/                       # Статический frontend
│   │   ├── assets/
│   │   ├── favicon/
│   │   └── images/
│   └── worker/                    # Retention worker service
│       └── main.py
├── common/                        # Общие утилиты
│   └── logging.py
├── config/                        # Управление настройками
│   ├── settings_migrations/
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
│   ├── errors.py
│   ├── lists_repository.py
│   └── postgres_event_repository.py
├── nginx/                         # Конфиг reverse proxy
│   └── default.conf
├── runtime/                       # Выполнение каналов и runtime-сервисы
│   ├── channel_runtime.py
│   ├── debug.py
│   ├── event_bus.py
│   └── event_sink.py
├── tests/                         # Тесты ключевых компонентов
│   ├── test_direction_estimator.py
│   ├── test_motion_detector.py
│   ├── test_plate_validator.py
│   └── test_track_aggregator.py
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
Центральная точка управления настройками, их нормализацией, миграцией и сохранением.

### `database/`
Слой доступа к данным: события, списки и клиенты (номера), SQL-схема PostgreSQL.

### `controllers/`
Интеграция с внешними аппаратными контроллерами реле и шлагбаумов.

### `common/`
Общие утилиты, прежде всего логирование.

### `tests/`
Набор тестов для критичных частей логики распознавания и обработки.

### `.planning/codebase/`
Служебные аналитические документы по архитектуре, стеку, структуре, интеграциям и соглашениям. Полезны при сопровождении документации и работе агентов.

## Связанные документы

- Диаграммы: [`diagrams.md`](diagrams.md)
- Описание модулей: [`modules.md`](modules.md)
- Технологический стек: [`technology-stack.md`](technology-stack.md)
