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
- Web UI для операторов и администраторов
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

| | Раздел | Описание |
|---|---|---|
| ⚙️ | [Деплой и конфигурация](docs/setup.md) | Переменные окружения, volumes, контроллеры, хранилище |
| 🔐 | [Аутентификация и пользователи](docs/auth.md) | Роли, разрешения, JWT, управление операторами |
| 🔌 | [API endpoints](docs/endpoints.md) | Полный список REST, SSE, MJPEG и worker endpoints |
| 🅿️ | [Парковочные зоны](docs/zones.md) | Режим зон: въезд/выезд, вместимость, интеграция с каналами |
| 🧠 | [ANPR pipeline](docs/anpr-pipeline.md) | Алгоритмы OCR, агрегация по треку, ключевые параметры |
| 📊 | [Диаграммы](docs/diagrams.md) | Схемы сервисов, pipeline, event flow, retention |
| 📦 | [Описание модулей](docs/modules.md) | Назначение каждого файла и директории |
| | [Архитектура](docs/architecture.md) | Текстовое описание архитектуры системы, сервисов и потоков данных |
| 🛠 | [Технологический стек](docs/technology-stack.md) | Языки, фреймворки, ключевые зависимости |
| 📁 | [Структура проекта](docs/project-structure.md) | Дерево репозитория |


---

## Лицензия

[MIT](LICENSE)
