# Persistence и согласованность хранилищ

[Навигация](README.md) · [Git](git-workflow.md) · [Файлы](file-storage.md)

## Распределение данных и порты

| Хранилище | Авторитетные данные | Порт Application |
| --- | --- | --- |
| Git | JSON-модель, дерево видов, существенные подтверждённые решения, версионируемые результаты проверок, pinned источники, воспроизводимые .puml | ArchitectureRepository: read_revision, create_task_branch, commit_changes(expected_head, operation_id), diff, inspect_merge |
| PostgreSQL | Пространства/проекты/задачи, чаты/сообщения, agent runs, drafts/proposals, ответы, настройки, статусы, привязки веток/коммитов, журнал операций и разрешений; отдельно таблицы checkpoints LangGraph | TaskRepository, ChatRepository, RunRepository, OperationJournal и SQL UnitOfWork для одной БД |
| Local filesystem или S3-compatible API | Оригиналы документов/вложения, крупные бинарные файлы, производные и временные экспорты | FileStorage: put_immutable, get_version, verify, delete_unreferenced |

Checkpoints LangGraph сохраняют выполнение графа, а SQL-журнал — предметные команды и их идемпотентность. Они не дублируют один и тот же next-stage. GraphState содержит ссылки и версии, не полную архитектуру или копию журнала. Git и SQLAlchemy не взаимозаменяемы. Будущий GitLab-адаптер добавит удалённые операции к Git-порту без изменения domain; MR не часть обязательного workflow. Права на merge остаются у человека вне LLM-порта. История сообщений не служит реестром подтверждённых решений: существенный ответ переносится в model/decision отдельной командой человека.

## Согласованность хранилищ

Общей транзакции PostgreSQL/Git/S3 нет; checkpoint LangGraph её также не создаёт. Одна команда имеет operation_id, scope, payload digest, expected_head и журнал стадий. SQL UoW обеспечивает атомарность только собственных записей.

| Стадия | Действие и восстановление |
| --- | --- |
| prepared | SQL фиксирует intent и ключ идемпотентности; повтор с другим payload отклоняется; повтор завершённого результата возвращается до проверки текущего HEAD |
| files_ready | immutable upload по заранее назначенным version/key; verify size/hash; pin/reservation. Сбой оставляет pending объект, повтор проверяет существующий, не перезаписывает |
| git_prepared | структурная целостность кандидата проверена синхронно, commit создан, hash записан в журнал; неизменяемая staging ref удерживает commit до recovery |
| git_published | CAS обновляет task ref; operation_id находится в metadata. После публикации асинхронно проверяются топология и правила с отчётом A-07. Сбой до CAS оставляет прежний head; после CAS результат восстанавливается по commit/ref и журналу, без второго commit |
| completed | SQL сохраняет итоговый hash, связи и pin; ответ выдаётся после сверки. Если SQL недоступен после CAS, операция pending/recovering, а не откатившаяся |

Сбой между созданием commit и записью его hash восстанавливается по operation_id/staging ref. Recovery проверяет ожидаемого родителя и payload digest; при внешнем продвижении ref ищет результат в истории, неоднозначность блокирует новую запись. Короткая публикация защищена от отмены HTTP; disconnect не отменяет уже применённое действие. GET operation_id сообщает фактический исход. Cleanup не удаляет данные pending/published операций; при недоступном хранилище GC приостанавливается. Слепой retry всей команды недопустим.
