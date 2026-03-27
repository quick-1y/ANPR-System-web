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

Крупные справочные разделы вынесены в папку [`docs/`](docs/):

| Раздел | Файл | Что внутри |
|---|---|---|
| Диаграммы | [`docs/diagrams.md`](docs/diagrams.md) | Архитектурные схемы, pipeline, event flow, retention |
| Описание модулей | [`docs/modules.md`](docs/modules.md) | Назначение основных директорий и ключевых файлов |
| Технологический стек | [`docs/technology-stack.md`](docs/technology-stack.md) | Языки, runtime, инфраструктура и ключевые зависимости |
| Структура проекта | [`docs/project-structure.md`](docs/project-structure.md) | Дерево проекта и навигация по репозиторию |

README остаётся точкой входа: быстрый обзор, запуск, конфигурация, ключевые алгоритмы и API.

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

## ANPR Pipeline

Схемы видеоввода, внутреннего pipeline и жизненного цикла событий вынесены в [`docs/diagrams.md`](docs/diagrams.md).

### Алгоритмы ядра

| Компонент | Алгоритм |
|---|---|
| **YOLODetector** | YOLOv8 с CUDA → CPU fallback; tracking fallback при потере трека; padding bbox перед кропом |
| **MotionDetector** | Абсолютная разность кадров → порог → гистерезис (счётчики активации/деактивации) |
| **PlatePreprocessor** | CLAHE + морфология → поиск четырёх точек → перспективная коррекция → выравнивание по HoughLines / min-area-rect |
| **CRNNRecognizer** | INT8-квантованная CRNN (32×128, grayscale); CTC-decode: argmax по шагам, удаление повторов, confidence = exp(mean(max logits)) |
| **TrackAggregator** | Скользящий буфер (text, confidence) на трек; взвешенное голосование с порогом quorum; TTL-вытеснение; **бюджет OCR-попыток** (`max_ocr_attempts`); финализация трека при консенсусе или исчерпании бюджета; fallback на лучшего кандидата; одноразовое событие «Нечитаемо» |
| **TrackDirectionEstimator** | История center_y и площади bbox на трек; APPROACHING = center_y ↓ + area ↑; RECEDING = center_y ↑ + area ↓; confidence = tanh(score) × density |
| **PlatePostProcessor** | Нормализация (uppercase, Ё→Е, strip) → коррекции по стране → валидация против regex-форматов YAML-конфигов |

### Трек-уровневый алгоритм OCR

Начиная с v0.8, каждый трек имеет **ограниченный бюджет OCR-попыток** (`max_ocr_attempts`, по умолчанию 15). Это радикально снижает нагрузку CPU для долгоживущих треков и предотвращает спам событий.

#### Состояние трека (`_TrackOCRState`)

| Поле | Описание |
|---|---|
| `ocr_attempts` | Число выполненных OCR-попыток (включая low-confidence) |
| `finalized` | Трек финализирован — дальнейший OCR запрещён |
| `result_emitted` | Был ли эмитирован валидный результат |
| `unreadable_emitted` | Было ли эмитировано событие «Нечитаемо» |

#### Когда OCR продолжается

`should_process(track_id)` возвращает `True`, пока:
- трек не финализирован (`finalized == False`);
- число попыток < `max_ocr_attempts`.

Если `should_process` возвращает `False`, для этого трека **полностью пропускаются**: кроп ROI, предобработка, CRNN-инференс. Это основной путь экономии CPU.

#### Когда трек финализируется

1. **Ранний консенсус** — кворум (≥ `(best_shots + 1) // 2` одинаковых текстов) + weighted majority (≥ 50% суммарного веса). Трек финализируется немедленно.
2. **Досрочный выход по пустым OCR** — если `max_consecutive_empty_ocr` подряд попыток не вернули текст (confidence ниже порога), трек финализируется досрочно. Значение `0` отключает эту логику. По умолчанию `5`. Снижает нагрузку CPU на нечитаемых номерах, которые бы иначе расходовали весь бюджет попыток впустую.
3. **Исчерпание бюджета** — `ocr_attempts >= max_ocr_attempts`. Если есть кандидаты — выбирается лучший по весу. Если кандидатов нет — трек помечается как unreadable.
4. **Постпроцессор отклонил номер** — `reset()` очищает кандидатов, но **сохраняет счётчик попыток**. Если бюджет ещё не исчерпан — трек продолжает обработку. Если исчерпан — финализация.

#### Как выбирается финальный номер

- **При консенсусе**: номер с наибольшим `(суммарный_вес, количество)` среди кандидатов в скользящем буфере.
- **При исчерпании бюджета**: `_best_candidate()` — тот же алгоритм, но без требования кворума.
- **Если кандидатов нет**: `should_emit_unreadable()` возвращает `True` ровно один раз → pipeline генерирует одно событие «Нечитаемо».

#### Предотвращение дублирования

- `last_emitted[track_id]` хранит последний эмитированный текст — повторная эмиссия того же номера невозможна.
- `result_emitted` — флаг, что валидный результат уже был.
- `unreadable_emitted` — флаг, что событие «Нечитаемо» уже было. `should_emit_unreadable` возвращает `True` только один раз.
- После финализации `should_process` возвращает `False` — никакой дальнейшей обработки.

#### Три практических сценария

**1. Стабильный распознанный трек**

Номер `А123ВС77` хорошо виден, OCR уверенно распознаёт его.

| Попытка | OCR текст | Confidence | Действие |
|---|---|---|---|
| 1 | А123ВС77 | 0.92 | Кандидат добавлен, кворум не достигнут |
| 2 | А123ВС77 | 0.89 | Кандидат добавлен, кворум не достигнут |
| 3 | А123ВС77 | 0.91 | **Консенсус**: кворум 3/3, majority 100% → emit `А123ВС77`, финализация |
| 4+ | — | — | `should_process → False`, OCR не запускается |

**Результат**: 1 событие с номером. CPU-работа прекращается после 3 попыток.

**2. Шумный / конфликтный трек**

Номер частично закрыт, OCR выдаёт разные варианты.

| Попытка | OCR текст | Confidence | Действие |
|---|---|---|---|
| 1 | А123ВС77 | 0.82 | Кандидат добавлен |
| 2 | А1Z3ВС77 | 0.65 | Кандидат добавлен |
| 3 | А123ВС77 | 0.78 | Кворум для А123ВС77: 2/3, но majority проверяется... |
| … | (разные) | | Консенсус не достигается |
| 15 | — | 0.45 | **Бюджет исчерпан**. `_best_candidate` → `А123ВС77` (наибольший суммарный вес) → emit, финализация |

**Результат**: 1 событие с лучшим кандидатом. 15 OCR-попыток, далее CPU не тратится.

**3. Полностью нечитаемый трек**

Номер слишком далеко или засвечен, OCR confidence всегда ниже порога.

| Попытка | OCR текст | Confidence | Действие |
|---|---|---|---|
| 1 | (мусор) | 0.35 | Ниже `ocr_min_confidence` → пустой текст, счётчик +1 |
| 2 | (мусор) | 0.28 | Счётчик +1 |
| … | | | |
| 15 | (мусор) | 0.31 | **Бюджет исчерпан**, кандидатов нет → финализация |
| 16+ | — | — | `should_process → False`, `should_emit_unreadable → True` (один раз) → emit «Нечитаемо» |

**Результат**: 1 событие «Нечитаемо». Без бюджета эта же ситуация генерировала бы событие на каждом кадре.

### Конфигурация OCR и детектора

| Параметр | Тип | По умолчанию | Диапазон | Описание |
|---|---|---|---|---|
| `max_ocr_attempts` | int | 15 | 1–200 | Макс. число OCR-попыток на трек |
| `max_consecutive_empty_ocr` | int | 5 | 0–200 | Пустых OCR подряд до досрочного завершения трека. `0` — отключить |
| `detector_frame_stride` | int | 2 | 1–30 | Базовый шаг инференса (каждый N-й кадр) |
| `adaptive_stride_enabled` | bool | true | — | Адаптивный шаг: когда активных треков нет, stride увеличивается ×3 для экономии CPU. При появлении треков возвращается к базовому значению |
| `preview_fps_limit` | int | 5 | 1–30 | Лимит FPS предпросмотра (per-channel). Ограничивает частоту кодирования JPEG для preview, не влияет на реальный FPS камеры |

**Взаимодействие параметров:**

- **`best_shots`** (по умолчанию 3): определяет размер скользящего буфера и кворум. Если `max_ocr_attempts < best_shots`, консенсус невозможен — используется fallback на лучшего кандидата.
- **`ocr_min_confidence`** (по умолчанию 0.6): результаты ниже порога не попадают в пул кандидатов, но **расходуют бюджет**. Низкоконфиденциальные результаты увеличивают счётчик `consecutive_failures`.
- **`max_consecutive_empty_ocr`**: работает совместно с `max_ocr_attempts`. Если номер не читается, трек финализируется после N пустых попыток подряд, не дожидаясь полного бюджета.
- **`adaptive_stride_enabled`**: работает совместно с `detector_frame_stride`. Когда включён и нет активных треков, `effective_stride = detector_frame_stride × 3`.
- **`cooldown_seconds`** (по умолчанию 5): работает после финализации — если тот же номер уже был недавно, событие подавляется.
- **`preview_fps_limit`**: управляет только preview-кодированием. Кодирование происходит только при наличии MJPEG/snapshot потребителей (lazy encode).

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

## REST и streaming endpoints

### Web UI

| Метод | Путь | Описание |
|---|---|---|
| `GET` | `/` | Операторская панель (index.html) |

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

### Events

| Метод | Путь | Описание |
|---|---|---|
| `GET` | `/api/events` | Журнал событий; параметры: `limit`, `before_ts`, `before_id`, `channel_id`, `plate`; сортировка `timestamp DESC, id DESC` |
| `GET` | `/api/events/item/{event_id}` | Детали события |
| `GET` | `/api/events/item/{event_id}/media/{kind}` | Медиафайл события (`kind=frame` или `plate`) |
| `GET` | `/api/events/stream` | SSE-поток live событий (`text/event-stream`; keepalive `: ping`; auto-retry) |

### Controllers

| Метод | Путь | Описание |
|---|---|---|
| `GET` | `/api/controllers` | Список контроллеров |
| `POST` | `/api/controllers` | Создать контроллер |
| `PUT` | `/api/controllers/{controller_id}` | Обновить контроллер |
| `DELETE` | `/api/controllers/{controller_id}` | Удалить контроллер (блокируется, если используется каналом) |
| `POST` | `/api/controllers/{controller_id}/test` | Отправить тестовую команду реле |

### Plate Lists

| Метод | Путь | Описание |
|---|---|---|
| `GET` | `/api/lists` | Список всех plate lists |
| `POST` | `/api/lists` | Создать список |
| `PUT` | `/api/lists/{list_id}` | Обновить метаданные списка |
| `DELETE` | `/api/lists/{list_id}` | Удалить список |
| `GET` | `/api/lists/{list_id}/entries` | Записи в списке |
| `POST` | `/api/lists/{list_id}/entries` | Добавить запись |
| `PUT` | `/api/lists/{list_id}/entries/{entry_id}` | Обновить запись |
| `DELETE` | `/api/lists/{list_id}/entries/{entry_id}` | Удалить запись |
| `GET` | `/api/lists/entry-by-plate` | Найти запись по номеру |
| `GET` | `/api/lists/plates` | Все номера с типами списков |

### Settings

| Метод | Путь | Описание |
|---|---|---|
| `GET` | `/api/settings` | Все глобальные настройки |
| `PUT` | `/api/settings` | Обновить настройки (изменение параметров распознавания номеров и DSN перезапускает pipeline) |

### Data & Export

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

### Debug

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
