# Итоговое исследование: роли, пользователи и права доступа

**Проект:** Web ANPR System  
**Домен:** RBAC (roles, section-based permissions, user audit) для self-hosted FastAPI/PostgreSQL access-control системы  
**Исследовано:** 2026-09-24  
**Уверенность:** HIGH (архитектура выведена из кода проекта); MEDIUM (таблица ролей — новая сущность); MEDIUM–LOW (контроллеры — открытое решение)

---

## Executive Summary

**Архитектура уже готова к немедленному применению прав.** Ключевое открытие всех исследований: `get_current_user()` в `app/api/deps.py` уже читает пользователя из БД на каждый HTTP-запрос (не кэширует в JWT), проверяя `is_active` мгновенно. Это значит, что блокировка и смена роли применяются сразу — архитектурное требование из `PROJECT.md` (Active) уже решено правильно. Новая модель прав (произвольные роли × 3 действия на 5 разделов) расширяет эту архитектуру, добавляя две таблицы (`roles`, `role_permissions`, `audit_log`), три репозитория и каталог прав.

**Новых зависимостей не требуется.** STACK-исследование подтвердило: FastAPI `Depends()`, psycopg, PyJWT, bcrypt, EventBus — всё уже в проекте. Ни Casbin, ни fastapi-users, ни Redis.

**Одно открытое решение владельца.** FEATURES и ARCHITECTURE выявили: как разграничивать «настройку контроллера» (админ) и «ручное открытие шлагбаума» (оператор). ARCHITECTURE предложил гипотезу A (ручное = Наблюдение.Изменение, настройка = Настройки), но требует подтверждения. PITFALLS выявил 12 критических рисков — все закрываются явными проверками и тестами, архитектурных дефектов нет.

---

## Key Findings

### Recommended Stack

Все нужное уже в проекте: FastAPI `Depends()`, psycopg, PyJWT, bcrypt, EventBus. Новых пакетов не требуется. Новые модули: `config/permissions.py` (каталог), `database/roles_repository.py`, `database/audit_log_repository.py`, `app/api/routers/roles.py`, `common/audit.py`.

### Expected Features

**Must Have:** Произвольные роли с галочками Просмотр/Изменение/Удаление (table stakes); серверная проверка на всех эндпоинтах (закрывает P18/P19); немедленное применение прав (архитектурно решено); блокировка без удаления; журнал действий; дефолтные роли как обычные редактируемые; защита от блокировки последнего администратора.

**Should Have:** Реальное соблюдение прав на API; журнал на русском с контекстом; единая точка истины для каталога.

**Defer (v2+):** Per-object ACL, дробление Настроек, LDAP/SSO, несколько ролей на пользователя.

### Architecture Approach

Brownfield-расширение без переписывания. Текущая система уже читает БД на каждый запрос; новая добавляет таблицы ролей/прав. Ключевые компоненты: каталог прав (единственный источник истины), таблицы (стандартный паттерн проекта), зависимость `require_section()` (замена всем `require_permission()`), журнал действий (асинхронная запись).

### Critical Pitfalls (top-3)

1. **Открытые API под видимостью вкладок (P18/P19).** Структурный тест по `app.routes` гарантирует каждый маршрут с явным уровнем доступа.

2. **Блокировка системы (self-lockout, удаление роли в использовании).** Guard против редактирования собственной роли; проверка на использование; инвариант на администратора.

3. **SSE/MJPEG обходят проверку.** Периодическая ре-проверка в генераторе; отдельный stream-token для избежания утечки в nginx.

---

## Implications for Roadmap

### Suggested Phase Structure

**Phase 1: Foundation** — Schema & Permissions Catalogue (0 research needed)
**Phase 2: Repositories & Dependencies** — `require_section()` в deps.py (0 research)
**Phase 3a (RESEARCH)** — Backend Planning: таблица 79 эндпоинтов, решение по контроллерам (REQUIRED: owner approval)
**Phase 3: Backend** — Guard replacements & audit hooks (1 research phase dependency)
**Phase 4: Roles CRUD & Default Users** (0 research)
**Phase 5: SSE/MJPEG & Stream Protection** (0 research)
**Phase 6: Frontend** (0 research)
**Phase 7: Testing, Docs & Hardening** (0 research)

### Research Flags

**Phases требующие исследования:**
- **Phase 3a (Backend Research):** Явная таблица действий для всех 79 эндпоинтов + решение по контроллерам (Вариант A/B/C/D); требуется подтверждение владельца

**Phases со стандартными паттернами:**
- Phase 1, 2, 4, 5, 6, 7 — прямые расширения существующих паттернов; skip research-phase

---

## Confidence Assessment

| Область | Уверенность | Примечания |
|---------|---|---|
| Stack | HIGH | Прямое чтение кода; нет новых зависимостей |
| Features | MEDIUM–HIGH | Выведены из кода + best practices; новая сущность |
| Architecture | HIGH | Расширение текущей архитектуры; стандартные паттерны |
| Pitfalls | HIGH | 12 ошибок из реального кода и аудитов; каждая имеет способ закрытия |

**Общая уверенность:** HIGH для 6 из 7 фаз; **MEDIUM** для Phase 3a (требует подтверждения владельца)

### Gaps to Address

1. **Контроллеры:** Разделение настройка vs использование (P из `PROJECT.md`) — решение при Phase 3a; варианты A/B/C/D в ARCHITECTURE.md
2. **Иерархия ролей:** Защита от самоэскалации (Ошибка 6) — минимум в Phase 4; полное решение в v2+
3. **Восстановление БД:** `POST /api/data/backup/database/restore` остаётся на `settings.edit` или переходит на `superadmin`? — решение Phase 3a
4. **Retention журнала:** Отдельная настройка `retention.audit_log_days` в `config/registry.py` перед Phase 4
5. **Утечка токена:** nginx `log_format` без query-string для `/api/events/stream` или stream-token отдельно от JWT — решение Phase 5

---

## Sources

**Primary (HIGH):**
- Прямое чтение кода: `app/api/deps.py`, 79 эндпоинтов, `schema.sql`, `auth_utils.py`, тесты, nginx config
- `.planning/codebase/CONCERNS.md`, `PROJECT.md`, `docs/roadmap/configuration-architecture.md`, `AGENTS.md`

**Secondary (MEDIUM):**
- Сравнительный анализ VMS (Genetec, Hikvision, Milestone, Trassir, Axxon)
- RBAC best practices (Zitadel, Azure AD)

**Tertiary (LOW):**
- Speculative aspects (контроллеры — ожидают подтверждения)

---

**Исследование завершено:** 2026-09-24  
**Готово к roadmapping:** ДА (Phase 3a-research для контроллеров)
