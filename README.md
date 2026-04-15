# ANPR System

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
|---|---|
| [Деплой и конфигурация](docs/setup.md) | Docker-запуск, переменные окружения, runtime-настройки, аппаратные контроллеры, хранилище |
| [Аутентификация и пользователи](docs/auth.md) | Роли, разрешения, JWT, управление пользователями |
| [API endpoints](docs/endpoints.md) | Web UI, REST, SSE, debug, worker и export endpoints |
| [ANPR pipeline](docs/anpr-pipeline.md) | Алгоритмы детекции, OCR, агрегация по треку, ключевые параметры |
| [Диаграммы](docs/diagrams.md) | Архитектурные схемы, pipeline, event flow, retention |
| [Описание модулей](docs/modules.md) | Назначение директорий и ключевых файлов |
| [Технологический стек](docs/technology-stack.md) | Языки, runtime, инфраструктура, ключевые зависимости |
| [Структура проекта](docs/project-structure.md) | Дерево репозитория и навигация |

---

## Возможности

- многоканальная обработка видео: отдельный поток исполнения на каждый канал;
- server-side ANPR pipeline: детекция (YOLOv8), OCR (CRNN), агрегация по треку, постобработка, cooldown;
- web UI оператора: наблюдение, журнал событий, управление клиентами, списки номеров, настройки;
- live preview по MJPEG из того же потока канала;
- live-события через SSE без опроса (long-lived stream с keepalive);
- управление каналами через API: создать, изменить, запустить, остановить, перезапустить;
- настройка ROI, размера номерного знака, OCR-порогов, cooldown и motion gate — отдельно на каждый канал;
- управление клиентами (ФИО, номер, телефон, автомобиль, комментарий) независимо от списков;
- white / black / custom plate lists с фильтрацией событий для автосработки реле; клиенты могут существовать без привязки к списку;
- управление аппаратными контроллерами через API (тип DTWONDER2CH);
- retention / cleanup / CSV / ZIP export через отдельный worker-сервис;
- полный бэкап PostgreSQL и `settings.yaml` с восстановлением через UI;
- PostgreSQL — единственный поддерживаемый backend хранения данных.

---

## Архитектура

Система разделена на три контура:

1. **API service** (`app/api/`) — FastAPI-приложение: web UI, REST API, управление каналами, SSE-поток событий, preview endpoints.
2. **Channel runtime / ANPR core** (`runtime/`, `anpr/`) — для каждого канала создаётся отдельный поток, который открывает источник видео, хранит MJPEG preview в памяти и прогоняет кадры через полный ANPR pipeline.
3. **Retention worker** (`app/worker/`) — отдельный FastAPI-сервис для очистки старых событий, удаления медиа, контроля размера хранилища и экспорта.

Архитектурные схемы вынесены в [`docs/diagrams.md`](docs/diagrams.md), описание компонентов — в [`docs/modules.md`](docs/modules.md).

---

## Быстрый старт

Поддерживаемая модель runtime: Docker Compose.

**Требования:** Docker Engine 24+, Docker Compose v2+, файлы ML-моделей в `anpr/models/yolo/` и `anpr/models/ocr_crnn/`.

```bash
cp .env.example .env
# Отредактировать .env — как минимум задать JWT_SECRET_KEY
docker compose up -d --build
```

Проверить, что система запустилась:

```bash
curl http://localhost:8080/api/health
curl http://localhost:8080/worker/health
```

Web UI доступен по адресу `http://localhost:8080`. Логин по умолчанию: `superadmin` / `1234`.

Подробнее о конфигурации, переменных окружения и процедурах обновления — в [`docs/setup.md`](docs/setup.md).

---

## Лицензия

MIT
