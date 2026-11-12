# StructuredOutputGenerator

[Навигация](README.md) · [Роли агентов](agents.md)


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

Смена поддерживаемого провайдера/endpoint требует профиля подключения и capability-smoke, не правок агентов/use cases. Универсальность API не означает одинаковых возможностей всех моделей. [LM Studio](https://lmstudio.ai/docs/developer/openai-compat/structured-output) и [vLLM](https://docs.vllm.ai/en/latest/features/structured_outputs/) описывают JSON Schema, но совместимость конкретной модели, schema subset и версии backend проверяется отдельно. SDK support registry — подсказка, не доказательство для произвольного локального model ID.

Ошибки типизированы: EmptyResponse, IncompleteResponse, InvalidStructuredOutput, UnsupportedSchema, UnsupportedCapability, ContextTooLarge, AuthenticationFailure, TransientTransportFailure, DeadlineExceeded, Cancelled. Refusal — отдельный отказ, не валидная пустая модель. Validation feedback содержит безопасную диагностику полей, не секреты. Retry exhaustion возвращает ошибку/отдельный incomplete draft, не фиктивный успех. Смена модели/провайдера никогда не выполняется молча. Структура не доказывает истинность: затем выполняются domain-валидация и независимый judge.
