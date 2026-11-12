"""Format/reference regressions of the documentary reference, not Domain tests."""
import importlib.util
import json
from pathlib import Path
import shutil
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[1]


class ExampleValidationTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        base = Path(self.temp.name)
        self.example = base / 'reporting-system'
        shutil.copytree(ROOT / 'docs/examples/reporting-system', self.example)
        shutil.copyfile(ROOT / 'docs/examples/reporting-system.md', base / 'reporting-system.md')

    def edit(self, name, change):
        path = self.example / name
        data = json.loads(path.read_text())
        change(data)
        path.write_text(json.dumps(data, ensure_ascii=False))

    def validate(self):
        path = Path(__file__).with_name('validate_example.py')
        self.assertTrue(path.exists(), 'standalone example validator is missing')
        spec = importlib.util.spec_from_file_location('validator', path)
        validator = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(validator)
        return validator.validate(self.example)

    def test_current_reference_passes(self):
        self.validate()

    def rejects(self, change):
        change()
        with self.assertRaises(ValueError):
            self.validate()

    def test_duplicate_json_key(self):
        self.rejects(lambda: (self.example / 'model.json').write_text('{"record_type":"model","record_type":"model"}'))

    def test_invalid_json_constant(self):
        self.rejects(lambda: (self.example / 'model.json').write_text('{"value":NaN}'))

    def test_unknown_schema_version(self):
        self.rejects(lambda: self.edit('model.json', lambda d: d.update(schema_version='999')))

    def test_invalid_schema_field(self):
        self.rejects(lambda: self.edit('objects.json', lambda d: d['objects'][0].update(unexpected=True)))

    def test_duplicate_id(self):
        self.rejects(lambda: self.edit('objects.json', lambda d: d['objects'].append(d['objects'][0])))

    def test_broken_endpoint(self):
        self.rejects(lambda: self.edit('relationships.json', lambda d: d['relationships'][0].update(target_id='00000000-0000-0000-0000-000000000000')))

    def test_wrong_data_reference_type(self):
        objects = json.loads((self.example / 'objects.json').read_text())['objects']
        component = next(o['id'] for o in objects if o['kind'] == 'architecture_object')
        self.rejects(lambda: self.edit('relationships.json', lambda d: d['relationships'][0].update(data_ids=[component])))

    def test_tree_cycle(self):
        self.rejects(lambda: self.edit('views.json', lambda d: d['folders'][0].update(parent_id=d['folders'][1]['id'])))

    def test_missing_folder(self):
        self.rejects(lambda: self.edit('views.json', lambda d: d['views'][0].update(folder_id='00000000-0000-0000-0000-000000000000')))

    def test_edge_outside_view(self):
        self.rejects(lambda: self.edit('views.json', lambda d: d['views'][0]['edges'][0].update(source_node_id=d['views'][1]['nodes'][0]['id'])))

    def test_edge_endpoint_mismatch(self):
        self.rejects(lambda: self.edit('views.json', lambda d: d['views'][0]['edges'][0].update(source_node_id=d['views'][0]['nodes'][1]['id'])))

    def test_source_changed(self):
        self.rejects(lambda: (self.example.parent / 'reporting-system.md').write_text('changed'))

    def test_diagram_direction_drift(self):
        path = self.example / 'data-flow.puml'
        self.rejects(lambda: path.write_text(path.read_text().replace('Rel_Flow_Down(sales, broker,', 'Rel_Flow_Down(broker, sales,')))

    def test_diagram_access_drift(self):
        path = self.example / 'data-flow.puml'
        self.rejects(lambda: path.write_text(path.read_text().replace('Rel_Access_w(loader,', 'Rel_Access_r(loader,')))

    def test_diagram_label_drift(self):
        path = self.example / 'interactions.puml'
        self.rejects(lambda: path.write_text(path.read_text().replace('Система продаж', 'Другая система')))

    def test_quality_is_not_free_text(self):
        self.rejects(lambda: self.edit('objects.json', lambda d: d['objects'][0]['quality'].update(status='some explanation')))

    def test_copied_object_identity(self):
        def duplicate(d):
            clone = dict(d['objects'][0])
            clone['id'] = '00000000-0000-0000-0000-000000000000'
            d['objects'].append(clone)
        self.rejects(lambda: self.edit('objects.json', duplicate))

    def test_missing_data_storage(self):
        def change(d):
            next(o for o in d['objects'] if 'storage_id' in o)['storage_id'] = '00000000-0000-0000-0000-000000000000'
        self.rejects(lambda: self.edit('objects.json', change))

    def test_rule_source_reference(self):
        self.rejects(lambda: self.edit('requirements.json', lambda d: d['rules'][0].update(source_id='00000000-0000-0000-0000-000000000000')))

    def test_broken_source_reference(self):
        self.rejects(lambda: self.edit('objects.json', lambda d: d['objects'][0]['provenance'].update(source_ids=['00000000-0000-0000-0000-000000000000'])))

    def test_check_result_is_not_free_text(self):
        self.rejects(lambda: self.edit('checks.json', lambda d: d['checks'][0].update(result='some explanation')))

    def test_stale_svg_label(self):
        path = self.example / 'data-flow.svg'
        self.rejects(lambda: path.write_text(path.read_text().replace('продаж</text>', 'других</text>')))

    def test_approval_is_independent(self):
        self.edit('objects.json', lambda d: d['objects'][0]['quality'].update(status='confirmed'))
        self.validate()  # confirmed quality is legal without human approval


if __name__ == '__main__':
    unittest.main()
