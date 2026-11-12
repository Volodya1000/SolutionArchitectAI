# Backend: стек и границы

[Навигация](README.md) · [Предметная модель](domain-model.md) · [Persistence](persistence.md) · [Lifecycle](resource-lifecycle.md)

## Стек и направления зависимостей

Планируется модульный backend на **Python 3.13**, с **uv** для управления зависимостями и воспроизводимыми окружениями: FastAPI/OpenAPI, Dishka AsyncContainer, PostgreSQL, SQLAlchemy 2.x async и Alembic. Pydantic проверяет внешние контракты, Pydantic Settings — конфигурацию. Domain использует dataclasses/enum и чистые валидаторы без ORM/HTTP/LLM SDK. Полные DDD, CQRS, event sourcing и микросервисы MVP не нужны. Фичи группируются внутри пакетов; общие порты принадлежат их потребителю в Application.

| Пакет | Обязанность и допустимые импорты |
| --- | --- |
| domain | Архитектурные объекты, требования, решения и инварианты; стандартная библиотека и свой код |
| application | Use cases, агентные DTO и Pydantic-схемы результатов, ContextBuilder, запуск графа, порты; зависит от domain, не от адаптеров |
| persistence | SQLAlchemy, Alembic, SQL-репозитории, Git-адаптер, local/S3 storage; реализует порты application, может использовать domain |
| infrastructure | LangChain LLM-адаптер, композиция LangGraph и PostgreSQL checkpointer, парсеры документов, PlantUML; реализует порты application |
| presentation | FastAPI, HTTP DTO, SSE и возможный CLI; вызывает application, не конкретные persistence/infrastructure |
| config | Чтение и валидация настроек; не импортируется domain/application |
| di | Composition root связывает реализации и lifecycle; единственная точка сборки |

**Persistence — отдельный технический пакет инфраструктурных адаптеров, а не новый внутренний архитектурный слой.** Зависимости направлены внутрь к Application/Domain. Infrastructure, Persistence и Presentation независимы друг от друга. Не вводим Domain → Persistence или универсальный `IRepository`, скрывающий различия SQL и Git.

```text
backend/src/solution_architect_ai/
  domain/                 # architecture, requirements, decisions, verification
  application/            # use cases по фичам, agents, context, ports
    prompts/              # один промпт — один Python-файл
  persistence/            # postgres, migrations, git, files
  infrastructure/         # llm, documents, rendering
  presentation/           # http, streaming
  config/
  di/
```

Application DTO выражают команду/результат, а не копируют HTTP-объекты. Общие Pydantic-схемы LLM принадлежат Application, SDK-типы не выходят из Infrastructure. Mapping в domain явный; неизвестные поля внешних контрактов отклоняются.

Dishka APP scope владеет пулами/HTTP-клиентами и фабриками; REQUEST — коротким use case и SQL session. Длительный run получает отдельный execution scope и не удерживает HTTP session. APP не захватывает REQUEST. При shutdown ресурсы закрываются. Unit use cases собираются напрямую с fake-портами; integration проверяет DI/lifecycle.

## Когда вводить абстракцию

Protocol, ABC и интерфейс вводятся при конкретной пользе: несколько реальных реализаций, предусмотренная замена внешней зависимости, изоляция Application от Persistence/Infrastructure, отдельный fake для существенного тестового сценария или существенная архитектурная граница. Причина указывается рядом с контрактом. Формальный шаблон Clean Architecture, интерфейс для каждого класса, гипотетическая вторая реализация и универсальность сами по себе недостаточны. Автоматических пар `IChatService/ChatService`, `IRequirementsAgent/RequirementsAgent`, `ISettingsService/SettingsService` нет.

| Механизм | Когда уместен |
| --- | --- |
| Конкретный класс/чистая функция | Одна внутренняя реализация без значимой границы: prompt builder, чистый сервис, настройки, чистый сервис |
| `typing.Protocol` | Небольшой структурный порт, когда адаптеры и fake должны соответствовать контракту без общего наследования; соответствие проверяет type checker, runtime-проверка не заменяет тесты поведения |
| `ABC` | Нужны номинальная принадлежность, запрет создания неполной реализации через абстрактные методы или общий жизненный цикл с полезной базовой реализацией; наследование имеет реальную цель |

Protocol не автоматически лучше ABC. Форму выбираем по контракту и проверяемым свойствам. Порты чтения архитектурных ревизий, SQL UoW, immutable файлов и LLM принадлежат потребителю — Application; адаптеры находятся в `persistence` и `infrastructure`. Git, PostgreSQL и S3 имеют разные семантики: универсального `IRepository` нет. Domain не импортирует Persistence, Application не импортирует его реализации. [import-linter](quality-and-testing.md#архитектурные-импорты) сохраняет направления импортов; тесты контрактов проверяют поведение, которое lint доказать не может.

## Python 3.13 и воспроизводимость

Целевая версия — CPython **3.13** (обычная сборка с GIL). При реализации `requires-python` задаётся как `>=3.13,<3.14`, uv создаёт окружение и общий `uv.lock`; CI и контейнер устанавливают зависимости через `uv sync --locked`. Это обеспечивает одинаковое разрешение, но не заменяет фиксацию версии Python/uv и базового образа. Приложение и runtime-зависимости этим PR не создаются.

Проверено **12 ноября 2026 года**: PyPI `Requires-Python`, классификаторы 3.13 и доступность бинарных зависимостей. Снимок основных пакетов:

| Пакет | Версия | Requires-Python | Основание для Python 3.13 |
| --- | --- | --- | --- |
| FastAPI | 0.162.5 | >=3.10 | Классификатор 3.13 |
| Dishka | 1.10.1 | >=3.10 | Классификатор 3.13 |
| Pydantic | 2.14.3 | >=3.10 | Классификатор 3.13; pydantic-core разрешён для cp313 |
| Pydantic Settings | 2.16.2 | >=3.11 | Классификатор 3.13 |
| SQLAlchemy | 2.1.8 | >=3.11 | Классификатор и cp313 wheels |
| Alembic | 1.20.1 | >=3.10 | Классификатор 3.13 |
| langchain-core | 1.8.0 | >=3.11,<4 | Классификатор 3.13 |
| langchain-openai | 1.7.4 | >=3.10,<4 | Классификатор 3.13 |
| langgraph | 1.2.20 | >=3.10 | Классификатор 3.13 |
| langgraph-checkpoint-postgres | 3.2.0 | >=3.10 | Допускает 3.13 по metadata, отдельного классификатора нет; разрешение с psycopg |
| psycopg | 3.3.9 | >=3.10 | Классификатор 3.13; планируется общий PostgreSQL-драйвер SQLAlchemy/checkpointer |
| uv | 0.13.8 | >=3.8 | Поддерживает управление CPython 3.13; отдельный инструмент, не библиотека backend |

Источники: [FastAPI](https://pypi.org/pypi/fastapi/json), [Dishka](https://pypi.org/pypi/dishka/json), [Pydantic](https://pypi.org/pypi/pydantic/json), [Settings](https://pypi.org/pypi/pydantic-settings/json), [SQLAlchemy](https://pypi.org/pypi/sqlalchemy/json), [Alembic](https://pypi.org/pypi/alembic/json), [core](https://pypi.org/pypi/langchain-core/json), [OpenAI adapter](https://pypi.org/pypi/langchain-openai/json), [LangGraph](https://pypi.org/pypi/langgraph/json), [checkpointer](https://pypi.org/pypi/langgraph-checkpoint-postgres/json), [psycopg](https://pypi.org/pypi/psycopg/json), [uv](https://docs.astral.sh/uv/concepts/python-versions/).

Временный набор этих библиотек (без uv как runtime) успешно разрешён `uv pip compile --python-version 3.13 --python-platform x86_64-manylinux_2_28 --only-binary :all:`; разрешены также `psycopg[binary,pool]` для PostgreSQL. Проверка означает отсутствие конфликта metadata и наличие подходящих дистрибутивов для указанной цели. Установка и совместное выполнение backend, запросы к БД, lifecycle Dishka/checkpointer и реальные LLM этим не проверяются. Это не готовый lock приложения: версии повторно проверяются и фиксируются вместе при реализации, для целевой архитектуры контейнеров отдельно проверяются wheels/системная libpq.

Python-модель остаётся носителем предметных операций и инвариантов; JSON сериализует/восстанавливает её редакцию в Git. Проверка JSON Schema не заменяет предметные правила.
