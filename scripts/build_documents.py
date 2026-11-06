#!/usr/bin/env python3
"""Build the two committed PDFs; regenerate editable LaTeX only on request."""
from __future__ import annotations

import argparse
import copy
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
        if label in ('manifest.yaml', 'YAML-манифест'):
            return {'t': 'Span', 'c': [['', [], []], [{'t': 'Str', 'c': 'архитектурный манифест (полностью приведён в приложении)'}]]}
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
    if kind == 'Para' and text_of(content).startswith('Документы и манифест проверяются в рамках одного коммита Git.'):
        return raw('')
    if kind == 'Para' and text_of(content).startswith('Эталон подготовлен по '):
        return raw('Решения предложены для ревью; согласование и ответы человека не имитируются.')
    if kind == 'Para' and len(content) == 1 and content[0].get('t') == 'Image':
        return normalize(content[0])
    if kind == 'Table':
        columns = content[2]
        header = text_of(content[3])
        if len(columns) == 2:
            widths = [.25, .75]
        elif len(columns) == 3:
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
    return run(['pandoc', '--from=json', '--to=latex', '--wrap=none'],
               input=json.dumps(ast, ensure_ascii=False), capture_output=True, text=True).stdout


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


def refresh() -> None:
    if not shutil.which('pandoc'):
        raise SystemExit('pandoc is required only for --refresh-tex.')
    brd = convert(ROOT / 'docs' / 'BRD.md')
    (LATEX / 'brd.tex').write_text(source(
        'SolutionArchitectAI', 'Бизнес-требования · MVP',
        'Назначение, этапы проектирования, результаты и критерии приёмки первой версии.', brd))
    example = convert(ROOT / 'docs' / 'examples' / 'reporting-system.md',
                      first_heading='Исходные требования и контекст')
    example += '\n' + r'\clearpage' + '\n'
    example += convert(EXAMPLE / 'expected-result.md', first_heading='Ожидаемый архитектурный результат')
    example += '\n' + r'''\clearpage
\section{Полный архитектурный манифест}
\label{manifest-appendix}
Ниже приведён полный YAML-манифест системы формирования отчётности.
Он описывает контекст, системы, наборы данных, потоки и технические взаимодействия.
\VerbatimInput[fontsize=\normalsize,breaklines=true,breakanywhere=true,
  breaksymbolleft={},breaksymbolright={},tabsize=2,
  frame=leftline,framerule=.6pt,rulecolor=\color{Accent},
  xleftmargin=8pt,framesep=8pt]{docs/examples/reporting-system/manifest.yaml}
'''
    (LATEX / 'example.tex').write_text(source(
        'Система формирования отчётности', 'Сквозной пример',
        'Синтетические бизнес-требования, архитектурный результат, две диаграммы и полный YAML-манифест.',
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
    if args.refresh_tex:
        refresh()
    env = os.environ.copy()
    if 'SOURCE_DATE_EPOCH' not in env:
        epoch = run(['git', 'log', '-1', '--format=%ct', '--', 'docs/latex',
                     'docs/examples/reporting-system/manifest.yaml',
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
