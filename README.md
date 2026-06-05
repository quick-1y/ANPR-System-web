# ANPR System

<p align="center">
  <img src="https://img.shields.io/badge/Python 3.13-3776ab?style=flat-square&logo=python&logoColor=white"/>
  <img src="https://img.shields.io/badge/FastAPI-009688?style=flat-square&logo=fastapi&logoColor=white"/>
  <img src="https://img.shields.io/badge/PostgreSQL-4169e1?style=flat-square&logo=postgresql&logoColor=white"/>
  <img src="https://img.shields.io/badge/YOLOv8-red?style=flat-square"/>
  <img src="https://img.shields.io/badge/CRNN-orange?style=flat-square"/>
  <img src="https://img.shields.io/badge/Docker-2496ed?style=flat-square&logo=docker&logoColor=white"/>
</p>

<p align="center">
  Веб приложение системы автоматического распознавания автомобильных номеров.
</p>

---

## О системе

ANPR System — это серверная система распознавания номерных знаков с web-интерфейсом оператора. Обработка выполняется локально: видеопоток захватывается и анализируется в реальном времени, результаты сохраняются в PostgreSQL и мгновенно отображаются в браузере.

Проект ориентирован на многоканальную работу, быстрое реагирование оператора, настройку каналов и управление доступом пользователей без зависимости от внешних облачных сервисов.

**Ключевые возможности:**

- Многоканальная обработка видеопотоков
- Web UI для операторов и администраторов с системными шрифтами и увеличенной базовой читаемостью
- Live preview через MJPEG
- Live events через SSE
- Настраиваемые ROI, OCR-пороги, motion gate и cooldown
- Клиенты и списки номеров
- Интеграция с аппаратными контроллерами
- Режим парковочных зон: учёт въезда и выезда транспортных средств по зонам с контролем вместимости
- Экспорт событий, backup и restore через UI
- JWT-аутентификация и ролевая модель доступа

---

## Документация

Документация разделена по аудиториям.

### Technical documentation (для разработчиков)

| | Раздел | Описание |
|---|---|---|
| | [Архитектура](docs/technical/architecture.md) | Текстовое описание архитектуры системы, сервисов и потоков данных |
| 🔌 | [API endpoints](docs/technical/endpoints.md) | Полный список REST, SSE, MJPEG и worker endpoints |
| 🔐 | [Аутентификация и пользователи](docs/technical/auth.md) | Роли, разрешения, JWT, управление операторами |
| 🧠 | [ANPR pipeline](docs/technical/anpr-pipeline.md) | Алгоритмы OCR, агрегация по треку, ключевые параметры |
| 📊 | [Диаграммы](docs/technical/diagrams.md) | Схемы сервисов, pipeline, event flow, retention |
| 📦 | [Описание модулей](docs/technical/modules.md) | Назначение каждого файла и директории |
| 🧾 | [Соглашения по коду](docs/technical/coding-conventions.md) | Именование публичных/приватных функций и общие правила |
| 🛠 | [Технологический стек](docs/technical/technology-stack.md) | Языки, фреймворки, ключевые зависимости |
| 📁 | [Структура проекта](docs/technical/project-structure.md) | Дерево репозитория |

### Guides & operations (для пользователей, операторов, администраторов)

| | Раздел | Описание |
|---|---|---|
| ⚙️ | [Деплой и конфигурация](docs/guides/setup.md) | Переменные окружения, volumes, контроллеры, хранилище |
| 🅿️ | [Парковочные зоны](docs/guides/zones.md) | Режим зон: въезд/выезд, вместимость, интеграция с каналами |

### Что можно доработать

| | Раздел | Описание |
|---|---|---|
| ⚙️ | [Roadmap inference](docs/roadmap/inference.md) | Дизайн inference workers, очередей и shared memory |

---

## Лицензия

[MIT](LICENSE)
