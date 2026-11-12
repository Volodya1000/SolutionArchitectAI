# Конфигурация и секреты

[Навигация](README.md) · [Развёртывание](deployment.md) · [Structured output](structured-output.md)

## Один корневой Settings

Единственный `Settings(BaseSettings)` централизованно загружает и валидирует конфигурацию один раз в composition root. Вложенные AppSettings, DatabaseSettings, LLMSettings, RetryConfig, GitSettings и StorageSettings — обычные Pydantic BaseModel, не независимые BaseSettings. Use cases получают только необходимые параметры, Domain не читает Settings, env или файлы.

Один набор параметров имеет одного владельца. Суффикс `Env` используем для групп чувствительных полей из окружения/секретного источника: например, DatabaseEnv содержит пароль, DatabaseSettings — адрес/имя БД/пул. Сами Env также BaseModel. Если секрет один и отдельная группа не улучшает ясность, достаточно SecretStr внутри раздела; не дублируем DSN и его составляющие. Суффикс не защищает данные.

## Файлы и источники

| Файл/источник | Содержимое и политика |
| --- | --- |
| `.env` в корне | Локальная конфигурация разработчика, игнорируется Git |
| `.env.test` в корне | Только безопасные тестовые значения, игнорируется Git; тесты также используют явные overrides |
| `.env.example` в корне | Единственный документированный dotenv-образец с безопасными значениями и пояснениями; никогда не загружается автоматически |
| `config/app.yaml` | Один необязательный несекретный файл: профили/aliases моделей, параметры генерации, RetryConfig, context budget и concurrency |
| Окружение процесса | Адреса БД/LLM/storage, пути Git, режим, разрешённые overrides поведения и секреты |
| Секретный источник платформы | Production password/key; минимальные права, без действующих значений в Git, Dockerfile, build args или образах |

Bootstrap до создания Settings явно выбирает режим и абсолютный config root. Development выбирает `.env`, test — `.env.test` или отсутствие dotenv с overrides, production — `env_file=None`. Файл разработчика в test/CI не читается. Не создаём дополнительные dotenv по компонентам или YAML overlays. Frontend использует относительный `/api`, backend dotenv ему не передаётся; Vite-переменные публичны и не содержат ключей.

## Приоритет загрузки

Для локального MVP: явные init overrides → process env → выбранный dotenv → один YAML → defaults. Раньше переданный source имеет больший приоритет. `SAA_` — префикс, `__` — разделитель вложенных полей. Это политика корневого Settings, а не нескольких загрузчиков.

Ниже небольшой целостный пример будущего контракта; это документация, не реализация конфигурационного модуля. Bootstrap передаёт `_env_file` абсолютным путём или None; YAML-путь ниже задаётся относительно явного рабочего config root.

```python
from pydantic import BaseModel, ConfigDict, Field, SecretStr
from pydantic_settings import BaseSettings, SettingsConfigDict, YamlConfigSettingsSource

class ConfigSection(BaseModel):
    model_config = ConfigDict(extra="forbid")

class RetryConfig(ConfigSection):
    network_retries: int = Field(default=1, ge=0)
    validation_retries: int = Field(default=1, ge=0)
    max_total_requests: int = Field(default=3, ge=1)

class AppSettings(ConfigSection):
    concurrency: int = Field(default=2, ge=1)

class DatabaseEnv(ConfigSection):
    password: SecretStr = Field(repr=False)

class DatabaseSettings(ConfigSection):
    host: str = "localhost"
    database: str = "solution_architect"
    credentials: DatabaseEnv

class LLMSettings(ConfigSection):
    base_url: str = "http://localhost:1234/v1"
    model: str
    api_key: SecretStr | None = Field(default=None, repr=False)
    retry: RetryConfig = Field(default_factory=RetryConfig)

class GitSettings(ConfigSection):
    root: str = "data/git"

class StorageSettings(ConfigSection):
    backend: str = "local"
    root: str = "data/files"

class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_prefix="SAA_", env_nested_delimiter="__", extra="forbid",
        yaml_file="config/app.yaml", hide_input_in_errors=True,
    )
    app: AppSettings = Field(default_factory=AppSettings)
    database: DatabaseSettings
    llm: LLMSettings
    git: GitSettings = Field(default_factory=GitSettings)
    storage: StorageSettings = Field(default_factory=StorageSettings)

    @classmethod
    def settings_customise_sources(cls, settings_cls, init_settings,
                                   env_settings, dotenv_settings, file_secret_settings):
        return (init_settings, env_settings, dotenv_settings,
                YamlConfigSettingsSource(settings_cls))
```

YAML использует те же корневые ключи (`app`, `llm` и т. д.), а не другой namespace. Например, `llm: {model: local-model, retry: {max_total_requests: 3}}`; `SAA_LLM__RETRY__MAX_TOTAL_REQUESTS=4` переопределяет только это поле, остальные поступают из нижних источников. Пароль: `SAA_DATABASE__CREDENTIALS__PASSWORD`. Пример показывает часть RetryConfig; полный контракт ниже обязателен при реализации. Ключи и пароль в YAML запрещены.

Пример использует env для секретов. Если deployment требует mounted secret files, подключается стандартный NestedSecretsSettingsSource с явными вложенными именами и тестом совместимой версии Pydantic Settings, а не самописный универсальный loader. Bootstrap production запрещает init-секреты и dotenv; одновременное определение одного секрета в файле и env — ошибка. Этот дополнительный source имеет приоритет над env. Не объявляем обычный file_secret_settings поддержкой вложенных secret fields без проверки.

Один безопасный YAML loader должен отклонять дубликаты/произвольные tags; неизвестные поля валидируются в каждом выбранном источнике до merge, чтобы override не скрывал опечатки. Предпочитаем стандартные sources и небольшой контроль схемы файла, не универсальную систему конфигураций. Преднамеренно указанный отсутствующий/повреждённый файл останавливает старт; необязательный YAML может отсутствовать. Списки заменяются целиком, вложенные словари объединяются по полям; эти приоритеты и обработка ошибок проверяются integration-тестом на зафиксированной версии библиотеки. Неизвестные системные env игнорируются; допустимые SAA overrides документируются в единственном образце.

## Валидация и защита секретов

При старте проверяются положительные лимиты, URL без credentials/query secrets, роли и aliases моделей, capabilities/параметры, общий token/deadline/retry budget, доступ к DB/Git/files. Health check не вызывает LLM. Init/secret overrides и источник режима выбираются до чтения конфигурации; YAML не может изменить политику собственной загрузки.

SecretStr маскирует стандартный вывод, но не шифрует значение и не защищает произвольный dump. Запрещены секреты в логах, repr, traces, config fingerprints и сообщениях об ошибках; наружу выходит только безопасное резюме/пути полей. Redaction тестируется на validation errors и SDK-ошибках. Реальные ключи не попадают в fixtures и Git. Production secret manager выбирается с платформой; Compose file mounts не являются зашифрованным vault.

Настройки применяются рестартом; run сохраняет несекретный effective config digest. В config fingerprint не входят секреты. Профили LLM и YAML приложения не являются моделью проектируемой архитектуры.

## Профили локальных LLM

LM Studio — локальная разработка/тестирование; vLLM — перспективный inference backend. Базовый Compose приложения не скачивает веса и не запускает inference server. Вызовы идут через `langchain-openai` и `langchain-core` за application-портом; полный `langchain` и LLM proxy не обязательны. Платные провайдеры и расчёты оплаты не входят в проект.

Профиль подключения задаёт base_url, adapter identifier, model identifier и ссылку на необязательный API key. Профиль модели содержит context_window, output_limit, temperature (если поддерживается), request_timeout, RetryConfig, concurrency и capabilities: streaming, JSON schema subset/strictness, JSON-text mode, cancellation semantics, tokenizer/counting strategy. Значения не выводятся только из имени модели. По ролям задаются aliases этих профилей.

Смена LM Studio/vLLM/иного поддерживаемого endpoint — изменение профиля, не кода агента. Настройка формата результата явно выбирает проверенный `json_schema` или разрешённый JSON-текст с Pydantic; запрещены молчаливое удаление schema, fallback на tool calling или смена модели. Capability mismatch даёт typed failure. До реальных испытаний проверяются поддерживаемая схема, пустой/обрезанный ответ, streaming и отмена на каждом endpoint. Поддержка OpenAI-compatible HTTP не доказывает одинаковой поддержки JSON Schema.

## RetryConfig

Типизированная Pydantic-модель входит во вложенный LLMSettings; значения читаются из несекретного YAML и разрешённых env overrides. Это конфигурация приложения, не архитектурная модель.

| Поле | Семантика |
| --- | --- |
| network_retries | Число дополнительных попыток для временной сети/429/разрешённых 5xx; 0 выключает |
| validation_retries | Число дополнительных генераций с безопасным schema feedback; 0 выключает |
| max_total_requests | Общий конечный лимит фактических HTTP-запросов на операцию, включая первую попытку |
| deadline_seconds | Общий бюджет, включая очередь, backoff и все попытки |
| request_timeout_seconds | Лимит одного запроса, не больше остатка deadline |
| backoff_initial / backoff_max / jitter | Ограниченное ожидание, Retry-After учитывается в остатке общего бюджета |
| retryable_errors | Явные классы временных ошибок; auth, forbidden, unknown model/schema/capability, cancellation и истёкший deadline не повторяются |

Числа выбираются по испытаниям, не объявляются требованиями заказчика. Все лимиты конечны; retries неотрицательны, total >= 1, backoff/timeout согласованы. Невалидный ответ не повторяется бесконечно; изменения неподдерживаемой схемы требуют явного решения. После обрезки нельзя молча превысить output limit. Смена модели запрещена без явной команды.

Единственный координатор повторов структурированной генерации — `StructuredOutputGenerator` поверх LangChain/Pydantic. Он ведёт отдельные счётчики классов ошибок и общий request/deadline budget, включая повторную генерацию после Pydantic-ошибки. Встроенные `ChatOpenAI(max_retries=0)`/SDK retries и LangGraph retry policy для LLM-узла не создают независимых циклов; contract test проверяет, что ноль наших повторов означает один HTTP-запрос. При возобновлении run сохраняется остаток общего бюджета. Для обычного streaming транспорт использует тот же бюджет; после уже выданных токенов прозрачный replay запрещён. Смена класса ошибки не сбрасывает общий счётчик.

Интеграционный тест считает исходящие запросы при последовательности network error → invalid JSON → success, при обоих retries=0, исчерпании бюджета и отмене во время backoff. Генерация не охватывает применение или Git commit. После HTTP disconnect запросить operation_id безопаснее, чем запускать всю команду заново.
