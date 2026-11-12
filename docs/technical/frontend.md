# Frontend и рабочее место архитектора

[Навигация](README.md) · [Агенты](agents.md) · [Проверки](quality-and-testing.md#frontend)

## Стек и центр интерфейса

Отдельное React + TypeScript strict + Vite SPA, React Router для адресуемых пространства/задачи/вида/редакции, TanStack Query для серверного состояния. SSR не требуется; FastAPI владеет правилами, LLM и хранилищами. Open WebUI — возможный референс, не платформа и не схема сообщений. Stream Chat с обязательным hosted backend не подходит.

Центральный объект — общая архитектурная модель и дерево представлений. Рядом доступен чат, основной способ общения с ИИ. Рабочее место позволяет найти компонент, открыть свойства/отношения, список использующих его видов, связанные требования/решения, историю и diff. Задача выбирает ветку, но не создаёт отдельную архитектуру. Представления — ссылки на общие ID, не набор независимых SVG. Полный drag-and-drop редактор уровня Archi вне первого MVP.

## Готовый чат: исследование 11 ноября 2026

Это оценка официальной документации, без установки и интеграционного прототипа. У всех кандидатов FastAPI/PostgreSQL остаются нашими: UI-библиотека сама не сохраняет историю в нашей БД. «Поддержка» ниже означает API/компоненты и требуемый адаптер, а не готовый backend.

| Критерий | assistant-ui | MUI X Chat | shadcn/ui AI Elements |
| --- | --- | --- | --- |
| React/Vite | React primitives/runtime, без обязательного Next.js | React/MUI; Vite совместим | Копируемые React-компоненты; есть Vite setup; chatbot template на Next.js не обязателен |
| FastAPI, без cloud | LocalRuntime/ChatModelAdapter или ExternalStoreRuntime; Assistant Cloud опционален | Свой backend adapter/ReadableStream | Свой transport/state; AI SDK template — пример, не обязательный облачный сервис |
| Streaming | Async stream адаптера, runtime состояния | Потоковый processor и adapter | Message Scroller/Message показывают обновления; transport подключаем сами |
| История PostgreSQL | HistoryAdapter и remote thread list через наш API | История/идентификаторы через свой backend adapter | Load/save и управление состоянием реализуем сами |
| Несколько чатов | RemoteThreadListAdapter, thread runtime | Multi-conversation/thread switching | Навигация и список чатов собственные |
| Вложения | AttachmentAdapter плюс наш immutable file API | Документированы message parts/attachments; upload adapter свой | Attachment/Input components; upload и связывание с сообщением свои |
| Отмена | AbortSignal/cancel runtime; API отмены run нужен отдельно | Cancellation contract адаптера; остановка server run наша | Abort transport и lifecycle реализуем сами |
| Кастомные сообщения | Custom components/data parts; карточки вопросов и proposals | Slots/parts, custom renderer | Полный контроль копируемого кода |
| Вопросы/предложения | Наши typed части ClarificationSet/ChangeProposal, кнопки use cases | Наши parts/slots и команды принятия | Свои карточки и event mapping |
| Light/Dark/System | Primitives стилизуем общей темой; не отдельная несогласованная палитра | Встроенная MUI theme integration | Общий Vite ThemeProvider/CSS tokens |
| Лицензия | MIT для open-source core; hosted-продукты отдельно | Документация Chat указывает MIT Community; не переносить лицензию Pro DataGrid на Chat | MIT исходников shadcn/ui; проверяем лицензии выбранных зависимостей |
| API и зрелость | Специализированный runtime с адаптерами; встречаются unstable API, pin и contract tests обязательны | Страница overview показывает **v9.0.0-alpha.21**, early development/Chat Preview; обещанный срок stable не доказательство выпуска | AI Elements переносится в shadcn/ui; старый registry объявлен к deprecation в конце ноября 2026; код сопровождать нам |
| Наш код интеграции | Средний: stream, history, threads, uploads и domain cards; меньше собственной механики чата | Средний при выборе MUI, плюс риск миграций alpha | Наибольший: композиция UI проста, lifecycle/history/concurrency в основном наши |

Источники: [assistant-ui LocalRuntime](https://www.assistant-ui.com/docs/runtimes/custom/local-runtime), [adapters](https://www.assistant-ui.com/docs/runtimes/concepts/adapters), [threads](https://www.assistant-ui.com/docs/runtimes/concepts/threads), [MIT](https://github.com/assistant-ui/assistant-ui/blob/main/LICENSE); [MUI overview](https://mui.com/x/react-chat/overview/), [alpha announcement](https://mui.com/blog/introducing-mui-x-chat-v9-alpha/); [shadcn Chat](https://ui.shadcn.com/docs/ai-elements/base/chat), [AI Elements](https://ui.shadcn.com/docs/ai-elements), [migration notice](https://elements.ai-sdk.dev/), [MIT](https://github.com/shadcn-ui/ui/blob/main/LICENSE.md).

**Рекомендация — assistant-ui с собственным FastAPI transport и persistence adapters.** Он закрывает больше типового lifecycle, не требует облачного чата и оставляет domain UI нашему приложению. MUI X Chat сейчас не рекомендуем для основы MVP из-за подтверждённой alpha, даже при выборе Material UI. shadcn AI Elements — подходящая альтернатива для полностью собственного UI, но требует больше интеграционного кода и учёта текущего переноса. Сравнение не является benchmark; перед pin версии первый вертикальный сценарий проверяет cancel/reconnect/history/attachments.

Общая UI-библиотека остаётся **рекомендацией**: бесплатный Material UI core удобен для таблиц/форм; shadcn/ui + Tailwind лучше сочетается с готовой стилизацией assistant-ui. При выборе MUI используем стилизуемые assistant-ui primitives, избегаем двух независимых reset/theme систем. Окончательный корпоративный выбор не объявлен. Redux не нужен: Query хранит серверное состояние, React — локальное.

## Чат и команды

Несколько чатов привязываются к задаче либо пространству. Сообщения имеют устойчивые IDs и typed parts: text, file reference, clarification, proposal, review, run status/error. PostgreSQL — авторитет истории. Streaming текст не превращается в подтверждённую архитектуру. UI показывает queued/running/waiting_input/cancelling/cancelled/failed/completed и incomplete output; сервер подтверждает окончательную отмену.

SSE/fetch-stream использует run_id и event sequence, reconnect загружает сохранённый статус/сообщение без второй генерации. Остановка чтения потока и отмена server run — разные действия. Переключение чата не перемешивает потоки. Вложения идут через file API, с типом, размером, доступом и immutable version; ошибки upload не маскируются успешным сообщением.

Карточка вопроса показывает blocking и основание; ответ отправляет AnswerClarification. Карточка proposal показывает diff, источники, затронутые общие объекты/виды, формальные нарушения и замечания judge; принять/отклонить — application-команды. Свободное «согласен» не скрытый approval. Для подтверждения пользователь видит точную ревизию/область. Несохранённый ввод сохраняется при обновлении server state.

Mutation применения передаёт expected_commit/operation_id. Запись не обновляется оптимистически; при потере ответа запрашивается статус операции. Query retry для mutating commands выключен; повтор той же команды идемпотентен на сервере. Cache keys включают workspace/task/revision/run; late response другого чата не заменяет текущий. Raw HTML из Markdown и активный SVG не исполняются.

## Светлая и тёмная темы — MVP

Обязательны **Light / Dark / System**, ручное переключение и восстановление выбора. System реагирует на prefers-color-scheme; явный Light/Dark имеет приоритет. Предпочтение сохраняется локально и в пользовательских настройках PostgreSQL; при старте локальный выбор применяется до загрузки профиля, затем действует сохранённый выбор пользователя с явной политикой синхронизации.

Если выбран MUI: [ThemeProvider, colorSchemes, useColorScheme и CSS variables](https://mui.com/material-ui/customization/dark-mode/) предоставляют основу и storage manager; дополнительный theme framework не нужен. Если shadcn/ui: [ThemeProvider для Vite](https://ui.shadcn.com/docs/dark-mode/vite), localStorage и CSS variables. Не добавляем next-themes в Vite лишь потому, что он встречается в Next.js примере.

Общие tokens применяются к чату, таблицам, дереву, диалогам, карточкам, diff, Markdown/code blocks и замечаниям. Диаграммы получают собственные проверенные палитры background/text/line/fill в обеих темах; если SVG экспортируется только для светлого режима, показывается на явно светлой canvas с читаемой рамкой, а не на прозрачном чёрном фоне. Не используем CSS invert: он меняет смысл цветов. Смена темы не меняет предметную модель/layout; theme-specific SVG остаётся производным экспортом той же ревизии.

## Читаемость и структура

Архитектор работает часами: приоритет читаемым шрифтам, умеренной плотности, контрасту и отсутствию визуального шума. Длинные таблицы имеют закреплённую шапку/локальный scroll, дерево — поиск и клавиатуру, диаграмма — zoom/pan и доступную табличную альтернативу. Статусы различаются текстом, не одним цветом. Подробные объяснения/источники раскрываются по запросу; основной экран выделяет сомнительные предложения ИИ, особенно конфликтующие с решениями человека, без баллов на каждом элементе.

Рекомендуем WCAG 2.2 AA как цель проверки доступности, не уже полученную сертификацию. Focus, labels, контраст, 200% zoom, screen reader и длинные русские тексты проверяются в обеих темах; live announcements streaming дозированы. Узкий экран использует вкладки с сохранением ввода. Git diff показывает JSON/.puml с понятными названиями объектов; JSON не обычный редактор архитектуры.

Предлагаемая структура: `app/` (router/providers/theme), `pages/` (композиция), `features/` (workspace-tree, object-details, tasks, chat, proposals, verification, artifacts, history), `shared/api` и `shared/ui`. Shared не импортирует features/pages; нет циклических barrel exports. OpenAPI-типы можно генерировать, но они не заменяют runtime server validation.

## Графическое редактирование и review MVP

Основной рабочий инструмент архитектора — интерактивное графическое представление общей модели. MVP поддерживает выбор узла/отношения, изменение свойств общего объекта, добавление/изменение разрешённого отношения, переход к связанному виду и поиск всех представлений объекта. Изменение layout локально виду. Изменение семантики идёт через предметную команду, проверки и решение человека, с анализом влияния на другие виды.

Предложение ИИ показывается в контексте затронутых объектов и diff; доступны применить/отклонить/вернуть на уточнение. Сравнение показывает добавление, изменение и удаление объектов/связей с основаниями, а не только текст сериализации. Интерфейс выделяет доказанное нарушение, конфликт с решением человека, недостающие обязательные данные и сомнительное предложение; подробности раскрываются. Контроль качества, происхождение и human approval независимы.

Конкретная React-библиотека графа выбирается коротким испытанием в шаге общей модели: select/edit edge, where-used, два независимых layout, русские подписи, темы и diff. Это выбор frontend, не замена ArchiMate на UML. MVP ограничен согласованным профилем нотации и основными операциями; полный набор возможностей редактора Archi не обещается.
