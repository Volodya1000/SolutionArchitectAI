# Редактируемые документы и PDF

В репозитории хранятся две готовые PDF-версии и их редактируемые исходники LaTeX:

| Документ | PDF | LaTeX |
| --- | --- | --- |
| Бизнес-требования MVP | [brd.pdf](pdf/brd.pdf) | [brd.tex](latex/brd.tex) |
| Сквозной пример системы отчётности | [example.pdf](pdf/example.pdf) | [example.tex](latex/example.tex) |

Второй документ включает исходный BRD, ожидаемый архитектурный результат, обе диаграммы и **полный** YAML-манифест. Для чтения PDF другие файлы не требуются. Текст доступен для поиска и копирования; диаграммы сохраняются в векторном виде.

## Правки и сборка

Редактируйте `docs/latex/brd.tex` и `docs/latex/example.tex` напрямую. Общие шрифты, цвета, поля и оформление находятся в [common.tex](latex/common.tex). Затем из корня репозитория выполните:

```sh
python3 scripts/build_documents.py
```

Обычная сборка **не перезаписывает LaTeX** и сохраняет ручные правки. Она преобразует актуальные SVG-диаграммы во временные PDF, подключает актуальный `docs/examples/reporting-system/manifest.yaml` целиком и компилирует каждый документ дважды. Результат сохраняется в `docs/pdf/`; временные файлы и журналы — в игнорируемом `.build/documents/`. Ошибки компиляции, отсутствующие символы и выход текста за поля останавливают сборку.

Markdown остаётся самостоятельной редактируемой версией документации. Синхронизация текста Markdown и LaTeX выполняется явно. Если после изменения Markdown нужно заново получить LaTeX, выполните:

```sh
python3 scripts/build_documents.py --refresh-tex
```

**Эта команда перезаписывает `brd.tex` и `example.tex`, включая ручные правки в них.** `common.tex` сохраняется. Перед обновлением сохраните нужные правки в Git и проверьте полученный diff. Источники регенерации: `docs/BRD.md`, `docs/examples/reporting-system.md` и `docs/examples/reporting-system/expected-result.md`. Относительные ссылки превращаются в понятные подписи; диаграммы и YAML включаются в документ.

Перед сборкой после изменения `.puml` пересоздайте обе SVG из исходников. Для текущего комплекта использован PlantUML 1.2026.9 и Graphviz; например, с локальным JAR:

```sh
java -Djava.awt.headless=true -jar /path/to/plantuml-1.2026.9.jar -charset UTF-8 -tsvg docs/examples/reporting-system/data-flow.puml docs/examples/reporting-system/interactions.puml
python3 scripts/build_documents.py --refresh-tex
```

Обычная PDF-сборка использует сохранённые SVG и сама не запускает PlantUML. После пересборки проверьте таблицы, переносы и обе диаграммы визуально; экспорт кода `.puml` обязателен для A-03 и A-05.

## Инструменты

Нужны Python 3, XeLaTeX, Inkscape и шрифты DejaVu с поддержкой кириллицы. Pandoc требуется только для `--refresh-tex`.

Для Ubuntu/Debian:

```sh
sudo apt-get update
sudo apt-get install -y texlive-xetex texlive-latex-extra texlive-lang-cyrillic texlive-fonts-recommended fonts-dejavu inkscape
# Только для регенерации LaTeX из Markdown:
sudo apt-get install -y pandoc
```

Для временных меток используется `SOURCE_DATE_EPOCH`, а если он не задан — время последнего коммита, изменившего исходники сборки (без `docs/pdf/`). Это уменьшает лишние изменения PDF при одинаковых исходниках и версиях инструментов. Побайтовая идентичность между разными версиями TeX, шрифтов и Inkscape не гарантируется.

## Автоматическая сборка

[GitHub Actions](../.github/workflows/build-pdf.yml) компилирует существующие LaTeX-исходники и публикует оба PDF как артефакт запуска. Регенерация из Markdown в CI не выполняется, поэтому ручные правки LaTeX сохраняются.

Для PR из ветки этого же репозитория workflow может добавить коммит, содержащий **только два PDF**, обратно в исходную feature-ветку. Ветка `main`, `master`, ветка по умолчанию и базовая ветка PR защищены явными условиями. PR из fork и ручной запуск только собирают и загружают артефакты, без записи в ветки. Перед коммитом проверяется исходный SHA; push использует точный lease, чтобы не затереть параллельные изменения. Одновременные сборки одного PR отменяют устаревшие запуски.
