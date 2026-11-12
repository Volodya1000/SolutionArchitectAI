# Жизненный цикл ресурсов и async

[Навигация](README.md) · [Persistence](persistence.md)

Один backend worker для MVP и ограниченные управляемые задачи; PostgreSQL хранит run-state после рестарта. Стадии claim выполняются атомарно с версией/lease, чтобы два возобновления не породили две публикации. Redis/workflow engine не нужны. LLM-вызов не держит DB-транзакцию или Git lock.

Async оправдан для LLM, HTTP, SQL async driver, streaming и поддерживаемого storage I/O. Синхронный Git/локальные файлы выносятся в контролируемый thread pool; CPU-парсинг и тяжёлый рендер — в process/subprocess с timeout и cleanup. Чистые domain-правила остаются синхронными. Не блокируем event loop, не делим одну AsyncSession между конкурентными задачами; session на отдельный use case/task ([SQLAlchemy](https://docs.sqlalchemy.org/en/20/orm/extensions/asyncio.html#using-asyncsession-with-concurrent-tasks)).

TaskGroup/структурированная конкурентность там, где подзадачи имеют общий lifecycle; нет бесконтрольных fire-and-forget. CancelledError распространяется после cleanup; общий monotonic deadline охватывает ожидание semaphore, сеть, backoff и генерацию. LLM concurrency ограничен. Shutdown прекращает новые runs, отменяет/ожидает активные, закрывает потоки/clients/sessions; незавершённые стадии получают interrupted. Временные и постоянные ошибки различаются.

Команда запуска возвращает run_id. Streaming — SSE (или fetch-stream с согласованным event envelope): run_id, event_id/sequence, kind, payload; reconnect восстанавливает сообщение и статус из PostgreSQL, не запускает новую генерацию. Отмена — отдельная идемпотентная команда; частичный текст остаётся явно incomplete. Логи содержат task/run/operation IDs, задержки, токены, модель/версию, параметры, ошибки и повторы; секреты и полные документы по умолчанию исключены. Расчётов оплаты LLM нет.

## Обязательный управляемый scope

Если объект владеет освобождаемым ресурсом или требует асинхронной инициализации/завершения, публичный API выдаёт его только внутри `async with`. Это относится к AsyncSession, транзакциям/соединениям, временным execution-ресурсам. Фабрика возвращает `AsyncContextManager[Resource]`, а не `Resource` или coroutine, возвращающую открытый ресурс. Реализация фабрики использует `@asynccontextmanager`; композиция — `AsyncExitStack`. Dishka scoped providers с `yield` освобождают ресурсы при закрытии своего scope.

Концептуальный пример контракта и использования (не реализация):

```text
RunScopeFactory.open(run_id) -> AsyncContextManager[RunScope]
UnitOfWorkFactory.open() -> AsyncContextManager[UnitOfWork]

async with run_scopes.open(run_id) as execution:
    async with execution.uow.open() as uow:
        inputs = await uow.runs.claim_and_read(run_id)
        await uow.commit()
    # SQL session/transaction уже закрыта перед длительной генерацией
    result = await execution.generate(inputs)
    async with execution.uow.open() as uow:
        await uow.runs.save_if_current(result)
        await uow.commit()
```

Внешний execution scope владеет временными ресурсами, deadline и управляемыми подзадачами, но не удерживает одну SQL session весь run. При исключении/отмене незавершённая транзакция откатывается, затем session/соединение закрываются; закрытие выполняется и при частичной инициализации. Защищённое конечным timeout завершение публикации подчиняется [журналу](persistence.md#согласованность-хранилищ), а не бесконечному shield. `CancelledError` не поглощается.

Конструкторы ресурсных реализаций остаются внутри адаптера/DI; Application получает только scoped factory. Запрещены прямой `AsyncSession()`/создание соединений вне providers и сохранение scoped объекта в singleton, глобальную переменную, HTTP background task или результат use case. В Python нельзя доказать отсутствие всех утечек только типами: правило дополняют import-linter, AST-проверка мест создания ресурсов и lifecycle integration-тесты (успех, исключение, отмена, частичная инициализация, использование после выхода). Результаты use cases — отделённые DTO, не live ORM entities.

Одна AsyncSession никогда не разделяется между конкурентными задачами; каждая получает собственный scope. HTTP-обработчик только запускает/читает run и не владеет его ресурсами. Worker управляет TaskGroup, остановкой и ожиданием; неуправляемые background tasks запрещены. Обычные domain-объекты, DTO, конфигурация и чистые сервисы остаются обычными классами. Scope предназначен для владения ресурсами, а не для любого объекта.
