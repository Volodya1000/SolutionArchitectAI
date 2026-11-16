#!/usr/bin/env python3
"""Build the five committed PDFs; regenerate editable LaTeX only on request."""
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
DOCUMENTS = ('brd', 'example', 'technical-decisions',
             'brd-input-guidelines', 'brd-template')


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
        elif len(columns) == 7 and 'ID данных' in header:
            widths = [.08, .14, .15, .14, .18, .16, .15]
        else:
            widths = [1 / len(columns)] * len(columns)
        for column, width in zip(columns, widths):
            column[1] = {'t': 'ColWidth', 'c': width}
    if 'c' in value:
        value['c'] = normalize(value['c'])
    return value


def convert(path: Path, *, first_heading: str | None = None,
            page_break_before: set[str] | None = None,
            preserve_heading_levels: bool = False) -> str:
    ast = json.loads(run(['pandoc', str(path), '--from=gfm', '--to=json'],
                         capture_output=True, text=True).stdout)
    blocks = ast['blocks']
    if blocks and blocks[0]['t'] == 'Header':
        if first_heading:
            blocks[0]['c'][2] = [{'t': 'Str', 'c': first_heading}]
        else:
            blocks.pop(0)
            if not preserve_heading_levels:
                for block in blocks:
                    if block['t'] == 'Header':
                        block['c'][0] -= 1
    # Publishing profiles name semantic boundaries, not page numbers. Apply
    # breaks before normalization so Markdown regeneration retains them.
    laid_out = []
    landscape_table = False
    for block in blocks:
        if (path.name == 'brd-template.md' and block['t'] == 'Header'
                and text_of(block['c'][2]).startswith('3. Функциональные требования')):
            laid_out.append(raw(r'\begin{landscape}'))
            landscape_table = True
        if block['t'] == 'Header' and text_of(block['c'][2]) in (page_break_before or set()):
            laid_out.append(raw(r'\clearpage'))
        laid_out.append(block)
        if landscape_table and block['t'] == 'Table':
            laid_out.append(raw(r'\end{landscape}'))
            landscape_table = False
    ast['blocks'] = normalize(laid_out)
    # Guard top-level lists as a unit, including an adjacent heading or short
    # introductory paragraph. Nested lists stay within the same measurement.
    guarded = []
    for block in ast['blocks']:
        if block['t'] in ('BulletList', 'OrderedList'):
            prefix = []
            if guarded and (guarded[-1]['t'] == 'Header' or
                            (guarded[-1]['t'] == 'Para' and len(text_of(guarded[-1])) < 180)):
                prefix.insert(0, guarded.pop())
            if guarded and guarded[-1]['t'] == 'Header':
                prefix.insert(0, guarded.pop())
            guarded.extend([raw(r'\KeepShortBlock{%'), *prefix, block, raw('}')])
        else:
            guarded.append(block)
    ast['blocks'] = guarded
    latex = run(['pandoc', '--from=json', '--to=latex', '--wrap=none'],
                input=json.dumps(ast, ensure_ascii=False), capture_output=True, text=True).stdout
    return keep_table_starts(latex)


def keep_table_starts(latex: str) -> str:
    """Reserve measured opening rows, or a compact table, without boxing output.

    Include an immediately preceding heading in the reservation, so moving a
    table cannot leave its section title alone at the bottom of a page.
    """
    pattern = re.compile(
        r'(?P<headings>(?:\\(?:sub)*section\{[^\n]+\}\s*)*)'
        r'\\begin\{longtable\}(?:\[[^\]]*\])?(?P<columns>.*?)'
        r'(?P<header>\\toprule.*?)\\endhead\s*'
        r'.*?\\endlastfoot\s*(?P<rows>.*?)\\end\{longtable\}', re.S)

    def reserve(match: re.Match) -> str:
        # Pandoc may emit a separate first-page header; measure it only once.
        header = match['header'].split(r'\endfirsthead')[0]
        headings = match['headings']
        heading_count = len(re.findall(r'\\(?:sub)*section\{', headings))
        rows = re.findall(r'.*?\\\\\s*', match['rows'], re.S)
        # Short tables can move together. Larger tables reserve two opening
        # rows; the original longtable and repeated header remain breakable.
        opening_rows = rows if len(rows) <= 4 else rows[:2]
        sample = (r'\begin{tabular}' + match['columns'] + header
                  + ''.join(opening_rows) + '\n' + r'\end{tabular}')
        guard = (r'\KeepTableStart{' + str(heading_count) + '}{%\n'
                 + sample + '%\n}\n')
        return guard + match[0]

    return pattern.sub(reserve, latex)


def source(title: str, subtitle: str, description: str, body: str, *,
           toc_depth: int = 1, intro_on_title: bool = False, font_size: int = 10,
           profile: str = 'standard') -> str:
    if profile not in ('standard', 'compact'):
        raise ValueError(f'Unknown document profile: {profile}')
    if intro_on_title:
        # Move the Markdown introduction to the opening page, preserving text.
        description, section_body = body.split(r'\section', 1)
        body = r'\section' + section_body
    title_command = 'CompactDocumentTitle' if profile == 'compact' else 'DocumentTitle'
    effective_toc_depth = 0 if profile == 'compact' else toc_depth
    return (r'% Editable publishing source. Rebuild without --refresh-tex to preserve edits.' + '\n'
            + r'\documentclass[' + str(font_size) + r'pt,a4paper]{article}' + '\n'
            + r'\input{docs/latex/common.tex}' + '\n'
            + r'\hypersetup{pdftitle={' + title + r'},pdfauthor={},pdfsubject={' + subtitle + '}}\n'
            + r'\fancyhead[L]{\small SolutionArchitectAI}' + '\n'
            + r'\fancyhead[R]{\small ' + subtitle + '}\n'
            + r'\setcounter{tocdepth}{' + str(effective_toc_depth) + '}\n'
            + r'\begin{document}' + '\n'
            + '\\' + title_command + '{' + title + '}{' + subtitle + '}{' + description + '}\n'
            + body + '\n' + r'\end{document}' + '\n')


def refresh() -> None:
    if not shutil.which('pandoc'):
        raise SystemExit('pandoc is required only for --refresh-tex.')
    brd = convert(ROOT / 'docs' / 'BRD.md')
    (LATEX / 'brd.tex').write_text(source(
        'Архитектурное проектирование MVP системы SolutionArchitectAI', 'Бизнес-требования',
        '', brd))
    example = convert(ROOT / 'docs' / 'examples' / 'reporting-system.md',
                      page_break_before={'Часть II. Синтетический корпоративный контекст'})
    example += '\n'
    example += convert(EXAMPLE / 'expected-result.md',
                       first_heading='Часть III. Ожидаемый результат архитектурного проектирования',
                       page_break_before={'Часть III. Ожидаемый результат архитектурного проектирования'})
    (LATEX / 'example.tex').write_text(source(
        'Система формирования отчётности', 'Сквозной пример',
        'Синтетические требования, общая архитектурная модель, два представления решения и результаты проверок.',
        example, toc_depth=2))
    decisions = convert(ROOT / 'docs' / 'technical' / 'technical-decisions-summary.md',
                        page_break_before={'2. Backend', '4. Искусственный интеллект',
                                           '5. Пользовательский интерфейс'})
    (LATEX / 'technical-decisions.tex').write_text(source(
        'SolutionArchitectAI. Ключевые технические решения', 'Технические решения',
        '', decisions, intro_on_title=True, font_size=11))
    guidelines = convert(ROOT / 'docs' / 'brd-input-guidelines.md')
    (LATEX / 'brd-input-guidelines.tex').write_text(source(
        'Приложение А.1. Требования к входящим артефактам', 'Рекомендации к BRD',
        '', guidelines, profile='compact'))
    template = convert(ROOT / 'docs' / 'templates' / 'brd-template.md',
                       preserve_heading_levels=True)
    (LATEX / 'brd-template.tex').write_text(source(
        'Приложение А.2. Эталонный Markdown-шаблон BRD', 'Шаблон BRD',
        '', template, profile='compact'))
    print('Refreshed editable LaTeX sources from Markdown.')


def require_latex_sources() -> None:
    for name in DOCUMENTS:
        tex = LATEX / f'{name}.tex'
        if not tex.exists():
            raise SystemExit(f'Missing {tex.relative_to(ROOT)}; run with --refresh-tex first.')


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--refresh-tex', action='store_true',
                        help='overwrite all five LaTeX sources from the current Markdown before building')
    parser.add_argument('--output-dir', type=Path, default=PDF,
                        help='where compiled PDFs are copied (default: docs/pdf)')
    args = parser.parse_args()
    for path in (BUILD, LATEX, args.output_dir):
        path.mkdir(parents=True, exist_ok=True)
    for command in ('xelatex', 'inkscape'):
        if not shutil.which(command):
            raise SystemExit(f'Missing required command: {command}')
    if args.refresh_tex:
        refresh()
    require_latex_sources()
    env = os.environ.copy()
    if 'SOURCE_DATE_EPOCH' not in env:
        epoch = run(['git', 'log', '-1', '--format=%ct', '--',
                     'docs/latex/brd.tex', 'docs/latex/example.tex',
                     'docs/BRD.md', 'docs/examples/reporting-system.md',
                     'docs/examples/reporting-system',
                     'docs/examples/reporting-system/data-flow.svg',
                     'docs/examples/reporting-system/interactions.svg'],
                    capture_output=True, text=True).stdout.strip()
        env['SOURCE_DATE_EPOCH'] = epoch or '0'
    env['FORCE_SOURCE_DATE'] = '1'
    env['TZ'] = 'UTC'
    for name in ('data-flow', 'interactions'):
        run(['inkscape', str(EXAMPLE / f'{name}.svg'), '--export-type=pdf',
             f'--export-filename={BUILD / (name + ".pdf")}'], env=env,
            capture_output=True)
    for name in DOCUMENTS:
        tex = LATEX / f'{name}.tex'
        for pass_number in range(1, 5):
            # Two passes minimum; a changed TOC can itself change pagination.
            before = [(BUILD / f'{name}.{ext}').read_bytes()
                      if (BUILD / f'{name}.{ext}').exists() else b''
                      for ext in ('aux', 'toc', 'out')]
            result = subprocess.run(['xelatex', '-no-shell-escape', '-halt-on-error', '-interaction=nonstopmode',
                                     '-file-line-error', f'-output-directory={BUILD}', str(tex)],
                                    cwd=ROOT, env=env, capture_output=True, text=True)
            if result.returncode:
                print(result.stdout)
                raise SystemExit(f'XeLaTeX failed; see {BUILD / (name + ".log")}')
            after = [(BUILD / f'{name}.{ext}').read_bytes()
                     if (BUILD / f'{name}.{ext}').exists() else b''
                     for ext in ('aux', 'toc', 'out')]
            if pass_number >= 2 and before == after:
                break
        else:
            raise SystemExit(f'TOC/references did not converge after four passes: {name}')
        log = (BUILD / f'{name}.log').read_text(errors='replace')
        warnings = [line for line in log.splitlines()
                    if 'Overfull' in line or 'Missing character:' in line]
        if warnings:
            print('\n'.join(warnings))
            raise SystemExit(f'Layout or font errors in {name}; inspect the build log.')
        shutil.copyfile(BUILD / f'{name}.pdf', args.output_dir / f'{name}.pdf')
        print(f'Built {args.output_dir / (name + ".pdf")}')


if __name__ == '__main__':
    main()
