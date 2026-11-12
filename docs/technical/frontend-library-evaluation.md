# Выбор frontend-библиотек MVP

[Навигация](README.md) · [Рабочее место](frontend.md)

Проверено **12 ноября 2026 года** по официальным руководствам, лицензиям и npm metadata. Это выбор для реализации, не отчёт об интеграционном испытании. Критерии: React/TypeScript/Vite SPA с собственным FastAPI, отсутствие обязательного облака, требуемая интерактивность, общие темы, доступность, стоимость сопровождения и лицензии.

## Решение и альтернативы

| Область | Выбранный вариант и причина | Существенная альтернатива и ограничение |
| --- | --- | --- |
| Маршрутизация | React Router, Declarative mode: вложенные маршруты и URL пространства/задачи/вида; данные остаются в Query | TanStack Router даёт более строгую типизацию маршрутов, но не устраняет адаптер FastAPI и вводит другую систему маршрутов без необходимой MVP функции |
| Серверные данные | TanStack Query: кеш, invalidation, состояния запросов и мутаций | SWR проще для чтения; Query удобнее для нескольких связанных сущностей, мутаций и обновления после принятия proposals. Redux Toolkit Query оправдан при уже принятом Redux, которого здесь нет |
| UI и стили | shadcn/ui + Tailwind CSS: изменяемые исходники компонентов, общие CSS tokens, согласованность с assistant-ui | Material UI core (MIT) даёт готовую систему форм/тем, но её совмещение с выбранным чатом создаёт вторую систему оформления. Не требуется MUI X Pro/Premium |
| Чат | assistant-ui: специализированные primitives/runtime, streaming и адаптеры своего backend | MUI X Chat на дату проверки всё ещё Preview/alpha. shadcn AI Elements подходит для собственных сообщений, но оставляет больше работы по состоянию/истории/отмене; перенос registry увеличивает стоимость обновлений |
| Диаграммы | React Flow: React-компоненты узлов, controlled nodes/edges, выбор, drag, соединения, zoom/pan | Только SVG PlantUML не даёт редактор; Cytoscape.js (MIT) ориентирован также на анализ графов, но формы React внутри узлов требуют дополнительной интеграции; JointJS core — MPL-2.0, расширения JointJS+ коммерческие, преимуществ для нашего ограниченного редактора недостаточно |

React Router применяется без framework/server режима и собственного второго кеша загрузчиков. TanStack Query не является транспортом SSE и не выполняет агентный процесс. assistant-ui подключается через **ExternalStoreRuntime** к состоянию сообщений нашего API; единый адаптер отвечает за streaming, восстановление истории, переключение чатов, загрузку вложений и отмену server run. Assistant Cloud, LangGraph Cloud и Vercel backend не требуются. Не подключаем одновременно альтернативные chat runtimes.

## React Flow: границы ответственности

| Требование | Что предоставляет React Flow | Что реализует SolutionArchitectAI |
| --- | --- | --- |
| Выбор объекта/связи | Selection и события узлов/рёбер | Сопоставление с предметным ID, панель свойств и проверка прав |
| Изменение свойств | Custom React nodes и controlled updates | Формы, предметные команды, валидация backend; React Flow не знает ArchiMate |
| Работа со связями | Handles, создание/reconnect, custom edges, проверка соединения в UI | Разрешённые типы/направления, семантика и окончательная проверка на сервере |
| Перемещение и масштаб | Drag, позиции, viewport, группы | Сохранение расположения/масштаба и отмена несохранённых правок |
| Несколько представлений | Отображение переданного набора nodes/edges | Отбор общих объектов, where-used, отдельные view ID и layout каждого вида |
| Предложения ИИ | Стили и свои узлы/рёбра для подсветки | Семантический diff, основания, принять/отклонить/уточнить и защита от устаревшей ревизии |

**Четыре разных уровня:** Python Domain Model хранит общие объекты/отношения с устойчивыми ID; React Flow показывает интерактивную проекцию; PlantUML генерирует воспроизводимые схемы; будущий адаптер ArchiMate Model Exchange XML выполняет обмен с Archi. ID экземпляра узла в виде отличается от ID общего объекта. Расположение, локальная подпись и viewport сохраняются с видом, не в свойствах общего объекта. Изменение узла преобразуется в команду над предметным ID; удаление с вида не удаляет объект.

Внутренний JSON React Flow не становится форматом Git-модели или XML-обмена. Потребуются отображение предметных типов на графические, сохранение views, схема преобразования поддерживаемого профиля ArchiMate и отдельные round-trip тесты будущего XML-адаптера. React Flow не импортирует/экспортирует модели Archi автоматически. Нотация и инварианты остаются независимыми; полный редактор Archi не входит в MVP.

SVG поддерживает масштабирование и ссылки на объекты: этого достаточно для просмотра/экспорта. Для изменения свойств с SVG можно добавить отдельную панель, но создание/перенос связей, drag элементов и независимый layout пришлось бы реализовать поверх SVG самостоятельно. Повторная генерация PlantUML не сохраняет автоматически ручное размещение каждого вида. Поэтому **React Flow выбран для обязательной интерактивности MVP**, а SVG остаётся производным документом, без обещания пиксельного совпадения двух рендереров. Автоматическая раскладка не встроена универсально; новый layout engine сейчас не добавляется.

## Совместимость и сопровождение

Снимок npm `latest` на дату проверки: React/React DOM 19.3.1, React Router 8.5.1, TanStack Query 5.107.1, Tailwind CSS 4.3.5, assistant-ui 0.15.36, React Flow 12.12.1, Vite 8.3.8, TypeScript 7.0.2, shadcn CLI 4.23.0. Это наблюдаемые версии, не lock-файл приложения. Источники metadata: [React](https://registry.npmjs.org/react/latest), [Router](https://registry.npmjs.org/react-router/latest), [Query](https://registry.npmjs.org/@tanstack/react-query/latest), [assistant-ui](https://registry.npmjs.org/@assistant-ui/react/latest), [React Flow](https://registry.npmjs.org/@xyflow/react/latest), [Vite](https://registry.npmjs.org/vite/latest).

Заявленные peer ranges Router требуют React/DOM >=19.2.7; Query и assistant-ui допускают React 18/19; React Flow — >=17. Общий вариант React 19.3.1 удовлетворяет этим диапазонам. Router требует Node >=22.22.0, Vite — ^20.19.0 или >=22.12.0: для сборки планируется Node 24 LTS. Совместимость типов, плагинов и конкретных скопированных shadcn-компонентов проверяется вместе при создании lock-файла; metadata не доказывают совместную работу. Tailwind v4 рассчитан на современные браузеры (Safari 16.4+, Chrome 111+, Firefox 128+); поддержку более старых корпоративных браузеров нельзя обещать без отдельного решения.

shadcn — исходники в нашем проекте, а не обновляемый монолитный runtime. Команда выбирает небольшой набор компонентов, сохраняет лицензии, проверяет изменения upstream и их доступность. Общие CSS tokens и Vite ThemeProvider обслуживают Light/Dark/System, assistant-ui и React Flow; CSS графа импортируется отдельно, классы Tailwind не формируются произвольной конкатенацией. Не нужен Next.js или `next-themes`.

assistant-ui остаётся pre-1.0 и содержит развивающиеся API: используем документированные адаптеры, фиксируем версии и проверяем контракт на обновлении. Для графа нужны тесты длинных русских подписей, двух видов одного объекта, независимых layout, тем, клавиатуры и сохранения. Для чата — streaming/cancel/reconnect, история, вложения и отсутствие смешивания потоков. Окончательный lock и эти интеграционные проверки появятся при реализации, **выбор библиотек уже сделан**.

## Лицензии

React, Vite, React Router, TanStack Query, shadcn/ui, Tailwind CSS, assistant-ui core и React Flow core распространяются под MIT; TypeScript — Apache-2.0. Коммерческое применение core не требует подписки при соблюдении лицензий и сохранении уведомлений. React Flow Pro продаёт дополнительные примеры/поддержку; обязательные операции MVP не требуют Pro. Assistant Cloud и Tailwind Plus — отдельные коммерческие продукты, не зависимости MVP. Лицензии и notices конкретных компонентов, иконок и транзитивных пакетов проверяются вместе с lock-файлом; лицензия registry/CLI не распространяется автоматически на сторонний контент.

Источники лицензий: [React](https://github.com/facebook/react/blob/main/LICENSE), [Vite](https://github.com/vitejs/vite/blob/main/LICENSE), [Router](https://github.com/remix-run/react-router/blob/main/LICENSE.md), [Query](https://github.com/TanStack/query/blob/main/LICENSE), [shadcn](https://github.com/shadcn-ui/ui/blob/main/LICENSE.md), [Tailwind](https://github.com/tailwindlabs/tailwindcss/blob/main/LICENSE), [assistant-ui](https://github.com/assistant-ui/assistant-ui/blob/main/LICENSE), [React Flow](https://github.com/xyflow/xyflow/blob/main/LICENSE), [TypeScript](https://github.com/microsoft/TypeScript/blob/main/LICENSE.txt), [React Flow Pro](https://reactflow.dev/pro), [JointJS](https://www.jointjs.com/license).

## Официальные руководства

- [React Router: режимы](https://reactrouter.com/start/modes), [TanStack Query: назначение](https://tanstack.com/query/latest/docs/framework/react/overview), [TanStack Router](https://tanstack.com/router/latest/docs/framework/react/overview), [SWR](https://swr.vercel.app/), [RTK Query](https://redux-toolkit.js.org/rtk-query/overview).
- [shadcn/ui с Vite](https://ui.shadcn.com/docs/installation/vite), [темы Vite](https://ui.shadcn.com/docs/dark-mode/vite), [Tailwind: браузеры](https://tailwindcss.com/docs/compatibility), [MUI](https://mui.com/material-ui/).
- [assistant-ui ExternalStoreRuntime](https://www.assistant-ui.com/docs/runtimes/custom/external-store), [adapters](https://www.assistant-ui.com/docs/runtimes/concepts/adapters), [threads](https://www.assistant-ui.com/docs/runtimes/concepts/threads), [MUI Chat Preview](https://mui.com/x/react-chat/overview/), [shadcn AI Elements](https://ui.shadcn.com/docs/ai-elements).
- [React Flow: интерактивность](https://reactflow.dev/learn/concepts/adding-interactivity), [custom nodes](https://reactflow.dev/learn/customization/custom-nodes), [state](https://reactflow.dev/learn/advanced-use/state-management), [layout](https://reactflow.dev/learn/layouting/layouting), [Cytoscape.js](https://js.cytoscape.org/), [Archi: руководство и обмен](https://www.archimatetool.com/downloads/archi/Archi%20User%20Guide.pdf).
