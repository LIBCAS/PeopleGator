"""Per-engine checkpoint pairs, trusted inspection and resume using local fixtures."""

from configparser import ConfigParser
from copy import copy
import json
from pathlib import Path
import pickle
import shutil
import sys
from unittest.mock import Mock

import pytest

from people_gator.core.checkpoints import load_checkpoint, save_checkpoint


@pytest.fixture(autouse=True)
def processing_only(runtime_mode):
    if runtime_mode == 'client':
        pytest.skip('Checkpoint tests require processing extras')


def pipeline(tmp_path, monkeypatch, model='original', device='cpu'):
    from people_gator.core import document_parser
    config = ConfigParser()
    config['PARSE_FOLDER'] = {'PROCESSING_CHECKPOINTS': str(tmp_path / 'snapshots')}
    engines = []
    for i in range(3):
        config[f'ENGINE_{i}'] = {'METHOD': 'TEXT_ENTITY_DETECTION', 'MODEL_NAME': model}
        engine = Mock()
        engine.process_document.side_effect = lambda doc, i=i: mark(doc, i)
        engines.append(engine)
    monkeypatch.setattr(document_parser, 'engine_factory', Mock(side_effect=engines))
    return document_parser.DocumentParser(config, device, str(tmp_path)), engines, config


def mark(doc, index):
    result = copy(doc)
    result.name = f'{doc.name} {index}'
    return result


def snapshots(tmp_path):
    return sorted((tmp_path / 'snapshots').rglob('checkpoint.json'))


@pytest.mark.parametrize('fmt', ['alto', 'page'])
def test_native_checkpoint_pair(tmp_path, fmt):
    import cv2
    import numpy as np
    from test_entity_matching import document, face, identity
    person = identity(entity_id='app-person')
    doc = document(fmt, linked=person)
    page, lazy_page = doc.page_layouts
    region = page.regions[0]
    saved_face = face(page, person, source=region)
    saved_face.face_metadata.prompts.append({'prompt': 'Čapek', 'response': 'raw'})
    doc.extra = {'source_line': region.lines[0]}
    doc.entity_linking_journal.append({'state': 'created', 'targets': [doc.text_entity_clusters[0]]})
    pixels = np.full((8, 12, 3), 42, dtype=np.uint8)
    doc.page_images_dir = str(tmp_path)
    doc.page_images[page.id] = pixels
    assert cv2.imwrite(str(tmp_path / f'{lazy_page.id}.jpg'), pixels)
    stage = tmp_path / 'stage'
    metadata = {'next_step': 1, 'notes': ['Čapek', None]}
    save_checkpoint(stage, doc, metadata)

    assert {p.name for p in stage.iterdir()} == {'document.pkl', 'checkpoint.json'}
    with (stage / 'document.pkl').open('rb') as stream:
        assert pickle.load(stream).text_entities[0].name == 'Karel Čapek'
    restored, info = load_checkpoint(stage / 'checkpoint.json')
    assert info == metadata
    page, lazy_page = restored.page_layouts
    cluster = restored.text_entity_clusters[0]
    assert cluster.text_entities[0] is page.text_entities[0]
    assert cluster.text_entities[1] is lazy_page.text_entities[0]
    assert restored.entity_linking_journal[0]['targets'][0] is cluster
    assert page.faces[0].face_metadata.page_identity.identity is cluster.identity
    assert page.faces[0].source_region is page.regions[0]
    assert restored.extra['source_line'] is page.regions[0].lines[0]
    assert restored.extra['source_line'].transcription == region.lines[0].transcription
    assert page.text_entities[0].source_spans == doc.text_entities[0].source_spans
    assert page.faces[0].face_metadata.prompts == saved_face.face_metadata.prompts
    assert set(restored.page_images) == {page.id}
    np.testing.assert_array_equal(restored.get_page_image(page), pixels)
    np.testing.assert_array_equal(restored.get_page_image(lazy_page), pixels)


@pytest.mark.parametrize('checkpoint_index', [0, 2])
def test_resume_with_current_settings_and_export(tmp_path, monkeypatch, checkpoint_index):
    from people_gator.core import document_parser
    from people_gator.core.layout import PeopleGatorDocument
    parser, engines, _ = pipeline(tmp_path, monkeypatch)
    parser.db_api_service = Mock()
    imported = PeopleGatorDocument(id='doc', name='imported')
    app_import = Mock(return_value=imported)
    app_export = Mock()
    monkeypatch.setattr(document_parser, 'import_document', app_import)
    monkeypatch.setattr(document_parser, 'export_document', app_export)
    initial = PeopleGatorDocument()
    full = parser.process_document(initial, import_from_app=True, export_to_app=True)
    app_import.assert_called_once_with(initial, parser.db_api_service)
    app_export.assert_called_once_with(full, parser.db_api_service, drop_existing_annotations=False)
    assert full.name == 'imported 0 1 2'
    paths = snapshots(tmp_path)
    assert len(paths) == 3
    for index, path in enumerate(paths):
        result, metadata = load_checkpoint(path)
        assert result.name == engines[index].process_document.call_args.args[0].name + f' {index}'
        assert metadata == {'next_step': index + 1, 'last_completed': index, 'engine': 'Mock', 'document_id': 'doc'}
    copied = tmp_path / 'copied'
    shutil.copytree(paths[checkpoint_index].parent, copied)
    # Only the copied pair is available at the resume path.
    (tmp_path / 'snapshots').rename(tmp_path / 'archived')
    resumed, engines, config = pipeline(tmp_path, monkeypatch, model='revised', device='gpu')
    resumed.db_api_service = parser.db_api_service
    config['PARSE_FOLDER']['PROCESSING_CHECKPOINTS'] = str(tmp_path / 'resumed')
    restored = resumed.process_document(None, resume_from_checkpoint=copied, import_from_app=checkpoint_index == 0,
                                        export_to_app=True, drop_existing_annotations=True)
    assert restored.name == full.name
    assert app_import.call_count == 1
    app_export.assert_called_with(restored, parser.db_api_service, drop_existing_annotations=True)
    assert [engine.process_document.call_count for engine in engines] == [int(i > checkpoint_index) for i in range(3)]
    assert len(list((tmp_path / 'resumed').rglob('checkpoint.json'))) == 2 - checkpoint_index
    assert not (tmp_path / 'snapshots').exists()


def test_independent_runs_and_skipped_engine_sections(tmp_path, monkeypatch):
    from people_gator.core import document_parser
    from people_gator.core.layout import PeopleGatorDocument
    config = ConfigParser()
    config.read_dict({'PARSE_FOLDER': {'PROCESSING_CHECKPOINTS': str(tmp_path / 'snapshots')},
                      'ENGINE_0': {}, 'ENGINE_1': {'METHOD': 'TEXT_ENTITY_DETECTION'}})
    engine = Mock()
    engine.process_document.side_effect = lambda doc: doc
    monkeypatch.setattr(document_parser, 'engine_factory', Mock(side_effect=[None, engine]))
    parser = document_parser.DocumentParser(config, 'cpu', str(tmp_path))
    for name in ('first', 'second'):
        parser.process_document(PeopleGatorDocument(name=name))
    assert sorted((doc.name, info['next_step']) for doc, info in map(load_checkpoint, snapshots(tmp_path))) == [
        ('first', 1), ('second', 1)]


@pytest.mark.parametrize('failure', ['engine', 'save'])
def test_failure_leaves_previous_stage_usable(tmp_path, monkeypatch, failure):
    from people_gator.core.layout import PeopleGatorDocument
    parser, engines, _ = pipeline(tmp_path, monkeypatch)

    def fail(doc):
        doc.name = 'partial'
        if failure == 'engine':
            raise RuntimeError('engine failed')
        doc.unpickleable = lambda: None
        return doc

    engines[1].process_document.side_effect = fail
    with pytest.raises(RuntimeError if failure == 'engine' else (AttributeError, pickle.PicklingError)):
        parser.process_document(PeopleGatorDocument(name='before'))
    engines[2].process_document.assert_not_called()
    path, = snapshots(tmp_path)
    assert load_checkpoint(path)[0].name == 'before 0'
    engines[1].process_document.side_effect = lambda doc: mark(doc, 1)
    assert parser.process_document(None, resume_from_checkpoint=path).name == 'before 0 1 2'


@pytest.mark.parametrize('filename,contents,error', [
    ('document.pkl', None, FileNotFoundError), ('document.pkl', b'invalid', pickle.UnpicklingError),
    ('checkpoint.json', b'{', json.JSONDecodeError), ('checkpoint.json', b'{}', KeyError),
])
def test_resume_surfaces_read_errors(tmp_path, monkeypatch, filename, contents, error):
    from people_gator.core.layout import PeopleGatorDocument
    parser, engines, _ = pipeline(tmp_path, monkeypatch)
    stage = tmp_path / 'stage'
    save_checkpoint(stage, PeopleGatorDocument(), {'next_step': 1})
    damaged = stage / filename
    if contents is None:
        damaged.unlink()
    else:
        damaged.write_bytes(contents)
    with pytest.raises(error):
        parser.process_document(None, resume_from_checkpoint=stage)
    assert not any(engine.process_document.called for engine in engines)


def test_inspect_pair_without_processing(tmp_path, monkeypatch, capsys):
    from test_entity_matching import document, face, identity
    from user_scripts import inspect_checkpoint as cli
    person = identity(entity_id='app-person')
    doc = document(linked=person)
    page = doc.page_layouts[0]
    face(page, person, source=page.regions[0])
    stage = tmp_path / 'stage'
    save_checkpoint(stage, doc, {'next_step': 1})
    before = {p: p.read_bytes() for p in stage.iterdir()}
    output = tmp_path / 'diagnostics' / 'selected.json'
    monkeypatch.setattr(sys, 'argv', ['inspect_checkpoint', str(stage), '--details', 'entities', '--output-path', str(output)])
    assert cli.main() == 0
    selected = json.loads(output.read_text())
    assert output.read_text(encoding='utf-8') == json.dumps(selected, ensure_ascii=True, indent=2) + '\n'
    assert selected['clusters'][0]['mentions'] == [0, 1]
    assert selected['pages'][0]['mentions'][0]['source_spans'][0]['start'] == 0
    assert 'ocr' not in selected['pages'][0]
    assert 'regions' not in selected['pages'][0]
    monkeypatch.setattr(sys, 'argv', ['inspect_checkpoint', str(stage / 'checkpoint.json')])
    assert cli.main() == 0
    report = json.loads(capsys.readouterr().out)
    assert report['next_step'] == 1
    assert report['summary']['faces'] == 1
    assert report['pages'][0]['ocr'][0]['text'] == page.regions[0].lines[0].transcription
    assert report['pages'][0]['faces'][0]['source_region_id'] == page.regions[0].id
    assert report['pages'][0]['faces'][0]['entity_id'] == 'app-person'
    alias = tmp_path / 'report.json'
    alias.hardlink_to(stage / 'document.pkl')
    for input_file in (*before, alias):
        monkeypatch.setattr(sys, 'argv', ['inspect_checkpoint', str(stage), '--output-path', str(input_file)])
        with pytest.raises(SystemExit):
            cli.main()
    monkeypatch.setattr(sys, 'argv', ['inspect_checkpoint', str(stage), '--output-path', str(output.parent)])
    with pytest.raises(OSError):
        cli.main()
    assert {p: p.read_bytes() for p in stage.iterdir()} == before


def test_inspect_optional_face_and_entity_fields(tmp_path):
    import numpy as np
    from test_entity_matching import add_cluster, document, face, identity, page_identity
    from people_gator.core.checkpoint_inspection import inspect_checkpoint
    from people_gator.core.layout import Position

    doc = document(linked=identity(entity_id='cluster'))
    first, second = doc.page_layouts
    first.text_entities[0].page_identity = page_identity(identity(entity_id='mention'))
    second.text_entities[0].page_identity = page_identity()
    second.text_entities[0].page_identity.identity = None
    add_cluster(doc, name='Unlinked')
    source = first.regions[0]
    linked = face(first, identity('Linked face', 'face'), source=source)
    meta = linked.face_metadata
    meta.left_eye_position = Position(np.int32(1), 2)
    meta.right_eye_position = Position(3, 4)
    meta.nose_position = None
    meta.left_mouth_corner_position = Position(5, 6)
    meta.right_mouth_corner_position = Position(7, 8)
    face(first, suffix='no-metadata').face_metadata = None
    face(first, suffix='no-page-identity').face_metadata.page_identity = None
    face(first, suffix='no-identity').face_metadata.page_identity.identity = None

    stage = tmp_path / 'stage'
    save_checkpoint(stage, doc, {'next_step': 1})
    report = inspect_checkpoint(stage)
    assert report['summary']['resolved_identities'] == 3
    assert [c['entity_id'] for c in report['clusters']] == ['cluster', None]
    assert [m['entity_id'] for p in report['pages'] for m in p['mentions']] == ['mention', None, None]
    page = report['pages'][0]
    assert [(r['id'], r['source_region_id']) for r in page['regions']] == [
        (region.id, source.id if region is linked else None) for region in first.regions]
    linked_face, no_metadata, no_page_identity, no_identity = page['faces']
    assert linked_face == {
        'id': linked.id, 'name': 'Linked face', 'entity_id': 'face', 'source_region_id': source.id,
        'landmarks': {'left_eye_position': {'x': 1, 'y': 2}, 'right_eye_position': {'x': 3, 'y': 4},
                      'nose_position': None, 'left_mouth_corner_position': {'x': 5, 'y': 6},
                      'right_mouth_corner_position': {'x': 7, 'y': 8}},
    }
    for unlinked in (no_metadata, no_page_identity, no_identity):
        assert unlinked['name'] is None and unlinked['entity_id'] is None and unlinked['source_region_id'] is None
    assert no_metadata['landmarks'] == dict.fromkeys(linked_face['landmarks'])
    assert no_page_identity['landmarks']['nose_position'] == no_identity['landmarks']['nose_position'] == {'x': 10, 'y': 10}


@pytest.mark.parametrize('mode', ['cli', 'ini', 'override', 'empty', 'absent', 'disable'])
def test_cli_configuration_and_resume_outputs(tmp_path, monkeypatch, mode):
    from people_gator.core import document_parser
    from user_scripts import parse_folder
    source_dir = tmp_path / 'input'
    source_dir.mkdir()
    source = Path(__file__).parent / 'resources' / 'text_chunking' / 'input.page.xml'
    shutil.copyfile(source, source_dir / 'input.xml')
    config = ConfigParser()
    config.read_dict({'PARSE_FOLDER': {'INPUT_XML_PATH': str(source_dir)},
                     'ENGINE_A': {'METHOD': 'TEXT_ENTITY_DETECTION'},
                     'ENGINE_B': {'METHOD': 'TEXT_ENTITY_DETECTION'}})
    ini_dir = tmp_path / 'ini-checkpoints'
    cli_dir = tmp_path / 'cli-checkpoints'
    if mode in ('ini', 'override', 'disable'): config['PARSE_FOLDER']['PROCESSING_CHECKPOINTS'] = str(ini_dir)
    if mode == 'empty': config['PARSE_FOLDER']['PROCESSING_CHECKPOINTS'] = ''
    config_path = tmp_path / 'pipeline.ini'
    with config_path.open('w') as target: config.write(target)
    engines = []
    def factory(*args, **kwargs):
        engine = Mock()
        engine.process_document.side_effect = lambda d: d
        engines.append(engine)
        return engine
    monkeypatch.setattr(document_parser, 'engine_factory', factory)
    args = ['peoplegator', '--config', str(config_path), '--output-xml-path', str(tmp_path / 'output')]
    if mode in ('cli', 'override'): args += ['--processing-checkpoints=' + str(cli_dir)]
    if mode == 'disable': args += ['--processing-checkpoints', '']
    monkeypatch.setattr(sys, 'argv', args)
    assert parse_folder.main() == 0
    expected = cli_dir if mode in ('cli', 'override') else ini_dir
    paths = sorted(expected.rglob('checkpoint.json'))
    assert len(paths) == (2 if mode in ('cli', 'ini', 'override') else 0)
    if mode in ('cli', 'override', 'empty', 'absent', 'disable'):
        assert not ini_dir.exists()
    if paths:
        monkeypatch.setattr(parse_folder, 'load_document', Mock(side_effect=AssertionError('must not reload XML')))
        monkeypatch.setattr(sys, 'argv', ['peoplegator', '--config', str(config_path),
            '--resume-from-checkpoint', str(paths[0]), '--processing-checkpoints', '',
            '--output-xml-path', str(tmp_path / 'resumed')])
        assert parse_folder.main() == 0
        assert [e.process_document.call_count for e in engines[-2:]] == [0, 1]
        from lxml import etree
        original = next((tmp_path / 'output').glob('*.xml'))
        resumed = next((tmp_path / 'resumed').glob('*.xml'))
        def normalized(path):
            tree = etree.parse(str(path))
            for element in tree.findall('.//{*}Metadata'): element.getparent().remove(element)
            return etree.tostring(tree, method='c14n')
        assert normalized(original) == normalized(resumed)
        assert len(list(expected.rglob('checkpoint.json'))) == 2


@pytest.mark.parametrize('fmt', ['alto', 'page'])
def test_real_linking_receipts_and_completed_linker_not_called(tmp_path, monkeypatch, fmt):
    from test_entity_matching import document, decision
    from people_gator.core.document_parser import DocumentParser, engine_factory
    from people_gator.core import document_parser
    prompt = tmp_path / 'link.json'
    prompt.write_text(json.dumps({'user': '{{ name }} {{ context }} {{ entities }}'}))
    config = ConfigParser()
    config.read_dict({'PARSE_FOLDER': {'PROCESSING_CHECKPOINTS': str(tmp_path / 'snapshots')},
        'ENGINE_LINK': {'METHOD': 'ENTITY_MATCHING', 'PROMPT_TEMPLATE_PATH': str(prompt),
                        'API_KEY': 'private-key-123456', 'API_URL': 'https://example.invalid', 'MODEL_NAME': 'mock'}})
    db = Mock()
    db.search_entities.return_value = {'items': []}
    db.create_entity.return_value = {'entity_id': 'created'}
    engine = engine_factory(config['ENGINE_LINK'], str(tmp_path), 'cpu', db)
    engine.llm_prompter = Mock(return_value=decision('create'))
    monkeypatch.setattr(document_parser, 'engine_factory', Mock(return_value=engine))
    parser = DocumentParser(config, 'cpu', str(tmp_path))
    parser.process_document(document(fmt))
    assert db.create_entity.call_count == 1
    path, = snapshots(tmp_path)
    engine.process_document = Mock(side_effect=AssertionError('completed linker must not rerun'))
    restored = parser.process_document(None, resume_from_checkpoint=path)
    cluster = restored.text_entity_clusters[0]
    assert restored.entity_linking_journal[0]['targets'][0] is cluster
    assert cluster.identity.peoplegator_id == 'created'
    assert db.create_entity.call_count == 1
