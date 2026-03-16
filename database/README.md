# database/

Каталог `database/` содержит SQL-артефакты PostgreSQL и Python-адаптеры доступа к БД для backend-приложения.

## Содержимое

- `postgres/schema.sql` — SQL-схема и индексы для таблиц ANPR.
- `postgres/` — SQL/schema assets для PostgreSQL.
- `*.py` в `database/` — repository/adaptor layer приложения для работы с PostgreSQL
  (например, репозитории событий и списков, общие ошибки слоя хранения).

## Важно

- Схема подключается автоматически через `docker-compose.yml` в контейнере `postgres`.
- Python-код в `database/` ограничен слоем репозиториев/адаптеров PostgreSQL;
  бизнес-логика ANPR остаётся в `anpr/`, orchestration/API — в `packages/` и `app/`.
