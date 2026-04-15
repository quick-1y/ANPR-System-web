# ANPR System

<p align="center">
  <img src="https://img.shields.io/badge/Python-3.13-3776ab?style=for-the-badge&logo=python&logoColor=white"/>
  <img src="https://img.shields.io/badge/FastAPI-009688?style=for-the-badge&logo=fastapi&logoColor=white"/>
  <img src="https://img.shields.io/badge/PostgreSQL-4169e1?style=for-the-badge&logo=postgresql&logoColor=white"/>
  <img src="https://img.shields.io/badge/Docker-2496ed?style=for-the-badge&logo=docker&logoColor=white"/>
  <img src="https://img.shields.io/badge/YOLOv8-red?style=for-the-badge"/>
  <img src="https://img.shields.io/badge/CRNN-orange?style=for-the-badge"/>
</p>

<p align="center">
  Многоканальная система автоматического распознавания автомобильных номеров с web-интерфейсом оператора.
</p>

---

## О системе

Система выполняет распознавание номерных знаков прямо на сервере — без внешних сервисов и облаков. Видеопоток захватывается и обрабатывается в реальном времени: детекция через YOLOv8, распознавание через CRNN с трек-уровневой агрегацией OCR, результаты мгновенно появляются в браузере через SSE. Live-preview отдаётся напрямую по MJPEG из того же потока, без отдельного медиасервера.

**Ключевые возможности:**

- Несколько каналов одновременно — каждый в отдельном потоке
- Настраиваемые ROI, motion gate, OCR-пороги, cooldown, размер номера — на каждый канал
- White / black / custom plate lists с автоматической сработкой реле на контроллер
- Журнал событий, клиентская база, экспорт CSV / ZIP
- Полный бэкап и восстановление БД и настроек через UI
- JWT-аутентификация, ролевая модель, управление операторами

---

## Требования

| Зависимость | Версия |
|---|---|
| Docker Engine | 24+ |
| Docker Compose | v2+ |
| ML-модели | файлы YOLO и CRNN  |

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

Полный список переменных — в [документации по деплою](docs/setup.md#переменные-окружения).


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

### 6. Открыть Web UI

Перейти в браузере на **http://localhost:8080**

Логин по умолчанию: `superadmin` / `1234`

---

## Обновление и сброс

```bash
# Пересборка с новым кодом
docker compose build --no-cache && docker compose up -d

# Остановка
docker compose down

# Полный сброс (удаляет все данные и volumes)
docker compose down -v
```

---

## Документация

| | Раздел | Описание |
|---|---|---|
| ⚙️ | [Деплой и конфигурация](docs/setup.md) | Переменные окружения, volumes, контроллеры, хранилище |
| 🔐 | [Аутентификация и пользователи](docs/auth.md) | Роли, разрешения, JWT, управление операторами |
| 🔌 | [API endpoints](docs/endpoints.md) | Полный список REST, SSE, MJPEG и worker endpoints |
| 🧠 | [ANPR pipeline](docs/anpr-pipeline.md) | Алгоритмы OCR, агрегация по треку, ключевые параметры |
| 📊 | [Диаграммы](docs/diagrams.md) | Схемы сервисов, pipeline, event flow, retention |
| 📦 | [Описание модулей](docs/modules.md) | Назначение каждого файла и директории |
| | [Архитектура](docs/architecture.md) | Текстовое описание архитектуры системы, сервисов и потоков данных |
| 🛠 | [Технологический стек](docs/technology-stack.md) | Языки, фреймворки, ключевые зависимости |
| 📁 | [Структура проекта](docs/project-structure.md) | Дерево репозитория |


---

## Лицензия

[MIT](LICENSE)
