# Развёртывание и сохранность

[Навигация](README.md) · [Конфигурация](configuration.md) · [Протокол хранения](backend.md)

## Минимальная поставка

Docker Compose включает отдельные frontend и backend, PostgreSQL и сохраняемые тома. Local filesystem — первая реализация файлового порта; S3-compatible endpoint выбирается конфигурацией. MinIO возможен отдельным profile для проверки S3, но не обязательная корпоративная зависимость. Git и локальный PlantUML/Java/Graphviz можно поставлять внутри backend образа. Веса и inference server в базовый Compose не входят.

| Ресурс | Назначение | Сохранность |
| --- | --- | --- |
| Frontend | Vite dev server или Nginx со статической SPA | Без предметных данных и секретов |
| Backend | FastAPI, управляемые runs, адаптеры и рендеринг | Один worker в MVP; temp отдельно от durable data |
| PostgreSQL | Операционное состояние, сообщения, runs, journal и checkpoints графа | Отдельный volume, Alembic migrations |
| Git volume | Один общий архитектурный repo на пространство | Все refs/objects и незавершённые staging операции |
| File storage | Immutable документы и вложения | Local volume либо S3 с политикой удержания версий |

Redis, task broker, Kubernetes, vector database и LangGraph не нужны для первого сценария чата. LangGraph и PostgreSQL checkpointer добавляются с первым агентным сценарием ожидания ответа человека. Kafka и 2FA из примера — свойства проектируемой системы, не сервисы помощника. PostgreSQL помощника при этом обязателен.

## Сеть, development и production

Браузер обращается к относительному `/api`; Vite proxy/Nginx маршрутизирует запросы backend через Compose DNS. Deep links SPA возвращают index.html, API errors сохраняют собственные статус/JSON. SSE требует отключить buffering и согласовать proxy idle timeout; отмена server run — отдельный API. Backend не передаёт ключи в браузер. Для отдельного dev frontend задаётся конкретный CORS origin, не wildcard с credentials.

Development использует bind mounts кода и hot reload; production — immutable multi-stage images, Nginx static frontend без Node runtime, backend без dev tools/reload. Версии и lock-файлы фиксируются при реализации. Порты локальной разработки публикуются на loopback. Удалённая эксплуатация требует отдельно согласованных auth/access/data правил; этот документ их не утверждает.

Dishka lifespan закрывает clients/pools/tasks. Alembic migrations и первый `AsyncPostgresSaver.setup()` выполняются до readiness управляемой инициализацией, а не конкурентно каждым worker. [Compose service_healthy](https://docs.docker.com/compose/how-tos/startup-order/) задаёт ожидание PostgreSQL; сам порядок старта готовности не гарантирует. Readiness проверяет schema version, DB/Git/file access и pending recovery. Liveness проверяет процесс; LLM availability показывается отдельно degraded, не скрывает историю. Health check не запускает генерацию/JVM каждый раз.

## Локальные модели

Backend использует настроенный OpenAI-compatible endpoint LM Studio или vLLM через `langchain-openai` (`ChatOpenAI`, явно настроенный `base_url`). `localhost` внутри контейнера — сам контейнер: для host endpoint нужен явно настроенный host gateway/DNS; для удалённого endpoint — доступная сеть и TLS по политике окружения. Автоматическая отправка данных другому провайдеру запрещена. Fake LLM позволяет запустить обычный CI без inference server, реальная модель проходит отдельный capability/quality smoke.

## Конфигурация и ограничения адаптеров

Приоритет источников — только по [configuration.md](configuration.md#приоритет-загрузки). Compose `.env` выполняет интерполяцию и сам не передаёт всё окружение backend. Development env_file и собственный dotenv loader не включаются одновременно неявно. Production использует явный YAML/разрешённые env и [secret mounts](https://docs.docker.com/compose/how-tos/use-secrets/); frontend не получает backend dotenv. Source и секреты не копируются в images.

Backend непривилегирован, пишет в data/temp. Git CLI получает список аргументов без shell, server-generated branch/path names и отключённые сторонние hooks. PlantUML получает сгенерированные экранированные проекции, не произвольный LLM `.puml`. [Security profile](https://plantuml.com/security) запрещает сетевые includes, локальная ArchiMate-библиотека поставляется вместе с рендерером; совместимость проверяется, автоматического ослабления до LEGACY нет. SVG показан как изображение с ограниченным content policy.

## Recovery и резервирование

Shutdown останавливает приём новых runs, завершает короткую CAS-публикацию или оставляет journal для recovery, отменяет LLM/рендер с cleanup и конечным grace period, закрывает SQL/HTTP ресурсы. Interrupted run не объявляется completed. Recovery сопоставляет journal, refs/operation_id и immutable file versions; неопределённость блокирует запись. Протокол не обещает распределённую транзакцию.

Backup охватывает PostgreSQL, весь Git repo и retained file versions с согласованным checkpoint/manifest. Один Git — не backup диска. Для минимального согласованного backup приостанавливаем записи/GC, выполняем DB dump и snapshot Git/files, записываем hashes и журнал, затем возобновляем. Restore на отдельном окружении проверяет ссылки на источники и незавершённые операции, а не только запуск контейнеров. Секреты резервируются отдельно, traces имеют доступ как исходники.

RPO/RTO, сроки хранения, права удаления, удалённый доступ и конкретная корпоративная платформа остаются открытыми. N-02 системы отчётности не переносится на помощника. Никакого допуска реальных закрытых данных из успешного синтетического smoke не следует. Compose/Dockerfile появятся при реализации, в этом PR их нет.
