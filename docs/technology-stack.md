# Технологический стек

Этот файл содержит вынесенное описание стека проекта. Он полезен как краткая сводка по языкам, runtime, инфраструктуре и ключевым зависимостям.

## Основной стек

| Слой | Технологии |
|---|---|
| Backend | FastAPI, Uvicorn, Python 3.13 |
| Detection | YOLOv8 (Ultralytics 8.3.20) |
| OCR | CRNN (INT8 quantized) |
| Video I/O | OpenCV |
| ML runtime | PyTorch 2.8.0, torchvision 0.23.0 (CPU wheel) |
| Live updates | SSE (`text/event-stream`) |
| Preview | MJPEG (`multipart/x-mixed-replace`) |
| Storage | PostgreSQL 16 (`psycopg`, `psycopg_pool`) |
| Config | YAML (PyYAML) |
| Reverse proxy | Nginx |
| Containerization | Docker, Docker Compose |
| Monitoring | psutil (CPU / RAM) |

## Языки и форматы

| Тип | Использование |
|---|---|
| Python 3.13 | Backend, API, runtime каналов, ML inference |
| HTML / CSS / JavaScript | Статический web frontend |
| YAML | Основная runtime-конфигурация (`config/settings.yaml`) |
| SQL | Схема PostgreSQL и запросы репозиториев |
| Mermaid | Архитектурные и процессные диаграммы в документации |

## Runtime и деплой

| Компонент | Назначение |
|---|---|
| `python:3.13-slim` | Базовый образ приложения |
| `postgres:16` | Хранение событий и списков номеров |
| `nginx:1.27-alpine` | Reverse proxy и публичная точка входа |
| Docker Compose | Оркестрация всех сервисов проекта |

## Сервисы в compose

| Сервис | Роль |
|---|---|
| `nginx` | Reverse proxy |
| `api` | FastAPI + web UI + channel runtime |
| `retention_worker` | Cleanup, retention, export |
| `postgres` | База данных |

## Ключевые Python-зависимости

| Пакет | Назначение |
|---|---|
| `fastapi` | HTTP API и web-приложение |
| `uvicorn` | ASGI server |
| `ultralytics` | YOLOv8 для локализации номеров |
| `opencv-python` | Захват видео, обработка изображений, JPEG encoding |
| `torch` | ML runtime для OCR |
| `torchvision` | Image transforms для OCR pipeline |
| `PyYAML` | Парсинг и сохранение настроек |
| `psycopg[binary]` | PostgreSQL driver |
| `psycopg_pool` | Pool подключений к PostgreSQL |
| `psutil` | Метрики CPU и RAM |
| `bcrypt` | Хэширование паролей пользователей |
| `PyJWT` | Генерация и валидация JWT-токенов (подготовлен для Phase 2 auth) |

## Коммуникации и форматы API

| Механизм | Где используется |
|---|---|
| REST | Управление каналами, настройками, событиями, контроллерами, списками |
| SSE | Live-события и live-логи |
| MJPEG | Live preview каналов |
| Multipart upload | Восстановление БД и `settings.yaml` |
| CSV / ZIP | Экспорт событий и бэкапов |

## Где смотреть детали

- Архитектурные схемы: [`diagrams.md`](diagrams.md)
- Назначение модулей: [`modules.md`](modules.md)
- Дерево проекта: [`project-structure.md`](project-structure.md)
