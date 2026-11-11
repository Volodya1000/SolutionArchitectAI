#!/usr/bin/env python3
"""Build the two committed PDFs; regenerate editable LaTeX only on request."""
from __future__ import annotations

import argparse
import copy
import hashlib
import json
import os
from pathlib import Path
import re
import shutil
import subprocess
import xml.etree.ElementTree as ET

ROOT = Path(__file__).resolve().parents[1]
BUILD = ROOT / '.build' / 'documents'
LATEX = ROOT / 'docs' / 'latex'
PDF = ROOT / 'docs' / 'pdf'
EXAMPLE = ROOT / 'docs' / 'examples' / 'reporting-system'


def run(command: list[str], **kwargs: object) -> subprocess.CompletedProcess:
    return subprocess.run(command, cwd=ROOT, check=True, **kwargs)


def text_of(value: object) -> str:
    if isinstance(value, list):
        return ''.join(text_of(item) for item in value)
    if isinstance(value, dict):
        if value.get('t') == 'Str':
            return value['c']
        if value.get('t') in ('Space', 'SoftBreak', 'LineBreak'):
            return ' '
        return text_of(value.get('c', []))
    return ''


def raw(value: str) -> dict:
    return {'t': 'RawBlock', 'c': ['latex', value]}


def normalize(value: object) -> object:
    """Make a standalone edition: readable links, vector figures, fitted tables."""
    if isinstance(value, list):
        return [normalize(item) for item in value]
    if not isinstance(value, dict):
        return value
    value = copy.deepcopy(value)
    kind, content = value.get('t'), value.get('c')
    if kind == 'Link' and not re.match(r'https?://|mailto:', content[2][0]):
        label = text_of(content[1])
        if label in ('model.json', 'JSON-модель'):
            return {'t': 'Span', 'c': [['', [], []], [{'t': 'Str', 'c': 'JSON-модель (полностью приведена в приложении)'}]]}
        return {'t': 'Span', 'c': [['', [], []], normalize(content[1])]}
    if kind == 'Image':
        name = Path(content[2][0]).stem
        if name not in ('data-flow', 'interactions'):
            raise ValueError(f'Unrecognised diagram: {content[2][0]}')
        caption = {'data-flow': 'Диаграмма потоков данных',
                   'interactions': 'Диаграмма межсистемных взаимодействий'}[name]
        svg = ET.parse(EXAMPLE / f'{name}.svg').getroot()
        _, _, width, height = map(float, svg.attrib['viewBox'].split())
        landscape = width / height > 1.35
        opening = r'\begin{landscape}\thispagestyle{plain}' if landscape else r'\clearpage'
        closing = r'\end{landscape}' if landscape else r'\clearpage'
        return raw(opening + '\n' + r'\subsection*{' + caption + '}\n'
                   + r'\vfill\begin{center}' + '\n'
                   + r'\includegraphics[width=\linewidth,height=.82\textheight,keepaspectratio]{.build/documents/'
                   + name + '.pdf}\n' + r'\end{center}\vfill' + '\n' + closing)
    if kind == 'Para' and len(content) == 1 and content[0].get('t') == 'Image':
        return normalize(content[0])
    if kind == 'Table':
        columns = content[2]
        header = text_of(content[3])
        if len(columns) == 2:
            widths = [.25, .75]
        elif len(columns) == 3:
            if 'Признак приёмки' in header:
                widths = [.09, .21, .70]
            elif 'Условие обнаружения' in header:
                widths = [.23, .45, .32]
            elif 'Результат в Git' in header:
                widths = [.25, .45, .30]
            else:
                widths = [.14, .28, .58] if 'ID' in header else [.31, .35, .34]
        elif len(columns) == 4:
            widths = [.25, .44, .22, .09] if 'Порт' in header else [.24, .24, .30, .22]
        elif len(columns) == 5:
            widths = [.235, .235, .28, .17, .08]
        else:
            widths = [1 / len(columns)] * len(columns)
        for column, width in zip(columns, widths):
            column[1] = {'t': 'ColWidth', 'c': width}
    if 'c' in value:
        value['c'] = normalize(value['c'])
    return value


def convert(path: Path, *, first_heading: str | None = None) -> str:
    ast = json.loads(run(['pandoc', str(path), '--from=gfm', '--to=json'],
                         capture_output=True, text=True).stdout)
    blocks = ast['blocks']
    if blocks and blocks[0]['t'] == 'Header':
        if first_heading:
            blocks[0]['c'][2] = [{'t': 'Str', 'c': first_heading}]
        else:
            blocks.pop(0)
            for block in blocks:
                if block['t'] == 'Header':
                    block['c'][0] -= 1
    ast['blocks'] = normalize(blocks)
    latex = run(['pandoc', '--from=json', '--to=latex', '--wrap=none'],
                input=json.dumps(ast, ensure_ascii=False), capture_output=True, text=True).stdout
    return keep_table_starts(latex)


def keep_table_starts(latex: str) -> str:
    """Reserve the measured header + first row, without keeping whole tables.

    Include an immediately preceding heading in the reservation, so moving a
    table cannot leave its section title alone at the bottom of a page.
    """
    pattern = re.compile(
        r'(?P<headings>(?:\\(?:sub)*section\{[^\n]+\}\s*)*)'
        r'\\begin\{longtable\}(?:\[[^\]]*\])?(?P<columns>.*?)'
        r'(?P<header>\\toprule.*?)\\endhead\s*'
        r'.*?\\endlastfoot\s*(?P<row>.*?\\\\)\s*', re.S)

    def reserve(match: re.Match) -> str:
        # Pandoc may emit a separate first-page header; measure it only once.
        header = match['header'].split(r'\endfirsthead')[0]
        headings = match['headings']
        heading_count = len(re.findall(r'\\(?:sub)*section\{', headings))
        sample = (r'\begin{tabular}' + match['columns'] + header
                  + match['row'] + '\n' + r'\end{tabular}')
        guard = (r'\KeepTableStart{' + str(heading_count) + '}{%\n'
                 + sample + '%\n}\n')
        return guard + match[0]

    return pattern.sub(reserve, latex)


def source(title: str, subtitle: str, description: str, body: str) -> str:
    return (r'% Editable publishing source. Rebuild without --refresh-tex to preserve edits.' + '\n'
            + r'\documentclass[10pt,a4paper]{article}' + '\n'
            + r'\input{docs/latex/common.tex}' + '\n'
            + r'\hypersetup{pdftitle={' + title + r'},pdfauthor={},pdfsubject={' + subtitle + '}}\n'
            + r'\fancyhead[L]{\small SolutionArchitectAI}' + '\n'
            + r'\fancyhead[R]{\small ' + subtitle + '}\n'
            + r'\begin{document}' + '\n'
            + r'\DocumentTitle{' + title + '}{' + subtitle + '}{' + description + '}\n'
            + body + '\n' + r'\end{document}' + '\n')


def prepare_json_appendix() -> None:
    """Publish every data file, retaining full JSON and checking source pins.

    This is a publishing check, not the future application's domain validator.
    Indented records permit page breaks without a second model in Git.
    """
    def unique_pairs(pairs: list[tuple[str, object]]) -> dict:
        result = {}
        for key, value in pairs:
            if key in result:
                raise ValueError(f'Duplicate JSON key: {key}')
            result[key] = value
        return result

    def load(name: str) -> dict:
        return json.loads((EXAMPLE / name).read_text(), object_pairs_hook=unique_pairs)

    model = load('model.json')
    if model.get('schema_version') != '1.0':
        raise ValueError('Unsupported model schema_version')
    names = ['model.json', *model['files'].values()]
    if any(Path(name).name != name or not name.endswith('.json') for name in names):
        raise ValueError('Model files must be local JSON filenames')
    documents = {name: load(name) for name in names}
    for source_ref in documents[model['files']['sources']]['sources']:
        source_path = (EXAMPLE / source_ref['path']).resolve()
        if not source_path.is_relative_to(EXAMPLE.parent.resolve()):
            raise ValueError('Pinned source is outside the example directory')
        content = source_path.read_bytes()
        digest = hashlib.sha256(content).hexdigest()
        if (digest != source_ref['sha256'] or len(content) != source_ref['size_bytes']
                or source_ref['version_id'] != 'sha256:' + digest):
            raise ValueError(f"Pinned source mismatch: {source_ref['path']}")
    directory = BUILD / 'json'
    directory.mkdir(parents=True, exist_ok=True)
    sections = []
    for name, data in documents.items():
        # Physical line breaks let fvextra paginate even deeply nested views.
        (directory / name).write_text(json.dumps(data, ensure_ascii=False, sort_keys=True,
                                                indent=2) + '\n')
        relative = (Path('.build/documents/json') / name).as_posix()
        sections.append(r'\subsection{' + name + '}\n'
                        + r'\VerbatimInput[fontsize=\small,breaklines=true,breakanywhere=true,'
                        + r'breaksymbolleft={},breaksymbolright={},tabsize=2,'
                        + r'frame=leftline,framerule=.6pt,rulecolor=\color{Accent},'
                        + r'xleftmargin=8pt,framesep=8pt]{' + relative + '}\n')
    (BUILD / 'model-appendix.tex').write_text('\n'.join(sections))


def refresh() -> None:
    if not shutil.which('pandoc'):
        raise SystemExit('pandoc is required only for --refresh-tex.')
    brd = convert(ROOT / 'docs' / 'BRD.md')
    (LATEX / 'brd.tex').write_text(source(
        'SolutionArchitectAI', 'Бизнес-требования · MVP',
        'Назначение, этапы проектирования, результаты и критерии приёмки первой версии.', brd))
    example = convert(ROOT / 'docs' / 'examples' / 'reporting-system.md',
                      first_heading='Исходные требования и контекст')
    example += '\n'
    example += convert(EXAMPLE / 'expected-result.md', first_heading='Ожидаемый архитектурный результат')
    example += '\n' + r'''\section{Полная структурированная JSON-модель}
\label{model-appendix}
Ниже приведены все данные модели, включая общие объекты, отношения,
требования, источники, решения, дерево представлений и ограничения проверок.
Запись с отступами сохраняет все значения и допускает переносы страниц. Это ручной эталон, а не результат работы приложения.
Схема версии 1.0 определена в model.schema.json репозитория.
\input{.build/documents/model-appendix.tex}
'''
    (LATEX / 'example.tex').write_text(source(
        'Система формирования отчётности', 'Сквозной пример',
        'Синтетические требования, общая архитектурная модель, два представления и полный JSON.',
        example))
    print('Refreshed editable LaTeX sources from Markdown.')


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--refresh-tex', action='store_true',
                        help='overwrite brd.tex and example.tex from the current Markdown before building')
    args = parser.parse_args()
    for path in (BUILD, LATEX, PDF):
        path.mkdir(parents=True, exist_ok=True)
    for command in ('xelatex', 'inkscape'):
        if not shutil.which(command):
            raise SystemExit(f'Missing required command: {command}')
    prepare_json_appendix()
    if args.refresh_tex:
        refresh()
    env = os.environ.copy()
    if 'SOURCE_DATE_EPOCH' not in env:
        epoch = run(['git', 'log', '-1', '--format=%ct', '--', 'docs/latex',
                     'docs/BRD.md', 'docs/examples/reporting-system.md',
                     'docs/examples/reporting-system',
                     'docs/examples/reporting-system/data-flow.svg',
                     'docs/examples/reporting-system/interactions.svg',
                     'scripts/build_documents.py'], capture_output=True, text=True).stdout.strip()
        env['SOURCE_DATE_EPOCH'] = epoch or '0'
    env['FORCE_SOURCE_DATE'] = '1'
    env['TZ'] = 'UTC'
    for name in ('data-flow', 'interactions'):
        run(['inkscape', str(EXAMPLE / f'{name}.svg'), '--export-type=pdf',
             f'--export-filename={BUILD / (name + ".pdf")}'], env=env,
            capture_output=True)
    for name in ('brd', 'example'):
        tex = LATEX / f'{name}.tex'
        if not tex.exists():
            raise SystemExit(f'Missing {tex.relative_to(ROOT)}; run with --refresh-tex first.')
        for _ in range(2):
            result = subprocess.run(['xelatex', '-no-shell-escape', '-halt-on-error', '-interaction=nonstopmode',
                                     '-file-line-error', f'-output-directory={BUILD}', str(tex)],
                                    cwd=ROOT, env=env, capture_output=True, text=True)
            if result.returncode:
                print(result.stdout)
                raise SystemExit(f'XeLaTeX failed; see {BUILD / (name + ".log")}')
        log = (BUILD / f'{name}.log').read_text(errors='replace')
        warnings = [line for line in log.splitlines()
                    if 'Overfull' in line or 'Missing character:' in line]
        if warnings:
            print('\n'.join(warnings))
            raise SystemExit(f'Layout or font errors in {name}; inspect the build log.')
        shutil.copyfile(BUILD / f'{name}.pdf', PDF / f'{name}.pdf')
        print(f'Built docs/pdf/{name}.pdf')


if __name__ == '__main__':
    main()
