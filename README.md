# SolutionArchitectAI

ИИ-помощник solution-архитектора: от бизнес-требований к согласованным потокам данных и межсистемным взаимодействиям.

**Статус:** реализуется PR 1 — сохраняемые независимые чаты, streaming, серверная отмена и темы. Архитектурное проектирование и артефакты следующих этапов пока не реализованы.

Основной документ — [BRD MVP](docs/BRD.md): назначение, функции, результаты и критерии приёмки.

Готовые файлы для пересылки:

- [BRD MVP — PDF](docs/pdf/brd.pdf).
- [Пример системы — PDF](docs/pdf/example.pdf): входные требования, контекст, таблицы, диаграммы, решения и результаты проверок.
- [Ключевые технические решения — PDF](docs/pdf/technical-decisions.pdf): краткий обзор стека и архитектурных границ.
- [Приложение А.1 — PDF](docs/pdf/brd-input-guidelines.pdf): рекомендации к входящим BRD.
- [Приложение А.2 — PDF](docs/pdf/brd-template.pdf): эталонный Markdown-шаблон BRD.

[Редактирование LaTeX и сборка PDF](docs/PDF.md). PDF хранятся в репозитории вместе с исходными Markdown и LaTeX.

| Документ | Для чего читать |
| --- | --- |
| [BRD MVP](docs/BRD.md) | Функции, ограничения, результаты и критерии приёмки |
| [Приложение А.1](docs/brd-input-guidelines.md) | Рекомендации к входящим BRD |
| [Приложение А.2](docs/templates/brd-template.md) | Самостоятельный эталонный Markdown-шаблон BRD |
| [Принципы архитектуры](docs/architecture.md) | Предложения по модели архитектуры, диаграммам и интеграциям |
| [Техническое проектирование](docs/technical/README.md) | Планируемый стек, контракты агентов, конфигурация, развёртывание, качество и план реализации |
| [Ключевые технические решения](docs/technical/technical-decisions-summary.md) | Краткий технический обзор для архитектора и ведущих разработчиков |
| [Входной пример](docs/examples/reporting-system.md) | Полный синтетический BRD и корпоративный контекст |
| [Ожидаемый результат](docs/examples/reporting-system/expected-result.md) | Таблицы и диаграммы с русскими названиями, решения и проверки |
| [Согласование](docs/review.md) | Открытые решения и порядок приёмки |

Для внешнего ревью предназначены пять PDF; изучать репозиторий не требуется. Markdown, JSON и LaTeX остаются редактируемыми исходниками. После согласования эталон используется для проверки MVP.

[JSON-модель примера](docs/examples/reporting-system/model.json) хранит общие объекты и дерево представлений; обычные архитектурные операции будущего приложения выполняются через UI. [Техническая архитектура](docs/technical/README.md) описывает PostgreSQL/Git/files, агентов и локальные LLM.

Основная ветка приложения — `main`. PR предлагаются к ней; архитектурный репозиторий, которым будет управлять продукт, имеет собственную ветку `main`. Merge выполняет человек.

Python 3.13/uv/FastAPI и React/TypeScript/Vite используют согласованный [стек](docs/technical/README.md). React Flow и LangGraph появятся на предусмотренных дорожной картой этапах. Будущий production — Red Hat OpenShift; текущая поставка рассчитана на локальную работу одного пользователя.

## Локальный запуск PR 1

Из корня репозитория, без внешнего LLM API-ключа:

```powershell
docker compose up -d --build --wait
```

Откройте [приложение](http://localhost:8080) или [OpenAPI](http://localhost:8000/docs). Чистый checkout использует fake LLM. PostgreSQL, Git и файлы имеют отдельные volumes; `docker compose down` сохраняет их. Alembic выполняется отдельным сервисом до старта backend. Порты публикуются только на loopback, PlantUML — только во внутренней сети.

Адреса и порты можно изменить в `.env` по образцу `.env.example`: `COMPOSE_BIND_HOST` задаёт адрес публикации, `COMPOSE_BACKEND_PORT`, `COMPOSE_FRONTEND_PORT`, `COMPOSE_POSTGRES_PORT` и `COMPOSE_FAKE_LLM_PORT` — порты на компьютере. `SAA_SERVER__HOST` / `SAA_SERVER__PORT` задают listener backend внутри контейнера; для связи с nginx оставьте host `0.0.0.0`. Healthcheck и proxy автоматически используют выбранный порт backend. `COMPOSE_FRONTEND_LISTEN_PORT` меняет внутренний порт nginx. Без Compose backend запускается через `uv run --project backend python -m solution_architect_ai.di.server` и использует те же типизированные настройки `server` (YAML и env), с loopback по умолчанию.

Для LM Studio загрузите существующую модель и задайте профиль:

```powershell
lms load qwen2.5-coder-14b-instruct --context-length 4096 --gpu max --parallel 1 --yes
$env:SAA_LLM__BASE_URL = 'http://host.docker.internal:1234/v1'
$env:SAA_LLM__MODEL = 'qwen2.5-coder-14b-instruct'
docker compose up -d --wait
```

LM Studio должен обслуживать API на порту 1234. Этот адрес хоста проверен из контейнера. Для постоянного профиля скопируйте `.env.example` в `.env` и измените URL/model; секреты не передаются frontend. Подробности vLLM и проверенных профилей — в [deployment](docs/technical/deployment.md#локальные-модели).

Для повторного fake-запуска задайте `SAA_LLM__BASE_URL=http://fake-llm:8000/v1` и `SAA_LLM__MODEL=fake-chat`. Fake понимает синтетические команды `[error]`, `[empty]`, `[truncated]`, `[disconnect]`, `[slow]` для проверки ошибок и отмены.

## Проверки разработки

Frontend использует Node 26.13.1 и pnpm 12.21.0, backend — Python 3.13.9 и uv 0.13.9. Установка: `pnpm.cmd --dir frontend install --frozen-lockfile`, `uv sync --locked --project backend`. Список обязательных gates и точные команды находятся в [workflow](.github/workflows/quality.yml); существующая PDF-сборка сохранена.

Локальные hooks устанавливаются воспроизводимо из корня:

```powershell
uv sync --locked --project backend
uv run --locked --project backend python -m tools.quality setup
```

Setup также подготавливает Chromium, если не выбран установленный Edge; в Linux для системных зависимостей могут потребоваться права sudo. Перед push переключитесь на отправляемую ветку и сохраните изменения в commit. После установки commit запускает `fast` (статический анализ, форматирование, архитектура и unit-тесты), push — `full` с аудитами, integration, E2E и отказами runtime. CI вызывает тот же `full`. Можно запускать эти режимы вручную через `uv run --locked --project backend python -m tools.quality fast` / `… full`. Полная проверка использует временный fake-стенд с собственными портами и данными; работающий чат с LM Studio/vLLM сохраняется. Подробнее — [quality-and-testing](docs/technical/quality-and-testing.md#локальные-hooks-и-ci).

Backend integration-тесты требуют отдельную БД и fake endpoint:

```powershell
docker compose exec -T postgres createdb -U solution_architect solution_architect_test
$env:SAA_MODE = 'test'
$env:SAA_DATABASE__HOST = '127.0.0.1'
$env:SAA_DATABASE__PORT = '5433'
$env:SAA_DATABASE__DATABASE = 'solution_architect_test'
$env:SAA_LLM__BASE_URL = 'http://127.0.0.1:8001/v1'
uv run --project backend python -m solution_architect_ai.di.migrate
uv run --project backend pytest backend/tests --disable-socket --allow-hosts=127.0.0.1,localhost --allow-unix-socket
```

`createdb` нужен только при первом создании тестовой БД. Playwright: `$env:PLAYWRIGHT_CHANNEL='chrome'; pnpm.cmd --dir frontend test:e2e` при работающем Compose с fake-профилем. При изменении опубликованных портов задайте `SAA_APP_URL` для Playwright и соответствующие `SAA_DATABASE__PORT` / `SAA_LLM__BASE_URL` для backend-тестов. `uv run --locked --project backend python -m tools.runtime_smoke` создаёт собственный временный fake-стенд, перезапускает в нём backend/PostgreSQL и проверяет отказ БД. Рабочий Compose-проект этот smoke не использует.

Run имеет неизменяемые терминальные статусы, `incomplete` отдельно от статуса, UUID команды для идемпотентного запуска и монотонный sequence. SSE передаёт полные сохранённые снимки; reconnect не запускает LLM повторно. После прерывания процесса run становится failed/incomplete и автоматически не повторяется. Закрытие вкладки не отменяет генерацию; кнопка остановки отправляет отдельную серверную команду. Backend подтверждает остановку локального потока, без гарантии прекращения вычислений внешнего сервера.

Тема применяется из локального сохранения до ответа API, затем используется настройка PostgreSQL; ручной выбор в текущем сеансе имеет приоритет. AC-18/AC-19 покрыты в объёме чатов и тем PR 1; файлы, агентный процесс и диаграммы относятся к следующим этапам.
