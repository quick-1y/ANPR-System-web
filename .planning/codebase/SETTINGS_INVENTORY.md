# Inventory of settings by ownership (Step 1)

Цель: зафиксировать единый реестр параметров и убрать размытость между глобальными settings и канальными настройками.

## Классификация

- `global_runtime` — глобальные runtime-настройки приложения (хранятся в `config/settings.yaml`).
- `channel_runtime` — per-channel runtime-настройки (хранятся в PostgreSQL `channels`).
- `infra_only` — инфраструктурные параметры окружения/секреты (хранятся в `.env`, не в settings).
- `ui_only` — настройки представления UI (хранятся в `config/settings.yaml`).

## Реестр параметров

| Domain | Key/Section | Class | Source of truth | Notes |
|---|---|---|---|---|
| UI | `grid` | `ui_only` | `config/settings.yaml` | Только layout отображения карточек. |
| UI | `theme` | `ui_only` | `config/settings.yaml` | Тема интерфейса. |
| UI | `sidebar_locked` | `ui_only` | `config/settings.yaml` | Состояние панели. |
| Runtime | `reconnect.*` | `global_runtime` | `config/settings.yaml` | Политики reconnect для processor. |
| Runtime | `storage.*` *(без DSN)* | `global_runtime` | `config/settings.yaml` | Cleanup и retention. |
| Runtime | `logging.*` | `global_runtime` | `config/settings.yaml` | Уровни и retention логов. |
| Runtime | `time.*` | `global_runtime` | `config/settings.yaml` | Timezone/offset. |
| Runtime | `plates.*` | `global_runtime` | `config/settings.yaml` | Конфиг стран и активные страны. |
| Runtime | `debug.*` | `global_runtime` | `config/settings.yaml` | Runtime debug flags. |
| Runtime | `models.*` | `global_runtime` | `config/settings.yaml` | Пути к моделям и device (cpu). |
| Runtime | `ocr.*` | `global_runtime` | `config/settings.yaml` | Глобальные OCR параметры. |
| Runtime | `detector.*` | `global_runtime` | `config/settings.yaml` | Глобальные detector параметры. |
| Runtime | `inference.*` | `global_runtime` | `config/settings.yaml` | Воркеры и shared memory. |
| Channel | ROI/motion/OCR/filter/controller/list/zone | `channel_runtime` | PostgreSQL `channels` | Per-channel поля в `database/channel_repository.py`. |
| Infra | `POSTGRES_DSN` | `infra_only` | ENV (`.env`) | Не хранится в YAML, подмешивается в API-ответ. |
| Infra | `JWT_SECRET_KEY`, DB creds, ports | `infra_only` | ENV (`.env`) | Секреты и инфраструктура. |

## Удалённые/дублирующие настройки

- Удалён глобальный блок `tracking` из settings как дублирующий канальные настройки БД.
- Канальные defaults централизованы в `channel_defaults()` и применяются в `ChannelDatabase._normalize()`.

## Проверка результата Step 1

1. Нет `tracking` в `build_default_settings()` и `config/settings.yaml`.
2. `/api/settings` отдаёт только глобальные секции.
3. Канальные параметры живут в таблице `channels` и API `/api/channels/*`.
