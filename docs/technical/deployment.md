# Развёртывание и сохранность

[Навигация](README.md) · [Конфигурация](configuration.md) · [Протокол хранения](backend.md)

## Минимальная поставка

Docker Compose включает отдельные frontend и backend, PostgreSQL и сохраняемые тома. Local filesystem — первая реализация файлового порта; S3-compatible endpoint выбирается конфигурацией. MinIO возможен отдельным profile для проверки S3, но не обязательная корпоративная зависимость. Git CLI планируется внутри backend-образа; **PlantUML Server — отдельный локальный контейнер** с Java/Graphviz. Веса и inference server в базовый Compose не входят.

| Ресурс | Назначение | Сохранность |
| --- | --- | --- |
| Frontend | Vite dev server или Nginx со статической SPA | Без предметных данных и секретов |
| Backend | FastAPI, управляемые runs и адаптеры; рендеринг через внутренний HTTP | Один worker в MVP; temp отдельно от durable data |
| PostgreSQL | Операционное состояние, сообщения, runs, journal и checkpoints графа | Отдельный volume, Alembic migrations |
| PlantUML Server | Локальная генерация SVG, доступ только backend | Без предметных данных, временный каталог и лимиты ресурсов |
| Git volume | Один общий архитектурный repo на пространство | Все refs/objects и незавершённые staging операции |
| File storage | Immutable документы и вложения | Local volume либо S3 с политикой удержания версий |

Redis, task broker, Kubernetes, vector database и LangGraph не нужны для первого сценария чата. LangGraph и PostgreSQL checkpointer добавляются с первым агентным сценарием ожидания ответа человека. Kafka и 2FA из примера — свойства проектируемой системы, не сервисы помощника. PostgreSQL помощника при этом обязателен.

## Сеть и локальная разработка

Браузер обращается к относительному `/api`; Vite proxy/Nginx маршрутизирует запросы backend через Compose DNS. Deep links SPA возвращают index.html, API errors сохраняют собственные статус/JSON. SSE требует отключить buffering и согласовать proxy idle timeout; отмена server run — отдельный API. Backend не передаёт ключи в браузер. Для отдельного dev frontend задаётся конкретный CORS origin, не wildcard с credentials.

Локальная разработка использует bind mounts кода и hot reload; поставляемые образы — immutable multi-stage images, статический frontend без Node runtime, backend без dev tools/reload. Версии и lock-файлы фиксируются при реализации. Порты локальной разработки публикуются на loopback. Удалённая эксплуатация требует отдельно согласованных auth/access/data правил; этот документ их не утверждает.

Dishka lifespan закрывает clients/pools/tasks. Alembic migrations и первый `AsyncPostgresSaver.setup()` выполняются до readiness управляемой инициализацией, а не конкурентно каждым worker. [Compose service_healthy](https://docs.docker.com/compose/how-tos/startup-order/) задаёт ожидание PostgreSQL; сам порядок старта готовности не гарантирует. Readiness проверяет schema version, DB/Git/file access и pending recovery. Liveness проверяет процесс; LLM availability показывается отдельно degraded, не скрывает историю. Health check не запускает генерацию/JVM каждый раз.

## Будущий production в Red Hat OpenShift

Решение заказчика: локально разработчик запускает **Docker Compose**, в будущем production запускается в **Red Hat OpenShift**. Compose не переносится в кластер как production-механизм. Используются контейнерные образы компонентов и платформенное управление сервисами; manifests/Helm и новая инфраструктура этим PR не создаются.

При реализации учитываются [рекомендации Red Hat по образам](https://docs.redhat.com/en/documentation/openshift_container_platform/4.20/html/images/creating-images):

- Непривилегированный пользователь и потенциально произвольный UID; writable data/temp с корректными group permissions, без обязательного root, фиксированного домашнего каталога или записи в слои образа. Права и volume policy проверяются в целевом кластере; root/init chown не считаются универсальным решением.
- Конфигурация через разрешённые env, ConfigMap/Secrets и secret files по [единому приоритету Settings](configuration.md#приоритет-загрузки); секреты не входят в frontend bundle/images. Пути задаются конфигурацией, без привязки к диску конкретного узла.
- PostgreSQL и файловые данные — внешние сервисы либо подходящие persistent volumes; local files MVP не означают ephemeral filesystem production. S3-порт позволяет сменить реализацию без изменения предметной модели.
- Сервисные DNS/внутренние порты, контролируемый ingress/API и сетевые политики. LLM и PlantUML доступны backend; браузер напрямую к ним не обращается. SSE/proxy timeouts сохраняются.
- Раздельные readiness/liveness, ресурсы CPU/RAM, корректный shutdown. Alembic и инициализация checkpointer выполняются отдельным управляемым шагом до readiness, а не каждым replica при старте.
- PlantUML/JVM/Graphviz проверяются под произвольным UID: доступный temp/font cache, кириллица/шрифты, headless Java, memory/CPU/process limits и отсутствие привилегированных портов. Официальный Docker-образ не считается автоматически совместимым с ограничениями OpenShift; при необходимости адаптируется образ, а не ослабляются политики кластера.

### Git-репозитории архитектурных моделей

Локально один backend worker использует постоянный Git volume; сохраняются все refs/objects и данные восстановления. В OpenShift Git не хранится в ephemeral слое pod или hostPath конкретного узла. Первое направление — persistent volume с явным единственным владельцем записи и проверенными блокировками/атомарностью файловых операций, резервированием и восстановлением после пересоздания pod. Это ограничивает горизонтальное масштабирование записей, а не обещает готовую многорепличную схему.

Перед масштабированием необходимо выбрать доступность и режим доступа хранилища, координацию writers, поведение Git ref updates при сбоях и backup согласованно с PostgreSQL/files. Общий RWX volume сам по себе не решает конкуренцию, а обычное S3 не является POSIX Git working directory. Сейчас не выбирается новая Git-платформа или распределённая файловая система: решение принимается по требованиям доступности/масштаба целевого кластера с сохранением принятого Git workflow.

## Локальный PlantUML: выбор способа выполнения

Проверены [официальный PlantUML Server и Docker-запуск](https://github.com/plantuml/plantuml-server), [HTTP/SVG API](https://plantuml.com/server), [CLI](https://plantuml.com/command-line), [профили безопасности](https://plantuml.com/security), [ArchiMate](https://plantuml.com/archimate-diagram) и [stdlib](https://plantuml.com/stdlib), 12 ноября 2026 года.

| Критерий | Отдельный PlantUML Server | CLI внутри backend или управляемого процесса |
| --- | --- | --- |
| Сопровождение | Один дополнительный сервис; версии JAR/Java/Graphviz/шрифтов закреплены в образе рендерера | Нет HTTP-сервиса, но Java/Graphviz и обновления входят в backend-образ либо нужен собственный управляющий процесс |
| Изоляция | Отдельные CPU/RAM/temp, сбой JVM отделён от API | CLI в backend делит лимиты/файлы; subprocess не является контейнерной границей. Изоляция отдельным worker потребует своей инфраструктуры |
| Сеть и доступ | Внутренний HTTP только от backend, без публикации наружу; сетевые и renderer policies | HTTP не нужен; subprocess со списком аргументов без shell, надзор/timeout/concurrency реализует backend |
| Ресурсы | Постоянная JVM использует память, избегает её старта на каждый render | JVM на каждый вызов проще, но дороже на серии запросов; долгоживущий CLI-процесс требует управления |
| OpenShift | Независимые лимиты и UID/temp checks рендерера; образ надо проверить/адаптировать | Более тяжёлый backend, проверки arbitrary UID и Java выполняются вместе; отдельный процесс не устраняет их |
| Возможности | Версия PlantUML/Graphviz/stdlib определяет ArchiMate и SVG | Та же версия движка может дать те же возможности; HTTP не расширяет нотацию |

**Выбран отдельный PlantUML Server** как сервис основного локального Compose: цена одного внутреннего HTTP endpoint оправдана изоляцией JVM, ресурсами и независимым сопровождением. Backend вызывает его через rendering adapter; он не доступен браузеру и не хранит предметную модель. CLI остаётся альтернативой для пакетной генерации доверенной документации и не является основным runtime MVP. Эта PDF-сборка использует сохранённые SVG и не требует runtime-сервиса.

Безопасный план: backend формирует экранированную проекцию **проверенной предметной модели** по контролируемым шаблонам; непроверенный LLM `.puml` напрямую не рендерится. Запрещаются произвольные препроцессорные директивы, URL/file includes и пользовательские ссылки/ресурсы. Основной профиль — `SANDBOX` (без доступа к URL/файлам); необходимые определения ArchiMate поставляются с закреплённой stdlib, а доверенные шаблонные определения при необходимости разворачиваются до отправки, без открытия произвольных includes. Совместимость ArchiMate/шрифтов/Graphviz с этим профилем проверяется до поставки; fallback в LEGACY/UNSECURE/INTERNET недопустим. Если действительно потребуется file include, это отдельное узкое решение ALLOWLIST с единственным read-only каталогом доверенных шаблонов и без URL allowlist, не автоматическое ослабление.

Ограничиваются размер/сложность входа, время и число параллельных render, Java heap и CPU/RAM контейнера. Рендерер не получает Git/files/secrets volumes; исходящий сетевой доступ запрещается сетевой политикой среды. В Compose отсутствие published port ограничивает вход, но само по себе не запрещает исходящий трафик: изолированная внутренняя сеть рендерера и SANDBOX проверяются отдельно. Только backend в разрешённой сети вызывает renderer; в OpenShift доступ дополнительно ограничивается NetworkPolicy. Таймаут HTTP не гарантирует остановку работы JVM: требуются ограничения самого рендеринга. SVG фильтруется от активного содержимого и показывается как изображение с ограниченным content policy. Исходники не попадают во внешние публичные сервисы или журналы URL.

PlantUML воспроизводит публикуемую схему по конкретной редакции модели и закреплённой версии шаблонов/движка/шрифтов; это не замена модели или интерактивного layout React Flow. Будущий ArchiMate XML-обмен строится по модели. Наличие ArchiMate-синтаксиса PlantUML не доказывает полное покрытие стандарта или готовый импорт Archi.

## Локальные модели

Backend использует настроенный OpenAI-compatible endpoint LM Studio или vLLM через `langchain-openai` (`ChatOpenAI`, явно настроенный `base_url`). `localhost` внутри контейнера — сам контейнер: для host endpoint нужен явно настроенный host gateway/DNS; для удалённого endpoint — доступная сеть и TLS по политике окружения. Автоматическая отправка данных другому провайдеру запрещена. Fake LLM позволяет запустить обычный CI без inference server, реальная модель проходит отдельный capability/quality smoke.

## Конфигурация и ограничения адаптеров

Приоритет источников — только по [configuration.md](configuration.md#приоритет-загрузки). Compose `.env` выполняет интерполяцию и сам не передаёт всё окружение backend. Development env_file и собственный dotenv loader не включаются одновременно неявно. Локальный Compose использует явный YAML/разрешённые env и [secret mounts](https://docs.docker.com/compose/how-tos/use-secrets/); OpenShift — конфигурацию и секреты платформы; frontend не получает backend dotenv. Source и секреты не копируются в images.

Backend непривилегирован, пишет в data/temp. Git CLI получает список аргументов без shell, server-generated branch/path names и отключённые сторонние hooks. PlantUML получает сгенерированные экранированные проекции, не произвольный LLM `.puml`. [Security profile](https://plantuml.com/security) запрещает сетевые includes, локальная ArchiMate-библиотека поставляется вместе с рендерером; совместимость проверяется, автоматического ослабления до LEGACY нет. SVG показан как изображение с ограниченным content policy.

## Recovery и резервирование

Shutdown останавливает приём новых runs, завершает короткую CAS-публикацию или оставляет journal для recovery, отменяет LLM/рендер с cleanup и конечным grace period, закрывает SQL/HTTP ресурсы. Interrupted run не объявляется completed. Recovery сопоставляет journal, refs/operation_id и immutable file versions; неопределённость блокирует запись. Протокол не обещает распределённую транзакцию.

Backup охватывает PostgreSQL, весь Git repo и retained file versions с согласованным checkpoint/manifest. Один Git — не backup диска. Для минимального согласованного backup приостанавливаем записи/GC, выполняем DB dump и snapshot Git/files, записываем hashes и журнал, затем возобновляем. Restore на отдельном окружении проверяет ссылки на источники и незавершённые операции, а не только запуск контейнеров. Секреты резервируются отдельно, traces имеют доступ как исходники.

RPO/RTO, сроки хранения, права удаления, удалённый доступ и параметры выбранной production-платформы OpenShift остаются открытыми. N-02 системы отчётности не переносится на помощника. Никакого допуска реальных закрытых данных из успешного синтетического smoke не следует. Compose/Dockerfile появятся при реализации, в этом PR их нет.
