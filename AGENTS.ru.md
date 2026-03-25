# AGENTS.ru.md

> Шаблон для AI coding agents. Замените все плейсхолдеры в `<угловых_скобках>` на реальные данные проекта перед использованием. Лишние примеры можно удалить, но секции лучше заполнять, а не вырезать. Этот файл должен быть конкретным, актуальным и пригодным для реальной работы.

---

## Назначение

Этот файл является основным операционным руководством для AI-агентов, работающих в репозитории.

Он должен давать агенту достаточно контекста, чтобы:

- понимать, что делает проект;
- следовать правильной архитектуре и принятым соглашениям;
- класть код в правильные директории;
- запускать нужные команды для setup, проверки и тестирования;
- избегать небезопасных и некачественных изменений;
- понимать, когда нужно остановиться и спросить человека.

Если этот файл расплывчатый, устаревший или противоречивый, качество работы агента будет заметно хуже. Делайте его конкретным.

---

## Краткая Сводка По Проекту

- Название проекта: `<project_name>`
- Тип проекта: `<web app | api | mobile app | cli | library | monorepo | service | internal tool | other>`
- Однострочное описание: `<что делает проект в одном предложении>`
- Основные пользователи: `<кто использует систему>`
- Бизнес- или доменный контекст: `<domain, workflow, problem space>`
- Стадия жизненного цикла: `<prototype | mvp | production | mature | legacy modernization>`
- Владельцы / ответственная команда: `<team_name_or_people>`
- Основная ветка: `<main_branch_name>`
- Важные заметки о состоянии репозитория: `<active refactor | migration in progress | legacy areas | frozen modules | none>`

### Подсказки Для Заполнения

- Пишите описание для инженера, а не для маркетинга.
- Если система legacy или находится в миграции, укажите это явно.
- Если репозиторий содержит несколько продуктов или приложений, отметьте это здесь и поясните структуру ниже.

### Пример

```md
- Название проекта: Acme Orders
- Тип проекта: Monorepo
- Однострочное описание: Internal platform for creating, pricing, and tracking wholesale orders.
- Основные пользователи: Sales operators, finance team, warehouse integrations
- Бизнес- или доменный контекст: B2B commerce
- Стадия жизненного цикла: Production
- Владельцы / ответственная команда: Orders Platform Team
- Основная ветка: main
- Важные заметки о состоянии репозитория: Legacy pricing flow is being migrated into feature-owned modules
```

---

## Принципы Работы Агента

Если пользователь явно не попросил иначе, агент должен:

- предпочитать минимальное безопасное изменение, которое решает задачу;
- сохранять существующую архитектуру и naming conventions;
- обновлять тесты при изменении поведения;
- обновлять docs, config и examples, если они устаревают из-за изменений;
- проверять результат перед завершением работы;
- не делать спекулятивных рефакторингов;
- спрашивать перед разрушительными, необратимыми, дорогими или влияющими на production действиями.

### На Что Агент Должен Оптимизировать Работу

1. Correctness
2. Maintainability
3. Speed

### Чего Агент Не Должен Делать По Умолчанию

- Переписывать архитектуру без запроса.
- Добавлять новую зависимость, если задачу можно решить уже существующими зависимостями проекта.
- Редактировать сгенерированные файлы вручную, если в проекте принят соответствующий workflow.
- Игнорировать падающие проверки, связанные с изменёнными файлами или поведением.
- Совершать действия наугад в security-sensitive, billing-sensitive или compliance-sensitive областях.

---

## Источники Правды

Перед любыми нетривиальными изменениями сверяйтесь со следующими материалами:

| Источник | Путь / URL | Когда использовать |
| --- | --- | --- |
| Продуктовая или доменная документация | `<path_or_url>` | `<правила поведения / бизнес-логика>` |
| Архитектурная документация | `<path_or_url>` | `<границы модулей / устройство системы>` |
| ADR / журнал решений | `<path_or_url>` | `<почему были выбраны определённые tradeoffs>` |
| API-контракты / схемы | `<path_or_url>` | `<изменения endpoint, event или schema>` |
| Design system / UI docs | `<path_or_url>` | `<поведение UI, компоненты, токены>` |
| Contribution guide | `<path_or_url>` | `<workflow репозитория, ветвление, review expectations>` |
| Документация по безопасности | `<path_or_url>` | `<auth, secrets, permissions, compliance>` |
| Deployment / runbooks | `<path_or_url>` | `<env, release, infrastructure changes>` |

Если документация и код противоречат друг другу, приоритет у `<code | docs | ask_human>`, а само расхождение нужно упомянуть в финальном summary.

### Пример

```md
| Источник | Путь / URL | Когда использовать |
| --- | --- | --- |
| Архитектурная документация | `docs/architecture.md` | Изменения границ модулей или shared packages |
| ADR / журнал решений | `docs/adr/` | Новые абстракции, изменения workflow, архитектурные tradeoffs |
| API-контракты / схемы | `openapi/openapi.yaml` | Любые изменения endpoint или generated client |
```

---

## Технологический Стек

Не пишите “latest”. Указывайте точные версии или поддерживаемые диапазоны.

### Основной Стек

- Язык(и): `<language_and_versions>`
- Runtime(s): `<runtime_and_versions>`
- Framework(s): `<frameworks_and_versions>`
- Package manager(s): `<package_managers_and_versions>`
- Build tool(s): `<build_tools_and_versions>`
- База(ы) данных: `<db_and_versions>`
- Messaging / queueing: `<tool_or_none>`
- Кэш / хранилище: `<tool_or_none>`
- Хостинг / инфраструктура: `<cloud | on-prem | hybrid | other>`

### Ключевые Библиотеки И Сервисы

Перечислите важные инструменты, которые агент должен сразу распознавать:

| Область | Библиотека / сервис | Версия | Назначение | Примечания / ограничения |
| --- | --- | --- | --- | --- |
| `<frontend/backend/data/auth/etc>` | `<name>` | `<version>` | `<why it exists>` | `<special rules>` |
| `<frontend/backend/data/auth/etc>` | `<name>` | `<version>` | `<why it exists>` | `<special rules>` |
| `<frontend/backend/data/auth/etc>` | `<name>` | `<version>` | `<why it exists>` | `<special rules>` |

### Политика Версий

- Обязательные версии: `<exact_versions_or_ranges>`
- Источник правды для версий: `<package.json | pyproject.toml | go.mod | Gemfile | Dockerfile | etc>`
- Политика обновления зависимостей: `<manual | renovate | dependabot | scheduled>`
- Требования по совместимости: `<browser matrix | runtime matrix | API compatibility | DB compatibility>`

### Пример

```md
- Язык(и): TypeScript 5.6
- Runtime(s): Node.js 22.x
- Framework(s): Next.js 15, React 19
- Package manager(s): pnpm 10
- Build tool(s): Turborepo 2
- База(ы) данных: PostgreSQL 16
- Messaging / queueing: none
- Кэш / хранилище: Redis 7, S3
- Хостинг / инфраструктура: AWS
```

---

## Архитектура

- Архитектурный стиль: `<feature-sliced | layered | clean architecture | hexagonal | modular monolith | microservices | event-driven | other>`
- Высокоуровневое описание: `<как система разделена и почему>`
- Основные модули / bounded contexts: `<module_a, module_b, module_c>`
- Основной поток данных: `<request/event/render flow>`
- Подход к управлению состоянием: `<if relevant>`
- Границы интеграций: `<external APIs, internal services, SDKs, jobs, queues>`
- Зоны миграции: `<legacy_to_new transitions>`
- Жёсткие ограничения: `<what must not be broken>`

### Архитектурные Правила

- Логику типа `<kind_of_logic>` размещать в `<allowed_path_or_layer>`, а не в `<forbidden_place>`.
- Модуль `<module>` должен оставаться независимым от `<module>`.
- Новая работа в `<area>` должна следовать паттерну `<pattern>`.
- Перед созданием новых абстракций переиспользовать существующие из `<paths>`.
- Нельзя обходить `<validation | domain layer | auth layer | schema boundary>` ради удобства.

### Подсказки Для Заполнения

- Если вы называете архитектурный стиль, поясните, что это значит именно в этом репозитории.
- Описывайте реальные границы и анти-паттерны, а не только учебные термины.
- Обязательно явно отмечайте зоны миграции. Без этого агенты часто ломают переходные состояния.

### Пример

```md
- Архитектурный стиль: Modular monolith with feature-oriented boundaries
- Высокоуровневое описание: Each business capability owns its API layer, application logic, domain rules, and persistence adapters
- Основные модули / bounded contexts: orders, pricing, customers, invoicing
- Основной поток данных: request -> route -> application service -> domain -> repository -> response mapper
- Зоны миграции: pricing logic is being moved out of shared utils into the pricing module
- Жёсткие ограничения: customer state transitions must remain backward compatible with existing warehouse integrations
```

---

## Структура Репозитория

Опишите дерево так, как будто вы онбордите нового инженера в первый день.

```text
<repo-root>/
├─ <dir-or-file>/        # <что здесь лежит>
├─ <dir-or-file>/        # <что здесь лежит>
├─ <dir-or-file>/        # <что здесь лежит>
├─ <dir-or-file>/        # <что здесь лежит>
└─ <dir-or-file>/        # <что здесь лежит>
```

### Ответственность Директорий

| Путь | Ответственность | Типичное содержимое | Чего быть не должно |
| --- | --- | --- | --- |
| `<path>` | `<purpose>` | `<examples>` | `<anti_examples>` |
| `<path>` | `<purpose>` | `<examples>` | `<anti_examples>` |
| `<path>` | `<purpose>` | `<examples>` | `<anti_examples>` |

### Правила Размещения Файлов

- Новые фичи размещать в `<path>`.
- Общий переиспользуемый код размещать в `<path>`.
- Одноразовые скрипты хранить в `<path>`.
- Generated artifacts хранить в `<path>` и они должны `<be_committed_or_not>`.
- Env/config-файлы хранить в `<path>`.
- Миграции, схемы и контракты хранить в `<path>`.

### Пример

```md
apps/web/          # customer-facing frontend
apps/admin/        # internal operations frontend
packages/ui/       # shared UI components and tokens
packages/domain/   # shared domain types and business rules
infra/             # deployment, IaC, environment templates
docs/              # architecture notes, ADRs, onboarding docs
```

---

## Подготовка Окружения

### Обязательные Инструменты

- Обязательные инструменты: `<tool_and_version>`, `<tool_and_version>`, `<tool_and_version>`
- Установка зависимостей: `<exact_command>`
- Запуск локального окружения: `<exact_command>`
- Запуск только зависимых сервисов: `<exact_command>`
- Seed / bootstrap данных: `<exact_command>`
- Откуда загружать env-переменные: `<path>`
- Необходимые локальные сервисы: `<db | docker | queue | emulator | none>`

### Замечания По Setup

- Укажите, если важен порядок команд.
- Укажите, Docker обязателен или опционален.
- Укажите, можно ли безопасно повторно запускать seed.
- Укажите, нужны ли ручные credentials, сертификаты или локальные ключи.

### Пример

```md
- Обязательные инструменты: Node.js 22.x, pnpm 10, Docker Desktop
- Установка зависимостей: pnpm install
- Запуск локального окружения: pnpm dev
- Запуск только зависимых сервисов: docker compose up -d
- Seed / bootstrap данных: pnpm db:seed
- Откуда загружать env-переменные: .env.local
- Необходимые локальные сервисы: Postgres, Redis
```

---

## Команды Для Разработки

Каждая команда ниже должна работать в том виде, в котором она записана.

| Задача | Команда | Scope | Примечания |
| --- | --- | --- | --- |
| Установить зависимости | `<command>` | `<repo_or_package>` | `<notes>` |
| Запустить разработку | `<command>` | `<repo_or_package>` | `<notes>` |
| Запустить один сервис / пакет | `<command>` | `<repo_or_package>` | `<notes>` |
| Сборка | `<command>` | `<repo_or_package>` | `<notes>` |
| Lint | `<command>` | `<repo_or_package>` | `<notes>` |
| Format | `<command>` | `<repo_or_package>` | `<notes>` |
| Typecheck | `<command>` | `<repo_or_package>` | `<notes>` |
| Запустить все тесты | `<command>` | `<repo_or_package>` | `<notes>` |
| Запустить один тестовый файл | `<command>` | `<repo_or_package>` | `<notes>` |
| Запустить один тест-кейс | `<command>` | `<repo_or_package>` | `<notes>` |
| Запустить integration tests | `<command>` | `<repo_or_package>` | `<notes>` |
| Запустить e2e tests | `<command>` | `<repo_or_package>` | `<notes>` |
| Перегенерировать код | `<command>` | `<repo_or_package>` | `<notes>` |

### Стратегия Проверки

Обычно агент должен валидировать изменения в таком порядке:

1. file-level или test-level проверки;
2. проверки ближайшего пакета или модуля;
3. full-repo проверки при необходимости;
4. release-grade проверки перед merge для рискованных или широких изменений.

### Пример

```md
| Задача | Команда | Scope | Примечания |
| --- | --- | --- | --- |
| Lint | `pnpm lint` | repo | Runs all package linters |
| Typecheck | `pnpm typecheck` | repo | Must pass before merge |
| Запустить один тестовый файл | `pnpm vitest run src/features/orders/order-form.test.ts` | package | Fastest local verification |
```

---

## Руководство По Тестированию

- Test framework(s): `<frameworks>`
- Где лежат unit tests: `<paths>`
- Где лежат integration tests: `<paths>`
- Где лежат e2e tests: `<paths>`
- Где лежат contract tests: `<paths_or_none>`
- Паттерны именования: `<*.test.ts | test_*.py | etc>`
- Где лежит CI workflow: `<path>`

### Правила Тестирования

- Любое изменение поведения должно сопровождаться тестами, если нет явно задокументированной причины этого не делать.
- Исправления багов по возможности должны включать regression test.
- Во время итерации предпочитайте точечные тесты.
- При изменении shared code, persistence, contracts, infrastructure или чувствительных workflow нужно запускать более широкие наборы тестов.
- Snapshot или golden-обновления нужно ревьюить, а не принимать вслепую.

### Матрица Тестов

| Тип тестов | Путь / Scope | Команда | Когда запускать |
| --- | --- | --- | --- |
| Unit | `<path>` | `<command>` | `<most logic changes>` |
| Integration | `<path>` | `<command>` | `<db/api/module-boundary changes>` |
| E2E | `<path>` | `<command>` | `<user workflow changes>` |
| Contract | `<path>` | `<command>` | `<schema/api/event changes>` |
| Performance | `<path>` | `<command>` | `<perf-sensitive changes>` |

### Пример

```md
- Test framework(s): Vitest, Playwright
- Где лежат unit tests: src/**/*.test.ts
- Где лежат e2e tests: tests/e2e/
- Паттерны именования: *.test.ts
- Где лежит CI workflow: .github/workflows/ci.yml
```

---

## Стиль Кода И Naming

- Formatter: `<tool>`
- Linter: `<tool>`
- Политика типизации: `<strict | moderate | dynamic with validation>`
- Политика комментариев: `<when comments are appropriate>`
- Политика импортов: `<absolute | relative | grouped | sorted>`
- Подход к обработке ошибок: `<exceptions | result objects | error wrappers | logging conventions>`
- Подход к логированию: `<structured | plain text | tracing>`
- Подход к конфигурации: `<typed env schema | central config | other>`

### Naming Conventions, Которые Мы Предпочитаем

| Сущность | Предпочтительно | Избегать | Пример |
| --- | --- | --- | --- |
| Файлы | `<preferred_style>` | `<avoid_style>` | `<example>` |
| Директории | `<preferred_style>` | `<avoid_style>` | `<example>` |
| Классы / компоненты | `<preferred_style>` | `<avoid_style>` | `<example>` |
| Функции / методы | `<preferred_style>` | `<avoid_style>` | `<example>` |
| Переменные | `<preferred_style>` | `<avoid_style>` | `<example>` |
| Константы | `<preferred_style>` | `<avoid_style>` | `<example>` |
| Types / interfaces / schemas | `<preferred_style>` | `<avoid_style>` | `<example>` |
| Названия тестов | `<preferred_style>` | `<avoid_style>` | `<example>` |
| Названия веток | `<preferred_style>` | `<avoid_style>` | `<example>` |

### Style Do / Don't

Делать:

- использовать названия, отражающие намерение;
- держать модули цельными и сфокусированными;
- следовать уже существующим паттернам рядом с изменяемым кодом;
- предпочитать явную бизнес-логику “умным” абстракциям.

Не делать:

- превращать `utils` в свалку несвязной логики;
- смешивать несколько naming styles в одной зоне кода;
- прятать важные side effects за расплывчатыми helper names;
- вводить широкие абстракции до появления второго реального use case.

### Пример

```md
| Сущность | Предпочтительно | Избегать | Пример |
| --- | --- | --- | --- |
| Файлы | kebab-case | mixedCase | order-summary-card.tsx |
| Классы / компоненты | PascalCase | snake_case | OrderSummaryCard |
| Функции / методы | verbNoun | generic names | calculateOrderTotal |
| Названия тестов | behavior-focused | “works correctly” | returns 422 when customer is archived |
```

---

## Предпочтительные Паттерны И Эталонные Реализации

Покажите агенту реальные примеры из репозитория.

### Хорошие Примеры, Которые Можно Копировать

- `<path>`: `<why this is a good example>`
- `<path>`: `<why this is a good example>`
- `<path>`: `<why this is a good example>`

### Паттерны, Которые Не Нужно Копировать

- `<path>`: `<why it exists but should not be reused>`
- `<path>`: `<why it exists but should not be reused>`
- `<path>`: `<why it exists but should not be reused>`

### Подсказки Для Заполнения

- Добавьте примеры для типовых задач: feature modules, API handlers, tests, background jobs, migrations, UI components.
- Явно помечайте legacy-примеры, чтобы агент не копировал их в новый код.

### Пример

```md
- `src/features/orders/api/create-order.ts`: good validation -> service -> mapper flow
- `src/features/orders/components/order-form.tsx`: good example of feature-local UI composition
- `src/features/orders/order-form.test.ts`: good example of behavior-focused tests
- `src/legacy/shared/utils.ts`: legacy dumping ground, do not add new business logic here
```

---

## Данные, Контракты, Codegen И Миграции

- Где лежат схемы: `<path>`
- Где лежат миграции: `<path>`
- Где лежат API-контракты: `<path>`
- Где лежат event-контракты: `<path_or_none>`
- Где лежит generated code: `<path>`
- Команда для регенерации: `<command>`

### Правила

- Не редактировать generated files вручную, если в проекте предполагается regeneration workflow.
- Сохранять backward compatibility для `<api | events | database>`, если задача явно не разрешает breaking change.
- При изменении контрактов обновлять также tests, fixtures, docs и зависимые clients, если это применимо.
- Для миграций указывать, обратимы ли они, разрушительны ли и требуют ли координации rollout.

### Пример

```md
- Где лежат схемы: prisma/schema.prisma
- Где лежат миграции: prisma/migrations/
- Где лежат API-контракты: openapi/openapi.yaml
- Где лежит generated code: src/generated/
- Команда для регенерации: pnpm codegen
```

---

## Границы Безопасности И Safety

Считайте этот раздел обязательным.

### Жёсткие Правила

- Никогда не коммитить secrets, private keys, access tokens или production credentials.
- Никогда не хардкодить secrets в source code, tests, fixtures или documentation.
- Редактировать чувствительные значения в логах и примерах.
- Валидировать и санитизировать недоверенный ввод на правильной границе.
- Использовать least privilege для database, cloud и service credentials.
- Быть особенно аккуратным в коде, связанном с auth, billing, PII, legal/compliance, infrastructure или permissions.

### Перед Этими Действиями Нужна Подтверждённая Проверка Человеком

- удаление данных или файлов;
- применение необратимых миграций;
- изменение auth или permission logic;
- изменение billing или payment flows;
- изменение deployment или production infrastructure;
- установка или замена крупных зависимостей;
- ротация secrets или изменение security configuration.

### Чувствительные Зоны

- Authentication / authorization: `<paths_or_notes>`
- Payments / billing: `<paths_or_notes>`
- Personal or regulated data: `<paths_or_notes>`
- Production configuration / infrastructure: `<paths_or_notes>`

---

## Git, PR И Definition Of Done

- Схема именования веток: `<pattern>`
- Формат commit message: `<pattern>`
- Формат заголовка PR: `<pattern>`
- Политика changelog: `<when_and_how_to_update>`
- Политика release notes: `<if_applicable>`

### Definition Of Done

Изменение не считается завершённым, пока:

1. не прошли релевантные проверки;
2. не добавлены или не обновлены тесты там, где это нужно;
3. не обновлены docs/config/examples, если они затронуты;
4. размещение файлов и naming соответствуют этому документу;
5. assumptions, risks и follow-up work зафиксированы.

### Пример

```md
- Схема именования веток: feat/<ticket>-<short-description>
- Формат commit message: conventional commits
- Формат заголовка PR: [ORD-123] Brief imperative summary
- Политика changelog: update CHANGELOG.md for user-visible changes
```

---

## Правила Для Монорепозитория

Если в репозитории несколько приложений, пакетов или сервисов:

- корневой `AGENTS.md` должен определять только глобальные правила;
- у каждого крупного приложения, пакета или сервиса должен быть свой вложенный `AGENTS.md`;
- ближайший к изменяемым файлам `AGENTS.md` должен определять локальные соглашения;
- shared packages должны документировать ожидания по совместимости и ограничения по релизам.

### Рекомендуемая Структура

```text
<repo-root>/
├─ AGENTS.md
├─ apps/
│  ├─ <app-a>/AGENTS.md
│  └─ <app-b>/AGENTS.md
├─ packages/
│  ├─ <shared-lib>/AGENTS.md
│  └─ <shared-ui>/AGENTS.md
└─ infra/
   └─ AGENTS.md
```

---

## Известные Подводные Камни

Перечислите реальные проблемы, в которые агент с высокой вероятностью упрётся:

- `<pitfall_and_how_to_avoid_it>`
- `<pitfall_and_how_to_avoid_it>`
- `<pitfall_and_how_to_avoid_it>`

### Пример

```md
- Do not import pricing helpers from `shared/utils`; use `modules/pricing` instead.
- Changes to `openapi/openapi.yaml` require regenerating typed clients.
- Legacy admin pages still rely on server-rendered templates; do not move them into the SPA without approval.
```

---

## Когда Агент Должен Остановиться И Спросить

Агент должен остановиться и спросить человека, если:

- требования неоднозначны и существует несколько валидных реализаций;
- изменение может нарушить совместимость API, данных или безопасность деплоя;
- документация и код существенно противоречат друг другу;
- тесты падают по причинам, не связанным с задачей, и причина неясна;
- для задачи нужны secrets, production access или product-policy decisions;
- самый безопасный путь зависит от tradeoff, который пользователь ещё не выбрал.

---

## Дополнительная Синхронизация С Другими Инструментами

Если репозиторий использует и tool-specific AI instruction files, держите их синхронизированными:

- `README.md`
- `.github/copilot-instructions.md`
- `CLAUDE.md`
- `.cursorrules`
- `.aider.conf.yml`
- `.gemini/settings.json`

Предпочтителен один authoritative source, а зеркалирование должно быть минимальным.

---

## Чеклист Поддержки Для Людей

- Обновляйте этот файл при изменении архитектуры, стека, команд или workflow.
- Следите, чтобы команды можно было выполнять в точности как они записаны.
- Перед rollout заменяйте расплывчатые плейсхолдеры реальными значениями.
- Добавляйте ссылки на лучшие примеры из репозитория для типовых задач.
- Разносите инструкции по вложенным `AGENTS.md`, когда один файл становится слишком широким по scope.

---

## Чеклист Перед Использованием

Перед тем как использовать этот файл в реальном репозитории, убедитесь, что вы заменили:

- все плейсхолдеры в `<угловых_скобках>`;
- все примерные значения, скопированные из шаблона;
- все общие команды на реальные команды;
- все общие пути на реальные пути;
- все абстрактные правила на проектно-специфичные правила.

Перед тем как считать файл завершённым, убедитесь, что в нём есть:

- обзор проекта;
- стек и версии;
- архитектура и границы;
- структура репозитория;
- точные setup/build/test команды;
- расположение тестов и стратегия запуска;
- naming conventions;
- хорошие и плохие примеры из репозитория;
- границы безопасности;
- правила эскалации;
- ссылки на source-of-truth документацию.