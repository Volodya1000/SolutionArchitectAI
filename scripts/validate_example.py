#!/usr/bin/env python3
"""Validate the persisted documentary example, not the future Python Domain Model.

JSON Schema checks format. The remaining checks keep this finite reference's
IDs, sources, view tree and PlantUML/SVG projections consistent.
"""
from collections import Counter
import hashlib
import json
from pathlib import Path
import re
import xml.etree.ElementTree as ET

from jsonschema import Draft202012Validator, FormatChecker

EXAMPLE = Path(__file__).resolve().parents[1] / 'docs/examples/reporting-system'


def require(condition, message):
    if not condition:
        raise ValueError(message)


def load(path):
    def unique(pairs):
        result = {}
        for key, value in pairs:
            require(key not in result, f'Duplicate JSON key: {path.name}: {key}')
            result[key] = value
        return result

    def invalid_constant(value):
        raise ValueError(f'Invalid JSON constant: {value}')

    return json.loads(path.read_text(encoding='utf-8'), object_pairs_hook=unique,
                      parse_constant=invalid_constant)


def local_path(root, name):
    path = (root / name).resolve()
    require(path.is_relative_to(root.resolve()), f'Path outside example: {name}')
    return path


def compact(text):
    return re.sub(r'\s+', '', text.replace(r'\n', '')).casefold()


def check_diagram(example, view, objects, relationships):
    source = local_path(example, view['renderer']['source']).read_text()
    declarations = re.findall(r'^\s*(Application_\w+|Technology_\w+)\((\w+),\s*"([^"\n]*)"\)', source, re.M)
    by_alias = {node['renderer_alias']: node for node in view['nodes']}
    require(len(by_alias) == len(view['nodes']), 'Duplicate renderer alias')
    require(len(declarations) == len(by_alias), 'Diagram node count differs from view')
    for notation, alias, label in declarations:
        require(alias in by_alias, f'Unknown diagram alias: {alias}')
        node = by_alias[alias]
        require(notation == node['notation_type'], f'Diagram notation mismatch: {alias}')
        name = objects[node['object_id']]['properties']['название']
        expected = node['label_template'].replace('{name}', name)
        # Automatic line wrapping and the existing DB creation-state prefix are display-only.
        require(compact(expected) in compact(label), f'Diagram label mismatch: {alias}')
    calls = re.findall(r'^\s*Rel_(\w+)\((\w+),\s*(\w+),\s*"([^"\n]*)"\)', source, re.M)
    node_by_id = {n['id']: n for n in view['nodes']}
    expected_edges = Counter()
    for edge in view['edges']:
        left = node_by_id[edge['source_node_id']]['renderer_alias']
        right = node_by_id[edge['target_node_id']]['renderer_alias']
        mode = edge['access_mode']
        if mode == 'read':
            left, right = right, left  # PlantUML Access_r points from reader to data
        expected_edges[(edge['notation_type'], mode, left, right)] += 1
    actual_edges = Counter()
    for macro, left, right, label in calls:
        notation = macro.split('_')[0]
        mode = {'Access_r': 'read', 'Access_w': 'write'}.get(macro, 'not_applicable')
        actual_edges[(notation, mode, left, right)] += 1
    require(actual_edges == expected_edges, 'Diagram relations/directions/access differ from view')

    svg = ET.parse(local_path(example, view['renderer']['image'])).getroot()
    require(svg.tag.endswith('svg'), 'Diagram export is not SVG')
    entities = {g.attrib['id']: g for g in svg.iter() if g.attrib.get('class') == 'entity'}
    aliases = {key: g.attrib['data-qualified-name'].split('.')[-1] for key, g in entities.items()}
    require(set(aliases.values()) == set(by_alias), 'SVG entities differ from source')
    for notation, alias, label in declarations:
        entity = next(g for key, g in entities.items() if aliases[key] == alias)
        visible = ''.join(t.text or '' for t in entity.iter() if t.tag.endswith('text'))
        require(compact(label) == compact(visible), f'SVG label differs from source: {alias}')
    svg_edges = Counter((aliases[g.attrib['data-entity-1']], aliases[g.attrib['data-entity-2']])
                        for g in svg.iter() if g.attrib.get('class') == 'link')
    # PlantUML's Up macro reverses SVG entity metadata to influence layout.
    require(svg_edges == Counter((right, left) if macro.endswith('_Up') else (left, right)
                                 for macro, left, right, _ in calls),
            'SVG connections differ from source')


def validate(example=EXAMPLE):
    example = Path(example)
    schema = load(example / 'model.schema.json')
    Draft202012Validator.check_schema(schema)
    validator = Draft202012Validator(schema, format_checker=FormatChecker())
    model = load(example / 'model.json')
    documents = {'model': model}
    for kind, name in model.get('files', {}).items():
        require(Path(name).name == name and name.endswith('.json'), 'Invalid model filename')
        documents[kind] = load(example / name)
    for kind, document in documents.items():
        errors = list(validator.iter_errors(document))
        require(not errors, f'Schema: {kind}: ' + '; '.join(e.message for e in errors[:3]))
        require(document['record_type'] == kind, f'Wrong file record_type: {kind}')

    seen = set()

    def ids(value):
        if isinstance(value, dict):
            if 'id' in value:
                require(value['id'] not in seen, f'Duplicate ID: {value["id"]}')
                seen.add(value['id'])
            for item in value.values():
                ids(item)
        elif isinstance(value, list):
            for item in value:
                ids(item)

    ids(documents)
    for kind in ('objects', 'relationships'):
        aliases = [r['alias'] for r in documents[kind][kind]]
        require(len(aliases) == len(set(aliases)), f'Duplicate {kind} alias: ambiguous identity')
    objects = {o['id']: o for o in documents['objects']['objects']}
    relationships = {r['id']: r for r in documents['relationships']['relationships']}
    sources = {s['id']: s for s in documents['sources']['sources']}
    checks = {c['id']: c for c in documents['checks']['checks']}

    def ref(key, collection, label):
        require(key in collection, f'Missing/wrong {label} reference: {key}')

    def kind_ref(key, kind):
        ref(key, objects, kind)
        require(objects[key]['kind'] == kind, f'Wrong reference type: {key}: expected {kind}')

    for check in checks.values():
        for key in check['quality']['check_ids']:
            ref(key, checks, 'check')
    for record in [*objects.values(), *relationships.values()]:
        for key in record['provenance']['source_ids']:
            ref(key, sources, 'source')
        for key in record['quality']['check_ids']:
            ref(key, checks, 'check')
    for obj in objects.values():
        for field in ['owner_id', 'platform_id', 'storage_id']:
            if field in obj:
                kind_ref(obj[field], 'architecture_object')
    for relation in relationships.values():
        ref(relation['source_id'], objects, 'endpoint')
        ref(relation['target_id'], objects, 'endpoint')
        for key in relation.get('data_ids', []):
            kind_ref(key, 'data')
        if 'interface_id' in relation:
            kind_ref(relation['interface_id'], 'interface')
            require(objects[relation['interface_id']]['owner_id'] == relation['target_id'],
                    'Interface owner differs from interaction recipient')
        if 'interaction_id' in relation:
            ref(relation['interaction_id'], relationships, 'interaction')
            require(relationships[relation['interaction_id']]['kind'] == 'interaction', 'Wrong interaction reference type')
    ref(model['context']['selected_proxy_id'], objects, 'selected proxy')
    for record in [*documents['requirements']['requirements'], *documents['requirements']['rules']]:
        ref(record['source_id'], sources, 'requirement source')
    for decision in documents['decisions']['decisions']:
        for key in decision['source_ids']:
            ref(key, sources, 'decision source')
    for source in sources.values():
        path = local_path(example.parent, str(Path(example.name) / source['path']))
        content = path.read_bytes()
        digest = hashlib.sha256(content).hexdigest()
        require(digest == source['sha256'] and source['version_id'] == 'sha256:' + digest
                and len(content) == source['size_bytes'], f'Pinned source mismatch: {source["path"]}')
        require(source['section'] in content.decode('utf-8'), 'Missing source section')

    folders = {f['id']: f for f in documents['views']['folders']}
    for folder in folders.values():
        trail = set()
        current = folder['id']
        while current is not None:
            ref(current, folders, 'folder')
            require(current not in trail, 'View tree cycle')
            trail.add(current)
            current = folders[current]['parent_id']
    usage = Counter()
    for view in documents['views']['views']:
        ref(view['folder_id'], folders, 'view folder')
        nodes = {n['id']: n for n in view['nodes']}
        for node in nodes.values():
            ref(node['object_id'], objects, 'view object')
        usage.update(set(n['object_id'] for n in nodes.values()))
        for group in view['groups']:
            for key in group['node_ids']:
                ref(key, nodes, 'group node')
            if 'object_id' in group:
                ref(group['object_id'], objects, 'group object')
        for edge in view['edges']:
            ref(edge['relationship_id'], relationships, 'view relationship')
            ref(edge['source_node_id'], nodes, 'source node in view')
            ref(edge['target_node_id'], nodes, 'target node in view')
            relation = relationships[edge['relationship_id']]
            require(nodes[edge['source_node_id']]['object_id'] == relation['source_id']
                    and nodes[edge['target_node_id']]['object_id'] == relation['target_id'],
                    'View endpoints differ from catalog relationship')
        check_diagram(example, view, objects, relationships)
    require(any(count > 1 for count in usage.values()), 'Views do not reuse a shared object')
    return {'documents': len(documents), 'objects': len(objects), 'relationships': len(relationships),
            'views': len(documents['views']['views']), 'shared_objects': sum(c > 1 for c in usage.values())}


if __name__ == '__main__':
    print('Documentary example:', validate())
