---
gsd_state_version: '1.0'
status: planning
progress:
  total_phases: 8
  completed_phases: 0
  total_plans: 0
  completed_plans: 0
  percent: 0
---

# Project State

## Project Reference

See: .planning/PROJECT.md (updated 2026-09-24)

**Core value:** Администратор может гибко выдать любому пользователю ровно те доступы, которые нужны, через роли с галочками, и сервер реально соблюдает эти права, а не только скрывает вкладки.
**Current focus:** Phase 1 — Фундамент модели прав

## Current Position

Phase: 1 of 8 (Фундамент модели прав)
Plan: 0 of TBD in current phase
Status: Ready to plan
Last activity: 2026-09-24 — Roadmap created (8 phases, 41/41 v1 requirements mapped)

Progress: [░░░░░░░░░░] 0%

## Performance Metrics

**Velocity:**
- Total plans completed: 0
- Average duration: -
- Total execution time: 0.0 hours

**By Phase:**

| Phase | Plans | Total | Avg/Plan |
|-------|-------|-------|----------|
| - | - | - | - |

**Recent Trend:**
- Last 5 plans: -
- Trend: -

*Updated after each plan completion*

## Accumulated Context

### Decisions

Decisions are logged in PROJECT.md Key Decisions table.
Recent decisions affecting current work:

- [Roadmap]: Ручное срабатывание реле — отдельная галочка «Ручное управление реле»; CRUD контроллеров — права «Настроек» (решение владельца, закрывает исследование по контроллерам)
- [Roadmap]: Управление пользователями и ролями — часть «Настроек»; «Настройки» имеют полную тройку Просмотр/Изменение/Удаление
- [Roadmap]: Оператор по умолчанию — Просмотр «Наблюдение» и «Зоны» + «Ручное управление реле»; Администратор — всё
- [Roadmap]: Защита последнего администратора/самоблокировки, фильтры и CSV журнала — v2; путь восстановления — superadmin
- [Roadmap]: Права читаются из БД на каждый запрос; кэширование прав в JWT или в памяти без инвалидации недопустимо (иначе ломается USER-07)

### Pending Todos

None yet.

### Blockers/Concerns

- [Phase 1]: Удаление `users.role`/`users.permissions` ломает текущий экран пользователей — в фазе 1 форма минимально переходит на выбор роли; полный экран пользователей — фаза 3
- [Phase 1]: `tests/test_permission_guards.py` фиксирует инвариант «18 мест `tab:settings`» — заменяется в фазе 1, а `AGENTS.md` (раздел авторизации) устаревает с этого момента
- [Phase 4]: Таблицу «эндпоинт → раздел.действие» утверждает владелец до реализации (retention/run, restore БД, старт/стоп канала, экспорт, телеметрия, раздел SSE-потока)
- [Phase 5]: Оператору без «Настройки: Просмотр» нужен источник привязок реле/хоткеев — сейчас он строится из закрытого списка контроллеров
- [Phase 7]: Запись журнала проектировать неблокирующей с самого начала (AUDIT-05 проверяется в фазе 8)

## Deferred Items

Items acknowledged and deferred at milestone close, most recent first:

| Category | Item | Status | Deferred At | Milestone |
|----------|------|--------|-------------|-----------|
| *(none)* | | | | |

## Session Continuity

Last session: 2026-09-24
Stopped at: Roadmap and STATE created; awaiting owner approval of roadmap
Resume file: None
