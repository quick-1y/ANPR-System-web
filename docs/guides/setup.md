# Деплой и конфигурация

## Требования

- Docker Engine 24+
- Docker Compose v2+
- Файлы ML-моделей:
  - `anpr/models/yolo/` — модель детекции YOLOv8
  - `anpr/models/ocr_crnn/` — модель распознавания CRNN

---

## Установка и запуск

### 1. Клонировать репозиторий

```bash
git clone https://github.com/quick-1y/ANPR-System-v0.8_web
cd ANPR-System-v0.8_web
```

### 2. Создать и настроить `.env`

```bash
cp .env.example .env
```

Обязательно задать перед запуском в production:

```env
JWT_SECRET_KEY=<случайная строка 32+ символа>
POSTGRES_PASSWORD=<надёжный пароль>
```

### 3. Собрать и запустить

```bash
docker compose up -d --build
```

Поднимаются четыре сервиса: `nginx`, `api`, `retention_worker`, `postgres`.

### 4. Проверить готовность

```bash
curl http://localhost:8080/api/health
curl http://localhost:8080/worker/health
```

Оба должны вернуть `200 OK`.

### 5. Открыть Web UI

Перейти в браузере на **http://localhost:8080**

Интерфейс использует системные шрифты браузера и увеличенную минимальную кегельную сетку, поэтому дополнительные файлы шрифтов устанавливать не нужно. В разделе **Настройки → Общие → Интерфейс** можно выбрать стиль приложения: стандартный `Graphite Minimal` используется по умолчанию, а `Modern Aurora` включает современный glass/dashboard-дизайн. Для каждого стиля доступны тёмная и светлая темы. Для операторов со слабым зрением можно дополнительно увеличить масштаб страницы штатными средствами браузера.

Логин по умолчанию: `superadmin` / `1234`

### 6. Обновление и сброс

```bash
# Пересборка с новым кодом
docker compose build --no-cache && docker compose up -d
```
```bash
# Остановка
docker compose down
```
```bash
# Полный сброс (удаляет все данные и volumes)
docker compose down -v
```

---

## Сервисы

Docker Compose запускает четыре сервиса:

| Сервис | Описание | Внутренний адрес |
|---|---|---|
| `nginx` | Reverse proxy — единственная публичная точка входа | `HTTP_PORT` (по умолчанию `8080`) |
| `api` | FastAPI + Web UI + channel runtime | `api:8080` |
| `retention_worker` | Retention, очистка, экспорт | `retention_worker:8092` |
| `postgres` | PostgreSQL 16 с init-схемой | `postgres:5432` (только внутри сети) |

---

## Volumes

| Volume | Содержимое |
|---|---|
| `pgdata` | Данные PostgreSQL |
| `media_data` | Скриншоты и экспорт (`data/screenshots`, `data/exports`) |
| `logs_data` | Логи приложения (`logs/`) |

---

## Переменные окружения

Все переменные задаются в `.env` (скопировать из `.env.example`):

| Переменная | По умолчанию | Описание |
|---|---|---|
| `HTTP_PORT` | `8080` | Порт nginx на хосте |
| `POSTGRES_DB` | `anpr` | Имя базы данных PostgreSQL |
| `POSTGRES_USER` | `anpr` | Пользователь PostgreSQL |
| `POSTGRES_PASSWORD` | `anpr` | Пароль PostgreSQL |
| `POSTGRES_DSN` | `postgresql://anpr:anpr@postgres:5432/anpr` | Полный DSN для подключения приложения |
| `JWT_SECRET_KEY` | `anpr-default-secret-change-me` | Секрет подписи JWT — **обязательно заменить перед деплоем** |
| `JWT_EXPIRATION_MINUTES` | `480` | Срок жизни токена в минутах |
| `LOG_LEVEL` | `INFO` | Уровень логирования: `DEBUG`, `INFO`, `WARNING`, `ERROR`, `CRITICAL` |
| `DEBUG` | `false` | Режим отладки |
| `SETTINGS_PATH` | `/app/config/settings.yaml` | Путь к файлу настроек внутри контейнера |
| `OMP_NUM_THREADS` | `2` | Лимит потоков PyTorch/OpenMP — предотвращает перегрузку CPU |
| `MKL_NUM_THREADS` | `2` | Лимит потоков MKL |
| `OPENBLAS_NUM_THREADS` | `2` | Лимит потоков OpenBLAS |

---

## Runtime-конфигурация (`config/settings.yaml`)

Глобальные runtime-параметры — пути к моделям, логика переподключения, политика retention, логирование, часовой пояс, debug-флаги, список поддерживаемых стран и UI-настройки (`ui.style`, `ui.theme`, `ui.grid`, `ui.sidebar_locked`) — хранятся в `config/settings.yaml` и управляются через UI настроек или напрямую в файле.

Контракты OCR и YOLO detector не являются runtime-настройками и зафиксированы в `anpr/model_config.py`: для OCR это размер входа `32×128` и алфавит `0123456789ABCEHKMOPTXY`, для detector — `confidence_threshold=0.5`, `bbox_padding_ratio=0.08`, `min_padding_pixels=2`. Менять их безопасно только вместе с проверенными/переобученными моделями.

Каналы, ROI, OCR-пороги каналов, motion/stride-параметры, preview-лимиты и аппаратные контроллеры хранятся в PostgreSQL, а не в `settings.yaml`.

### Версионирование схемы

- Версионирование и миграция `settings.yaml` не используются: в разработке применяется только актуальный формат файла.
- При изменении структуры настроек обновляйте `config/settings_schema.py`, `config/settings_normalizer.py` и актуальный `config/settings.yaml` напрямую.

---

## Аппаратные контроллеры

Контроллеры настраиваются через API и хранятся в PostgreSQL. Описание реализации — в [`docs/modules.md`](../technical/modules.md).

### Конфигурация контроллера

Каждый контроллер содержит:
- имя, тип (`DTWONDER2CH`), сетевой адрес и пароль;
- два реле, каждое с режимом срабатывания и опциональным хоткеем.

Удаление контроллера, привязанного к каналу, возвращает ошибку.

### Режимы фильтрации для автосработки реле

Привязка контроллера к каналу задаётся через `controller_id`, `controller_relay` (0 или 1), `list_filter_mode` и `list_filter_list_ids`. Перед отправкой команды система проверяет правила фильтрации.

| `list_filter_mode` | Поведение |
|---|---|
| `all` | Реле срабатывает для любого номера, кроме номеров из black list |
| `whitelist` | Реле срабатывает только для номеров из списков типа `white`; black list блокирует |
| `custom` | Реле срабатывает только для номеров из выбранных списков; black list блокирует |

Приоритет black list абсолютный во всех режимах.

### Фильтр направления движения (`controller_direction_filter`)

Применяется дополнительно к фильтру списков — оба условия должны выполниться.

| Значение | Поведение |
|---|---|
| `both` | Направление не учитывается (по умолчанию) |
| `approaching` | Команда отправляется только при движении ТС в сторону камеры |
| `receding` | Команда отправляется только при движении ТС от камеры |

Если направление не удалось определить (`UNKNOWN`), команда при значениях `approaching` или `receding` не отправляется.

### Режимы реле

| Режим | Поведение |
|---|---|
| `pulse` | Мгновенный импульс (таймер фиксирован: 1 с) |
| `pulse_timer` | Импульс с таймером (настраиваемый, ≥ 1 с) |

### Хоткеи реле

Хоткей задаётся на конкретное реле. Нажатие в Web UI отправляет тестовую команду контроллеру. Хоткей блокируется при фокусе в поле ввода или при удержании клавиши. Дубликаты хоткеев в одном контроллере запрещены валидацией API.

---

## Хранение данных

### PostgreSQL

Все события, списки номеров, клиенты, каналы, контроллеры и пользователи хранятся в PostgreSQL через `POSTGRES_DSN`.

**Ключевые таблицы:**

| Таблица | Основные поля |
|---|---|
| `zones` | `id`, `name`, `capacity` |
| `events` | `id`, `time`, `channel_id`, `plate`, `plate_display`, `country`, `confidence`, `source`, `frame_path`, `plate_path`, `direction`, `client_id`, `zone_id`, `time_entry`, `time_exit` |
| `lists` | `id`, `name`, `type`, `is_deleted` |
| `clients` | `id`, `list_id` *(nullable — клиент может существовать без списка)*, `plate`, `plate_normalized`, `last_name`, `first_name`, `middle_name`, `phone`, `car`, `comment`, `is_deleted` |
| `users` | `id`, `login`, `password` (bcrypt), `role`, `permissions` (JSONB), `is_active`, `created_at`, `updated_at` |

**Зоновые поля событий:**  
`zone_id > 0` — ТС находится в зоне; `zone_id = 0` — ТС вне парковки (системный sentinel «Вне парковки»); `zone_id IS NULL` — зона не используется. `time_entry` и `time_exit` фиксируют моменты въезда и выезда. Значение `zone_id` всегда соответствует `zone_after_id` канала, обработавшего событие.

**Зоновые поля каналов:**  
`zone_before_id` — зона, в которой ТС находится до прохождения канала; `zone_after_id` — зона после прохождения; `zone_channel_type` — тип канала (`entry` / `exit` / `null`). Значение `0` в обоих полях означает «Вне парковки».

**Индексы:** `(time DESC, id DESC)` по событиям; `plate_normalized` и `(list_id, plate_normalized) UNIQUE WHERE is_deleted = FALSE` по клиентам; `(zone_id) WHERE zone_id IS NOT NULL AND zone_id > 0 AND time_exit IS NULL` для подсчёта занятости зоны.

### Медиа и экспорт

- Скриншоты и кропы номеров сохраняются в `storage.screenshots_dir`.
- CSV и ZIP-экспорт формируются в памяти и отдаются браузеру напрямую как файл для скачивания.
- Bundle export упаковывает CSV и доступные медиафайлы в ZIP.

Настройка политики retention (автоочистка, лимиты хранилища) — в разделе **Настройки → Данные** в Web UI.
