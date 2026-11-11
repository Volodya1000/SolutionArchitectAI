# Агенты, структурированная генерация и контекст

[Навигация](README.md) · [Хранение и Git](backend.md) · [RetryConfig](configuration.md)

## Роли MVP и контракт

Агенты — роли внутри одного backend, не независимые сервисы. Минимум **четыре**: три явно требуемые роли и один генератор архитектурных предложений. Независимые DataArchitectureAgent/IntegrationDesignAgent пока не нужны: их разные схемы заданий и промпты использует ArchitectureDesignAgent. Отдельные роли оправдаются различием источников, результатов или независимых проверок, а не количеством операций.

| Роль | Вход AgentRequest.payload | Успешный AgentResult.payload |
| --- | --- | --- |
| BRDAnalysisAgent | BRD-фрагменты, связанные правила, область анализа | BRDAnalysis: FR/NFR с source refs, противоречия, пробелы; это извлечённые кандидаты, не подтверждённые факты |
| ClarificationAgent | BRDAnalysis, требования, пробелы, реестр вопросов/ответов | ClarificationSet: question_id, gap_key, текст, blocking, основание, dependent_requirement_ids; при блокировке envelope NeedsInput |
| ArchitectureDesignAgent | Принятые требования/ответы, общий каталог и связи, затронутые виды/решения/правила | ChangeProposal: типизированные предметные операции, основания, альтернативы и затронутые ID |
| ArchitectureReviewAgent | Неизменяемый кандидат и diff, требования/правила/решения, FormalReport | ReviewReport: область, snapshot digest, сомнительные предложения, противоречия и source refs; без права применения |

Общий envelope **AgentRequest → AgentResult** содержит workspace_id/project_id/task_id, run_id, operation_id, attempt_id, role, contract_version, base_commit, source/rule digests и execution context (deadline, cancellation, model profile, token budget, prompt version). Результат — один из BRDAnalysis/ClarificationSet/ChangeProposal/ReviewReport/NeedsInput/typed failure, допустимый для конкретной роли. SDK-объекты и credentials в контракт не входят. Агент не знает соседей и не получает capability записи в хранилище.

В ChangeProposal: proposal_id, base_commit, expected old values, операции над ID/локальными ключами новых объектов, зависимости, provenance и объяснение. Application назначает устойчивые ID один раз при подготовке операции и проверяет целостность. Полный новый state или произвольный JSON Patch не заменяют предметные операции. ReviewReport нельзя применить как proposal; LLM не назначает approval.

Ответ человека обрабатывает **AnswerClarification use case**: проверяет question_id, revision, автора, сохраняет ответ, обновляет связанные требования и допущения/риски. Предположение агента не становится ответом человека. Повторный ClarificationAgent получает закрытые gap_key и ответы, не повторяет закрытые вопросы; новое основание/ревизия может явно reopen вопрос. Semantic dedup не гарантируется одним ID, нормализованный gap_key и UI-сопоставление защищают от парафразов. Неблокирующий вопрос не останавливает независимую работу.

## Pipeline и выбор оркестрации

BRDAnalysis → Clarification → ожидание/ответ человека → ArchitectureDesign → формальные валидаторы → ArchitectureReview → решение человека → применение. Независимый анализ разрешён при открытых вопросах; зависимые стадии ждут. Применение и согласование различаются, [merge](backend.md#git-workflow) выполняется отдельно человеком.

| Критерий | A: детерминированный application pipeline | B: LangGraph |
| --- | --- | --- |
| Код и читаемость | Небольшая явная таблица стадий/переходов; сами пишем claims, resume и журнал | Nodes/state/edges и готовые interrupts/checkpoints; дополнительный runtime и mapping |
| Тестируемость | Каждый переход/use case с fake-портами; контракт PostgreSQL/Git проверяется отдельно | Удобные тесты узлов/переходов; replay/interrupt тоже требуют сценариев |
| Состояние/HITL | PostgreSQL RunState, waiting_input без живой coroutine, resume use case | Checkpointer и thread_id, interrupt/resume из framework |
| Сбой/отмена | Interrupted + повторное выполнение безопасной стадии; собственный ограниченный recovery | Готовые checkpoints уменьшают код восстановления, side effects всё равно должны быть идемпотентны |
| PostgreSQL/Git | Один журнал команд приложения; SQL транзакция только SQL | PostgreSQL checkpointer возможен; не объединяет Git/S3 с SQL и может дублировать RunState |
| Когда окупается | Линейный MVP с несколькими развилками | Большое ветвление, циклы, подграфы и сложные повторные исполнения |

**Рекомендация — A.** Это реальная персистентная машина переходов, не цепочка вызовов в HTTP router. Сохраняются run_id, typed stage/status, stage input/output refs, state_version, branch/base_commit, prompt/model config digest, счётчики повторов, lease и ожидаемые question IDs. Переход — короткая SQL CAS-команда. waiting_input переживает restart; после ответа новый execution scope продолжает run с проверкой ревизии. Неоконченная running стадия становится interrupted, автоматическое повторное применение запрещено. Лимиты повторов стадии и LLM retries различаются. [LangGraph persistence](https://docs.langchain.com/oss/python/langgraph/persistence) не отвергается вообще, но сейчас дублирует значительную часть обязательного журнала предметных команд.

Tool Calling в MVP отсутствует: нет динамического реестра tools, model-driven цикла, shell или самостоятельной записи ИИ. Structured output использует JSON Schema/JSON text, а не скрыто выбранный tool mode.

## StructuredOutputGenerator

Один переиспользуемый application-порт, концептуальная сигнатура без реализации:

```text
async generate[T: BaseModel](
    messages: PromptMessages,
    model_profile: ModelProfile,
    result_schema: type[T],
    parameters: GenerationParameters,
    retry: RetryConfig,
    deadline: Deadline,
    cancellation: CancellationContext,
) -> T | StructuredGenerationFailure
```

Порт отвечает за структурированный результат, capability policy, runtime-валидацию и ошибки, но не за истину архитектуры, отбор контекста, подтверждение и Git. Все агенты используют его; обычный потоковый текст чата может идти через отдельный LLM streaming port. Частично полученный JSON не становится proposal до завершения валидации.

| Подход | Что готово | Ограничение и решение |
| --- | --- | --- |
| [LiteLLM response_format](https://docs.litellm.ai/docs/completion/json_mode) + Pydantic | Нормализация провайдеров, async, JSON Schema и готовая валидация Pydantic | Сам по себе не весь reusable validation/reask lifecycle; жизненный цикл корректирующей генерации пришлось бы собирать |
| [Instructor + LiteLLM](https://docs.litellm.ai/docs/tutorials/instructor) | Async, generic response_model, Pydantic validation, готовый feedback/retry; LiteLLM меняет транспорт без изменения агентов | Ещё одна узкая библиотека; режимы и retry надо настроить явно. **Рекомендуем** |
| [LangChain structured output](https://docs.langchain.com/oss/python/langchain/models#structured-output) / PydanticOutputParser | with_structured_output и Pydantic; OutputParser проверяет текст | Полезно при уже выбранном LangChain; только ради этой функции добавляет лишний framework. Автоматический ToolStrategy не подходит заданию |
| Native OpenAI-compatible JSON Schema | LM Studio/vLLM могут ограничивать форму на сервере | Это capability backend, а не общий клиентский lifecycle; прямой SDK привязал бы retry/error mapping к одному API |

**Выбор: Instructor поверх LiteLLM SDK и Pydantic за одним Infrastructure-адаптером.** [Официальная интеграция](https://python.useinstructor.com/integrations/litellm/) поддерживает async; [режимы Instructor](https://python.useinstructor.com/modes-comparison/) позволяют выбрать native JSON_SCHEMA или явно разрешённый JSON-text/MD_JSON с Pydantic. Default tool mode не используем. Фабрика адаптера выбирает поддерживаемый режим из профиля, а не по ветке `if vllm` внутри агента. Native schema предпочтительна. Переход к менее строгому режиму требует явной настройки и видимой диагностики; unsupported schema/capability — ошибка, не молчаливое ослабление. Собственного универсального JSON-parser, исправления regex и constrained decoding не создаём.

Смена поддерживаемого провайдера/endpoint требует профиля подключения и capability-smoke, не правок агентов/use cases. Универсальность API не означает одинаковых возможностей всех моделей. [LM Studio](https://lmstudio.ai/docs/developer/openai-compat/structured-output) и [vLLM](https://docs.vllm.ai/en/latest/features/structured_outputs/) описывают JSON Schema, но совместимость конкретной модели, schema subset и версии backend проверяется отдельно. SDK support registry — подсказка, не доказательство для произвольного локального model ID. Ollama в проекте не используется.

Ошибки типизированы: EmptyResponse, IncompleteResponse, InvalidStructuredOutput, UnsupportedSchema, UnsupportedCapability, ContextTooLarge, AuthenticationFailure, TransientTransportFailure, DeadlineExceeded, Cancelled. Refusal — отдельный отказ, не валидная пустая модель. Validation feedback содержит безопасную диагностику полей, не секреты. Retry exhaustion возвращает ошибку/отдельный incomplete draft, не фиктивный успех. Смена модели/провайдера никогда не выполняется молча. Структура не доказывает истинность: затем выполняются domain-валидация и независимый judge.

## Контекст по ролям

**ContextBuilder** собирает immutable ContextPack: base_commit, selected IDs, source version/hash/locator, rule/decision IDs, coverage/omission manifest, prompt version и token estimate. Структурированный граф и текстовый корпус обрабатываются разными способами.

| Роль | Обязательный контекст | Дополнительный контекст |
| --- | --- | --- |
| BRDAnalysis | Выбранная неизменяемая версия BRD, область анализа, обязательные применимые правила | По частям длинного BRD; результаты частей сводятся с проверкой покрытия |
| Clarification | Analysis, пробелы, связанные требования, ответы/закрытые вопросы, решения человека | Релевантные исходные фрагменты и небольшой контекст диалога |
| ArchitectureDesign | Принятые требования, mandatory rules, связанные общие объекты/интерфейсы и решения | Соседние объекты по связям, затронутые виды, подходящие паттерны |
| ArchitectureReview | Кандидат/diff и base revision, требования, правила, подтверждённые решения, FormalReport | Независимый подбор доказательств и соседей; не только цитаты, выбранные генератором |

MVP: выбор по устойчивым ID, типам, relations и ссылкам требований; индекс «где используется»; извлечённый текст с секциями/локаторами и простой лексический поиск. PostgreSQL full-text search полезен при росте корпуса; нормализация русского текста проверяется на собственных вопросах. Весь каталог и chat history автоматически не отправляются.

| Стратегия | Применимость |
| --- | --- |
| ID/явные связи/фильтры | Первый выбор для модели; точные зависимости и целостность |
| Связи требований/решений | Обязательные доказательства и правила без probabilistic retrieval |
| Поиск по документам / full-text | MVP для неизвестных терминов и крупных текстов; возвращает фрагмент и неизменяемый source ref |
| Embeddings/semantic search | Только после измеренных пропусков лексического поиска; не заменяет точные ID/обязательные правила |
| Hybrid RAG | Объединяет exact/lexical/semantic срезы; вводится при подтверждённом росте recall на размеченном наборе и приемлемой задержке |

Embedding-модель, vector DB и RAG-framework в MVP не добавляются. Переход обосновывается retrieval recall/coverage на размеченных вопросах, missed-document анализом и сравнением с full-text; пороги заранее не объявляются согласованными. Для структурированных объектов embeddings не источник идентичности.

Budget: context_window минус output_limit, system/schema tokens и safety reserve. Сначала применимые обязательные правила и решения человека, затем требования/доказательства/объекты, потом необязательная история. При переполнении сокращаем историю, разбиваем вход с явной областью или возвращаем ContextTooLarge/NeedsInput. Обязательные правила не отбрасываются молча; полная проверка не заявляется при частичном покрытии. Cache key включает Git revision, source hashes, rule versions и prompt/config digest; любое изменение инвалидирует зависимый контекст и отчёт. При завершении генерации проверяется expected head, stale предложение не применяется.

Faithfulness к найденному срезу может оставаться высокой, даже если retrieval пропустил запрещающий документ. Citation Faithfulness проверяет поддержку ссылки, но также не доказывает полноту контекста. Поэтому отдельно измеряются полнота источников/генерации, корректность объектов и нарушения; omissions видны ревьюеру.

## Промпты, применение и полномочия

Один промпт — один Python-файл в `application/prompts/`: analyze_brd.py, generate_questions.py, design_architecture.py, review_architecture.py. Типизированная чистая функция с явными параметрами возвращает сообщения и instruction_version (дополнительно content hash); тесты проверяют переменные, границы доверия и обязательный контекст. Python-функций достаточно; ChatPromptTemplate потребовал бы LangChain, Jinja2 оправдан лишь сложными повторяющимися шаблонами. Нет eval, секретов или собственной template-системы. Trusted instructions отделены от недоверенных документов/ответов, содержимое источника не получает system role.

Proposal/report закреплены за base_commit и input digests. Кандидат создаётся на копии снимка; типы/ссылки/правила проверяются независимо от LLM. Человек видит diff, основания, затронутые виды и замечания до принятия; отдельное принятие требуется для замены подтверждённого решения. Judge не отменяет формальную ошибку. Успех проверки не является approval. Принятое допущение обновляет A-01 и риск A-07, не отменяет обязательное правило.

Основной UI выделяет сомнительные **предложения ИИ**, особенно конфликтующие с человеком/правилами; сохраняет происхождение всех объектов, но не навязывает балл или бейдж каждому элементу. Внутренние результаты «нарушение / не проверено / требует внимания / проверено» имеют основания и scope, не десятибалльную шкалу. ИИ не коммитит, не делает merge, не обходит checks и не объявляет собственные предположения согласованными.

[RetryConfig](configuration.md#retryconfig), [журнал применения](backend.md#согласованность-хранилищ) и [сценарии качества](quality-and-testing.md) определяют поведение при ошибках. LLM retry никогда не охватывает применение Git-коммита.
