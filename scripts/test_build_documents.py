"""Publishing regression checks; no future application behavior is exercised."""
import importlib.util
from pathlib import Path
import tempfile
import shutil
import xml.etree.ElementTree as ET
import unittest
from unittest.mock import patch

spec = importlib.util.spec_from_file_location('publisher', Path(__file__).with_name('build_documents.py'))
publisher = importlib.util.module_from_spec(spec)
spec.loader.exec_module(publisher)


class PublicationTests(unittest.TestCase):
    def test_all_five_documents_have_markdown_sources_and_publishing_profiles(self):
        self.assertEqual(publisher.DOCUMENTS, (
            'brd', 'example', 'technical-decisions',
            'brd-input-guidelines', 'brd-template'))
        with tempfile.TemporaryDirectory() as directory:
            with patch.object(publisher, 'LATEX', Path(directory)):
                publisher.refresh()
            guidelines = (Path(directory) / 'brd-input-guidelines.tex').read_text()
            template = (Path(directory) / 'brd-template.tex').read_text()
        self.assertIn('Приложение А.1', guidelines)
        self.assertIn('Приложение А.2', template)
        self.assertIn('DATA-03', template)
        self.assertIn(r'\begin{landscape}', template)
        self.assertIn(r'\end{landscape}', template)

    def test_refresh_contains_review_material_and_third_summary(self):
        with tempfile.TemporaryDirectory() as directory:
            target = Path(directory)
            with patch.object(publisher, 'LATEX', target):
                publisher.refresh()
            example = (target / 'example.tex').read_text()
            brd = (target / 'brd.tex').read_text()
            decisions = (target / 'technical-decisions.tex').read_text()
            for forbidden in ('model-appendix', 'VerbatimInput', 'Полная структурированная JSON',
                              'полностью приведена в приложении'):
                self.assertNotIn(forbidden, example)
            for required in ('data-flow.pdf', 'interactions.pdf', 'longtable', 'Реестр решений'):
                self.assertIn(required, example)
            for heading in ('Часть I. Исходные требования', 'Часть II. Синтетический корпоративный контекст',
                            'Часть III. Ожидаемый результат архитектурного проектирования'):
                self.assertIn(heading, example)
            self.assertIn('Архитектурное проектирование MVP системы SolutionArchitectAI', brd)
            for status in ('Подтверждено', 'Требует проверки', 'Нарушение', 'Недостаточно данных'):
                self.assertIn(status, brd)
            for required in ('Ключевые технические решения', 'LangGraph',
                             'Python 3.13', 'React Flow', 'OpenShift', 'PlantUML Server'):
                self.assertIn(required, decisions)

    def test_logical_page_breaks_survive_markdown_conversion(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / 'source.md'
            path.write_text('# Title\n\nIntro.\n\n## First\n\nText.\n\n## Second\n\n- One\n- Two\n')
            latex = publisher.convert(path, page_break_before={'Second'})
            self.assertNotIn(r'\clearpage' + '\n' + r'\section{First}', latex)
            self.assertLess(latex.index(r'\clearpage'), latex.index(r'\section{Second}'))
            self.assertEqual(latex.count(r'\clearpage'), 1)

    def test_table_guard_includes_labelled_heading(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / 'source.md'
            path.write_text('# Title\n\n## Table heading\n\n| ID | Text |\n| --- | --- |\n| A | First row |\n| B | Second row |\n| C | Third row |\n| D | Fourth |\n| E | Fifth |\n')
            latex = publisher.convert(path)
            self.assertIn(r'\KeepTableStart{1}', latex)
            self.assertLess(latex.index(r'\KeepTableStart'), latex.index(r'\section{Table heading}'))
            # Reserve two opening rows; long tables must remain breakable.
            guard = latex.split(r'\section{Table heading}')[0]
            self.assertIn('First row', guard)
            self.assertIn('Second row', guard)
            self.assertNotIn('Third row', guard)

    def test_compact_table_is_measured_whole_without_boxing_its_output(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / 'source.md'
            path.write_text('# Title\n\n| ID | Text |\n| --- | --- |\n| A | First |\n| B | Last |\n')
            latex = publisher.convert(path)
        guard, table = latex.split(r'\begin{longtable}', 1)
        self.assertIn('Last', guard)
        self.assertIn('Last', table)
        self.assertNotIn(r'\begin{samepage}', table)

    def test_short_list_guard_retains_nested_and_following_content(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / 'source.md'
            path.write_text('# Title\n\n## List\n\n- Outer\n  - Inner\n- Last\n\nFollowing paragraph.\n')
            latex = publisher.convert(path)
            self.assertIn(r'\KeepShortBlock{', latex)
            self.assertEqual(latex.count('Outer'), 1)
            self.assertEqual(latex.count('Inner'), 1)
            self.assertEqual(latex.count('Following paragraph.'), 1)
            self.assertLess(latex.index(r'\KeepShortBlock{'), latex.index(r'\section{List}'))

    def test_publishing_profiles_break_parts_without_breaking_each_brd_section(self):
        with tempfile.TemporaryDirectory() as directory:
            with patch.object(publisher, 'LATEX', Path(directory)):
                publisher.refresh()
            example = (Path(directory) / 'example.tex').read_text()
            brd = (Path(directory) / 'brd.tex').read_text()
            technical = (Path(directory) / 'technical-decisions.tex').read_text()
        self.assertIn(r'\setcounter{tocdepth}{2}', example)
        self.assertRegex(example, r'\\clearpage\s+\\section\{Часть II')
        self.assertRegex(example, r'\\clearpage\s+\\section\{Часть III')
        self.assertNotIn(r'\clearpage' + '\n' + r'\section', brd)
        for title in ('2. Backend', '4. Искусственный интеллект', '5. Пользовательский интерфейс'):
            self.assertRegex(technical, r'\\clearpage\s+(?:\\KeepShortBlock\{%\s+)?\\section\{' + title + r'\}')

    def test_refresh_is_repeatable_and_preserves_common_template(self):
        with tempfile.TemporaryDirectory() as directory:
            target = Path(directory)
            (target / 'common.tex').write_text('% Manual shared typography')
            with patch.object(publisher, 'LATEX', target):
                publisher.refresh()
                first = {path.name: path.read_bytes() for path in target.glob('*.tex')}
                publisher.refresh()
                second = {path.name: path.read_bytes() for path in target.glob('*.tex')}
        self.assertEqual(first, second)
        self.assertEqual(second['common.tex'], b'% Manual shared typography')

    @unittest.skipUnless(shutil.which('xelatex') and shutil.which('pdftotext'),
                         'PDF layout regression requires XeLaTeX and Poppler')
    def test_measured_list_does_not_overlap_preceding_paragraph(self):
        # Text extraction with bounding boxes checks visible line separation,
        # rather than asserting that a particular TeX spacing command exists.
        with tempfile.TemporaryDirectory() as directory:
            target = Path(directory)
            tex = target / 'spacing.tex'
            tex.write_text(publisher.source('Title', 'Subtitle', '',
                r'Previous paragraph BEFORE.' + '\n\n' +
                r'\KeepShortBlock{Introduction INTRODUCTION.' + '\n\n' +
                r'\begin{itemize}\item A list item.\end{itemize}}'))
            publisher.run(['xelatex', '-no-shell-escape', '-halt-on-error',
                           '-interaction=nonstopmode', f'-output-directory={target}', str(tex)],
                          capture_output=True)
            result = publisher.run(['pdftotext', '-bbox', str(target / 'spacing.pdf'), '-'],
                                   capture_output=True, text=True)
            words = {word.text: word.attrib for word in ET.fromstring(result.stdout).iter()
                     if word.tag.endswith('word')}
        previous_bottom = float(words['BEFORE.']['yMax'])
        next_top = float(words['Introduction']['yMin'])
        self.assertGreaterEqual(next_top - previous_bottom, 3.0)

    def test_local_model_link_is_plain_repository_reference(self):
        link = {'t': 'Link', 'c': [['', [], []], [{'t': 'Str', 'c': 'JSON-модель'}],
                                 ['model.json', '']]}
        self.assertNotIn('приложении', publisher.text_of(publisher.normalize(link)))

    def test_missing_third_latex_source_fails_preflight(self):
        with tempfile.TemporaryDirectory(dir=publisher.ROOT) as directory:
            target = Path(directory)
            (target / 'brd.tex').touch()
            (target / 'example.tex').touch()
            with patch.object(publisher, 'LATEX', target):
                with self.assertRaisesRegex(SystemExit, 'technical-decisions.tex'):
                    publisher.require_latex_sources()


if __name__ == '__main__':
    unittest.main()
