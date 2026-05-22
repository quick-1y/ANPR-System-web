# Аутентификация и управление пользователями

## Модель доступа (актуальная)

В проекте используется простая модель на текущем этапе:
- доступ к разделам управляется tab-permissions;
- `superadmin` имеет полный доступ;
- debug-функции доступны только `superadmin`.

### Доступные tab-permissions

| Ключ | Название |
|---|---|
| `tab:obs` | Наблюдение |
| `tab:journal` | Журнал |
| `tab:zones` | Зоны |
| `tab:clients` | Клиенты |
| `tab:settings` | Настройки (все, кроме отладки) |

### Ограничения по ролям

- `admin`: можно назначать `tab:obs`, `tab:journal`, `tab:zones`, `tab:clients`, `tab:settings`.
- `operator`: можно назначать `tab:obs`, `tab:journal`, `tab:zones`, `tab:clients`.
- `superadmin`: технический root-аккаунт, bypass проверок permissions и единственный доступ к debug.

## Сводка по API-доступу

- Публично: `/api/health`, `POST /api/auth/login`.
- Авторизованный пользователь: базовые пользовательские API по своим tab-доступам.
- Требует `tab:settings`: глобальные настройки, контроллеры, backup/restore, retention, управление пользователями, список доступных permissions.
- Только `superadmin`: `/api/debug/*`.
