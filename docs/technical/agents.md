# Роли агентов и контракты

[Навигация](README.md) · [Pipeline](agent-pipeline.md) · [Structured output](structured-output.md) · [Контекст](context-management.md)

## Роли MVP и контракт

Агенты — роли внутри одного backend, не независимые сервисы. Для MVP достаточно **четырёх ролей**. Независимые DataArchitectureAgent/IntegrationDesignAgent пока не нужны: их разные схемы заданий и промпты использует ArchitectureDesignAgent. Отдельные роли оправдаются различием источников, результатов или независимых проверок, а не количеством операций.

| Роль | Вход AgentRequest.payload | Успешный AgentResult.payload |
| --- | --- | --- |
| RequirementsExtractionAgent | Релевантные документы или фрагменты: описания заказчика, ТЗ, функциональные/нефункциональные требования и дополнительные материалы; версии, локаторы и область анализа | RequirementsExtraction: FR/NFR с source refs, противоречия, пробелы; это извлечённые кандидаты, не подтверждённые факты |
| ClarificationAgent | RequirementsExtraction, требования, пробелы, реестр вопросов/ответов | ClarificationSet: question_id, gap_key, текст, blocking, основание, dependent_requirement_ids; при блокировке envelope NeedsInput |
| ArchitectureDesignAgent | Принятые требования/ответы, общий каталог и связи, затронутые виды/решения/правила | ChangeProposal: типизированные предметные операции, основания, альтернативы и затронутые ID |
| ArchitectureReviewAgent | Неизменяемый кандидат и diff, требования/правила/решения, FormalReport | ReviewReport: область, snapshot digest, сомнительные предложения, противоречия и source refs; без права применения |

Общий envelope **AgentRequest → AgentResult** содержит workspace_id/project_id/task_id, run_id, operation_id, attempt_id, role, contract_version, base_commit, source/rule digests и execution context (deadline, cancellation, model profile, token budget, prompt version). Результат — один из RequirementsExtraction/ClarificationSet/ChangeProposal/ReviewReport/NeedsInput/typed failure, допустимый для конкретной роли. SDK-объекты и credentials в контракт не входят. Агент не знает соседей и не получает capability записи в хранилище.

В ChangeProposal: proposal_id, base_commit, expected old values, операции над ID/локальными ключами новых объектов, зависимости, provenance и объяснение. Application назначает устойчивые ID один раз при подготовке операции и проверяет целостность. Полный новый state или произвольный JSON Patch не заменяют предметные операции. ReviewReport нельзя применить как proposal; LLM не назначает approval.

Ответ человека обрабатывает **AnswerClarification use case**: проверяет question_id, revision, автора, сохраняет ответ, обновляет связанные требования и допущения/риски. Предположение агента не становится ответом человека. Повторный ClarificationAgent получает закрытые gap_key и ответы, не повторяет закрытые вопросы; новое основание/ревизия может явно reopen вопрос. Semantic dedup не гарантируется одним ID, нормализованный gap_key и UI-сопоставление защищают от парафразов. Неблокирующий вопрос не останавливает независимую работу.

## Промпты, применение и полномочия

Один промпт — один Python-файл в `application/prompts/`: extract_requirements.py, generate_questions.py, analyze_context.py, select_components.py, define_components.py, design_data.py, design_flows.py, design_integrations.py, compose_views.py, review_architecture.py. Типизированная чистая функция с явными параметрами возвращает сообщения и instruction_version (дополнительно content hash); тесты проверяют переменные, границы доверия и обязательный контекст. Python-функций достаточно и при выбранном LangChain; `ChatPromptTemplate` из `langchain-core` доступен, если он даст конкретную пользу. Jinja2 оправдан лишь сложными повторяющимися шаблонами. Нет eval, секретов или собственной template-системы. Trusted instructions отделены от недоверенных документов/ответов, содержимое источника не получает system role.

Proposal/report закреплены за base_commit и input digests. Кандидат создаётся на копии снимка; типы/ссылки/правила проверяются независимо от LLM. Человек видит diff, основания, затронутые виды и замечания до принятия; отдельное принятие требуется для замены подтверждённого решения. Judge не отменяет формальную ошибку. Успех проверки не является approval. Принятое допущение обновляет A-01 и риск A-07, не отменяет обязательное правило.

Основной UI выделяет сомнительные **предложения ИИ**, особенно конфликтующие с человеком/правилами; сохраняет происхождение всех объектов, но не навязывает балл или бейдж каждому элементу. Статусы контроля «Подтверждено / Требует проверки / Нарушение / Недостаточно данных» независимы от происхождения и согласования, имеют основания и scope, не десятибалльную шкалу. ИИ не коммитит, не делает merge, не обходит checks и не объявляет собственные предположения согласованными.

[RetryConfig](configuration.md#retryconfig), [журнал применения](persistence.md#согласованность-хранилищ) и [сценарии качества](quality-and-testing.md) определяют поведение при ошибках. LLM retry никогда не охватывает применение Git-коммита.

Извлечение требований отделено от интерпретации: RequirementsExtractionAgent сохраняет FR/NFR, исходные формулировки, противоречия, пробелы, source ID/version/locator и границу покрытия. Предположения возвращаются отдельно и не объявляются подтверждёнными требованиями. ArchitectureDesignAgent получает этот результат после решений по блокирующим вопросам и интерпретирует требования как архитектурные предложения. Один агент выполняет несколько вызовов по контрактам операций; LangGraph-узел адаптирует AgentResult к GraphState, но агент не связан с этим состоянием напрямую. Подробная декомпозиция — в [pipeline](agent-pipeline.md).
