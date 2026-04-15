# ANPR System

<p align="center">
  <b>🚀 Core</b><br/>
  <img src="https://img.shields.io/badge/Python-3.13-3776ab?style=for-the-badge&logo=python&logoColor=white"/>
  <img src="https://img.shields.io/badge/API-FastAPI-009688?style=for-the-badge&logo=fastapi&logoColor=white"/>
  <img src="https://img.shields.io/badge/Data-PostgreSQL-4169e1?style=for-the-badge&logo=postgresql&logoColor=white"/>
  <br/><br/>
  <b>🧠 ML & Vision</b><br/>
  <img src="https://img.shields.io/badge/Detection-YOLOv8-red?style=for-the-badge"/>
  <img src="https://img.shields.io/badge/OCR-CRNN-orange?style=for-the-badge"/>
  <img src="https://img.shields.io/badge/PyTorch-2.8-ee4c2c?style=for-the-badge&logo=pytorch&logoColor=white"/>
  <br/><br/>
  <b>🐳 Deployment</b><br/>
  <img src="https://img.shields.io/badge/Docker-2496ed?style=for-the-badge&logo=docker&logoColor=white"/>
  <img src="https://img.shields.io/badge/Nginx-009639?style=for-the-badge&logo=nginx&logoColor=white"/>
</p>

<p align="center">
  Веб приложение системы автоматического распознавания автомобильных номеров.
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
