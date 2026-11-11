"""Regression checks for the document publisher, not future application tests."""
import importlib.util
import json
from pathlib import Path
import shutil
import tempfile
import unittest
from unittest.mock import patch

spec = importlib.util.spec_from_file_location('publisher', Path(__file__).with_name('build_documents.py'))
publisher = importlib.util.module_from_spec(spec)
spec.loader.exec_module(publisher)


class JsonAppendixTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        root = Path(self.temp.name)
        example = root / 'example'
        shutil.copytree(publisher.EXAMPLE, example)
        shutil.copyfile(publisher.EXAMPLE.parent / 'reporting-system.md', root / 'reporting-system.md')
        self.example = example
        self.build = root / 'build'
        self.addCleanup(patch.stopall)
        patch.object(publisher, 'EXAMPLE', example).start()
        patch.object(publisher, 'BUILD', self.build).start()

    def prepare(self):
        self.assertTrue(hasattr(publisher, 'prepare_json_appendix'), 'JSON appendix generation is missing')
        publisher.prepare_json_appendix()

    def test_appendix_preserves_every_model_file(self):
        self.prepare()
        model = json.loads((self.example / 'model.json').read_text())
        for name in ['model.json', *model['files'].values()]:
            original = json.loads((self.example / name).read_text())
            listing = json.loads((self.build / 'json' / name).read_text())
            self.assertEqual(listing, original)
        self.assertTrue((self.build / 'model-appendix.tex').is_file())

    def test_changed_source_is_not_published_as_pinned_version(self):
        source = self.example.parent / 'reporting-system.md'
        source.write_text(source.read_text() + '\nChanged source\n')
        with self.assertRaisesRegex(ValueError, 'source'):
            self.prepare()

    def test_duplicate_json_key_is_rejected(self):
        (self.example / 'model.json').write_text('{"schema_version":"1.0","schema_version":"2.0"}')
        with self.assertRaisesRegex(ValueError, 'Duplicate'):
            self.prepare()

    def test_unknown_schema_version_is_rejected(self):
        p = self.example / 'model.json'
        model = json.loads(p.read_text())
        model['schema_version'] = '999'
        p.write_text(json.dumps(model))
        with self.assertRaisesRegex(ValueError, 'schema_version'):
            self.prepare()


if __name__ == '__main__':
    unittest.main()
