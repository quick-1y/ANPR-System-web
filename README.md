# ANPR System v0.8 Web

![Python](https://img.shields.io/badge/Python-3.13-blue.svg)
![FastAPI](https://img.shields.io/badge/API-FastAPI-009688.svg)
![Web UI](https://img.shields.io/badge/UI-Web--only-4CAF50.svg)
![YOLOv8](https://img.shields.io/badge/Detection-YOLOv8-red.svg)
![CRNN](https://img.shields.io/badge/OCR-CRNN-orange.svg)
![Storage](https://img.shields.io/badge/Data-PostgreSQL-blue.svg)

Многоканальная система автоматического распознавания автомобильных номеров с web-интерфейсом оператора.

Система выполняет server-side обработку видеопотоков, распознаёт номера, сохраняет события в PostgreSQL, публикует live-обновления в браузер через SSE и отдаёт live preview по MJPEG без отдельного медиасервера.

---

## Документация

| Раздел | Что внутри |
|--------|------------|
| [Диаграммы](docs/diagrams.md) | Архитектурные схемы, pipeline, event flow, retention |
| [Описание модулей](docs/modules.md) | Назначение основных директорий и ключевых файлов |
| [Технологический стек](docs/technology-stack.md) | Языки, runtime, инфраструктура и ключевые зависимости |
| [Структура проекта](docs/project-structure.md) | Дерево проекта и навигация по репозиторию |
| [API endpoints](docs/endpoints.md) | Web UI, REST, SSE, debug, worker и export endpoints |
| [ANPR pipeline](docs/anpr-pipeline.md) | Алгоритмы ядра, OCR по треку, сценарии и ключевые параметры |


---

## Возможности

- многоканальная обработка видео: отдельный поток исполнения на каждый канал;
- server-side ANPR pipeline: детекция (YOLOv8), OCR (CRNN), агрегация по треку, постобработка, cooldown;
- web UI оператора: наблюдение, журнал событий, управление списками, настройки;
- live preview по MJPEG из того же channel runtime;
- live-события через SSE без опроса (long-lived stream с keepalive);
- управление каналами через API: создать, изменить, запустить, остановить, перезапустить;
- настройка ROI, размера номерного знака, OCR порогов, cooldown, motion gate;
- white / black / custom plate lists с фильтрацией событий для автоматической сработки реле;
- управление аппаратными контроллерами через API (тип DTWONDER2CH);
- retention / cleanup / CSV / ZIP export через отдельный worker-сервис;
- backup / restore: полный бэкап PostgreSQL и settings.yaml с валидацией и восстановлением через UI;
- PostgreSQL — единственный поддерживаемый backend хранения данных.

---

## Архитектура

Система разделена на три контура:

1. **API service** (`app/api/`) — FastAPI-приложение: web UI, REST API, управление каналами, SSE-поток событий, preview endpoints.
2. **Channel runtime / ANPR core** (`runtime/`, `anpr/`) — для каждого канала создаётся отдельный поток, который открывает источник видео, формирует MJPEG preview в памяти и прогоняет кадры через полный ANPR pipeline.
3. **Retention worker** (`app/worker/`) — отдельный FastAPI-сервис для очистки старых событий, удаления медиа, контроля размера хранилища и экспорта.

Подробные схемы вынесены в [`docs/diagrams.md`](docs/diagrams.md), а описание ключевых компонентов — в [`docs/modules.md`](docs/modules.md).

---

## Быстрый старт

Поддерживаемая модель runtime: Docker Compose.

### Требования

- Docker Engine 24+
- Docker Compose v2+
- файлы моделей в `anpr/models/yolo/` и `anpr/models/ocr_crnn/`

### Подготовка

```bash
cp .env.example .env
# при необходимости отредактировать .env
```

### Запуск

```bash
docker compose up -d --build
```

Поднимаются четыре сервиса:

| Сервис | Описание | Внутренний адрес |
|---|---|---|
| `nginx` | Reverse proxy, единственная публичная точка входа | `HTTP_PORT` (по умолчанию `8080`) |
| `api` | FastAPI + Web UI + channel runtime | `api:8080` |
| `retention_worker` | Retention / cleanup / export | `retention_worker:8092` |
| `postgres` | PostgreSQL 16 с init-схемой | `postgres:5432` (только внутри сети) |

**Volumes:**
- `pgdata` — данные PostgreSQL
- `media_data` — `data/screenshots` и `data/exports`
- `logs_data` — `logs`

### Проверка

```bash
curl http://localhost:8080/api/health
curl http://localhost:8080/worker/health
curl http://localhost:8080/api/channels
curl -o snapshot.jpg http://localhost:8080/api/channels/1/snapshot.jpg
```

### Обновление / сброс

```bash
# Пересборка
docker compose build --no-cache && docker compose up -d
```

```bash
# Остановка
docker compose down
```

```bash
# Полный сброс данных (удаляет volumes)
docker compose down -v
```

---

## Конфигурация

| Файл | Назначение |
|---|---|
| `.env` | Переменные окружения для Docker Compose (`POSTGRES_*`, `HTTP_PORT`, `LOG_LEVEL`, `API_KEY`, `SETTINGS_PATH`) |
| `.env.example` | Шаблон `.env` |
| `config/settings.yaml` | Runtime-конфигурация: каналы, ROI, OCR, retention, контроллеры |

API и retention_worker используют один и тот же `SETTINGS_PATH=/app/config/settings.yaml`. PostgreSQL — единственный backend runtime-данных.

### Версионирование `settings.yaml`

- `settings_lineage: mainline` — каноническая линия схемы.
- `settings_version: 1` — текущая версия для этой линии.
- При загрузке legacy-конфиги (без `settings_lineage`) автоматически мигрируют до текущей схемы и сохраняются обратно.
- `settings_version` выше поддерживаемой → явная ошибка (без silent downgrade).
- Неизвестная `settings_lineage` → явная ошибка (без принудительной перезаписи).
- Любое изменение структуры полей требует повышения версии схемы и обновления migration path.

---

## Поток данных

Диаграмма публикации событий и обслуживания хранилища вынесена в [`docs/diagrams.md`](docs/diagrams.md).

### Шаги обработки

1. **Подключение канала** — при старте API читает каналы из `config/settings.yaml`; `ChannelProcessor` создаёт `ChannelContext` и запускает поток для каждого `enabled=true` канала.
2. **Получение кадров** — поток открывает источник через `cv2.VideoCapture(source)` и в цикле вызывает `cap.read()`.
3. **Reconnect логика**:
   - `reconnect.signal_loss.enabled` — контроль таймаута чтения; при таймауте увеличивается `timeout_count`, выполняется controlled reconnect.
   - `reconnect.periodic.enabled` — принудительный reconnect каждые `interval_minutes` независимо от signal-loss.
   - При каждом reconnect увеличивается `reconnect_count`.
4. **Preview** — кадр кодируется в JPEG только при наличии активных MJPEG/snapshot потребителей (lazy encode), с частотой не выше `preview_fps_limit` (per-channel, по умолчанию 5 fps). Отключается через `debug.disable_video_output`.
5. **Детекция и распознавание** — кадр идёт в `YOLODetector.track()`, затем в `ANPRPipeline.process_frame()`.
6. **Сохранение события** — валидный номер (с прошедшим cooldown) записывается в PostgreSQL через `EventSink`, затем публикуется в `EventBus` для SSE.

---

## Контроллеры и plate lists

### Привязка контроллера к каналу

- Контроллер настраивается отдельно: имя, тип, адрес, пароль, 2 реле с режимом и хоткеем.
- В конфиге канала указываются `controller_id`, `controller_relay`, `list_filter_mode`, `list_filter_list_ids`.
- Режим реле задаётся в контроллере, а не в канале.
- При удалении контроллера, который используется каналом, API возвращает ошибку.

### Режимы фильтрации для автосработки реле

| Режим | Поведение |
|---|---|
| `all` | Реле срабатывает для любого номера, кроме номеров из black list |
| `whitelist` | Реле срабатывает только для номеров из списков типа `white`; black list блокирует |
| `custom` | Реле срабатывает только для номеров из выбранных списков (`list_filter_list_ids`); black list блокирует |

Приоритет black list абсолютный.

### Режимы реле

| Режим | Описание |
|---|---|
| `pulse` | Без таймера (timer_seconds=1) |
| `pulse_timer` | С таймером >= 1 с |

### Хоткеи реле

- Хоткей задаётся на конкретное реле конкретного контроллера.
- По нажатию в web UI отправляется `POST /api/controllers/{controller_id}/test`.
- Блокируется при фокусе в `input/textarea/select/contenteditable` или при key repeat.
- Дубликаты хоткеев в одном контроллере запрещены валидацией API.

---

## Хранение данных

### PostgreSQL (обязательно)

Все события и plate lists хранятся в PostgreSQL через `POSTGRES_DSN`.

**Таблицы:**

| Таблица | Поля |
|---|---|
| `events` | `id`, `timestamp`, `channel_id`, `channel`, `plate`, `plate_display`, `country`, `confidence`, `source`, `frame_path`, `plate_path`, `direction` |
| `plate_lists` | `id`, `name`, `type` |
| `plate_list_entries` | `id`, `list_id`, `plate`, `plate_normalized`, `comment` |

**Индексы:** `(timestamp DESC, id DESC)` по событиям; `plate_normalized` и `(list_id, plate_normalized) UNIQUE` по записям.

### Медиа и экспорт

- Медиа сохраняются в `storage.screenshots_dir`.
- CSV/ZIP-экспорт формируется сервером в памяти и отдаётся в браузер как файл для скачивания.(TODO, если будут проблемы с RAM, изменить метод сохранения перед экспортом на что то вроде `_export_dir = /tmp/anpr_exports`)
- Bundle export упаковывает CSV и доступные медиафайлы в ZIP.

Подробности по стеку и расположению директорий см. в [`docs/technology-stack.md`](docs/technology-stack.md) и [`docs/project-structure.md`](docs/project-structure.md).

---

## License

MIT
