# Backend: стек и границы

[Навигация](README.md) · [Предметная модель](domain-model.md) · [Persistence](persistence.md) · [Lifecycle](resource-lifecycle.md)

## Стек и направления зависимостей

Рекомендуется модульный Python backend: FastAPI/OpenAPI, Dishka AsyncContainer, PostgreSQL, SQLAlchemy 2.x async и Alembic. Pydantic проверяет внешние контракты, Pydantic Settings — конфигурацию. Domain использует dataclasses/enum и чистые валидаторы без ORM/HTTP/LLM SDK. Полные DDD, CQRS, event sourcing и микросервисы MVP не нужны. Фичи группируются внутри пакетов; общие порты принадлежат их потребителю в Application.

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
