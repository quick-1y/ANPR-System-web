# database/

Каталог `database/` содержит SQL-артефакты PostgreSQL и Python-адаптеры доступа к БД для backend-приложения.

## Содержимое

- `postgres/schema.sql` — SQL-схема и индексы для таблиц ANPR (events, users).
- `postgres/` — SQL/schema assets для PostgreSQL.
- `*.py` в `database/` — repository/adaptor layer приложения для работы с PostgreSQL
  (например, репозитории событий, списков и пользователей, общие ошибки слоя хранения).
- `user_repository.py` — репозиторий пользователей (auth). При первом запуске
  автоматически создаёт таблицу `users` и пользователя `admin` (пароль: `1234`).

## Важно

- Схема подключается автоматически через `docker-compose.yml` в контейнере `postgres`.
- Python-код в `database/` ограничен слоем репозиториев/адаптеров PostgreSQL;
  бизнес-логика ANPR остаётся в `anpr/`, orchestration/API — в `packages/` и `app/`.
