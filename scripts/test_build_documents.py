"""Publishing regression checks; no future application behavior is exercised."""
import importlib.util
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

spec = importlib.util.spec_from_file_location('publisher', Path(__file__).with_name('build_documents.py'))
publisher = importlib.util.module_from_spec(spec)
spec.loader.exec_module(publisher)


class PublicationTests(unittest.TestCase):
    def test_refresh_contains_review_material_and_both_vector_diagrams_without_json_listing(self):
        with tempfile.TemporaryDirectory() as directory:
            target = Path(directory)
            with patch.object(publisher, 'LATEX', target):
                publisher.refresh()
            example = (target / 'example.tex').read_text()
            brd = (target / 'brd.tex').read_text()
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

    def test_local_model_link_is_plain_repository_reference(self):
        link = {'t': 'Link', 'c': [['', [], []], [{'t': 'Str', 'c': 'JSON-модель'}],
                                 ['model.json', '']]}
        self.assertNotIn('приложении', publisher.text_of(publisher.normalize(link)))


if __name__ == '__main__':
    unittest.main()
