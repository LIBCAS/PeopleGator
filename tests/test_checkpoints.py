"""Complete graph snapshots and conservative recovery without live services."""

from configparser import ConfigParser
from copy import deepcopy
from datetime import datetime, timezone
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
from unittest.mock import Mock
from uuid import uuid4

import pytest


@pytest.fixture(autouse=True)
def processing_only(runtime_mode):
    if runtime_mode == 'client':
        pytest.skip('Checkpoint tests require processing extras')


def rich_document(fmt='alto'):
    import numpy as np
    from scipy.sparse import csc_matrix
    from anno_page.core.layout import AnnoPageRegionLayout
    from anno_page.core.metadata import GraphicalObjectMetadata, RelatedLinesMetadata, ColorInfo, DominantColorInfo
    from anno_page.enums import Language, LineRelation
    from people_gator.core.layout import (PeopleGatorDocument, PeopleGatorPageLayout,
        PeopleGatorIdentity, PeopleGatorPageIdentity, PeopleGatorTextEntityMention,
        PeopleGatorTextEntityCluster, PeopleGatorFaceMetadata, PeopleGatorFaceRegionLayout, Position)
    from people_gator.text import SourceLine, SourceSpan
    pages = []
    person = PeopleGatorIdentity('Karel Čapek', 'app-person', {'wikidata': 'Q155855'})
    mentions = []
    for index in range(2):
        page = PeopleGatorPageLayout()
        source = Path(__file__).parent / 'resources' / 'text_chunking' / f'input.{fmt}.xml'
        getattr(page, 'from_altoxml' if fmt == 'alto' else 'from_pagexml')(str(source))
        page.id = f'p{index}'
        line = page.regions[0].lines[0]
        line.transcription = 'Karel Čapek, český spisovatel.\n'
        line.index = 7
        line.heights = np.array([3.2, 4.5], dtype=np.float32)
        line.character_confidences = np.array([.7, .8, .9])
        line.transcription_confidence = np.float32(.9876)
        line.logits = csc_matrix(np.array([[0., -1.25], [-2., 0.]], dtype=np.float32))
        line.characters = ['Č', 'a']
        line.logit_coords = [(1, 2), (None, None)]
        line.crop = np.full((12, 14, 3), 72 + index, dtype=np.uint8)
        line.embeddings = [np.array([.1, float('nan'), float('-inf')])]
        line.metadata = {'source': 'OCR', 'uuid': uuid4(), 'time': datetime(2026, 1, 1, tzinfo=timezone.utc)}
        page.confidence = .981
        page.reading_order = {region: i for i, region in enumerate(page.regions)}
        wrapper = PeopleGatorPageIdentity('person', 'MODS_PERSON', person,
                    used_ai_models={'manual': 'reviewed'}, confidence=.9)
        span = SourceSpan(SourceLine(index, page.id, 0, page.regions[0].id, 0, line.id), 0, 11)
        mention = PeopleGatorTextEntityMention('Karel Čapek', line.transcription, line, (0, 11), wrapper,
                                             (span,), 'Karel Čapek', 'spisovatel')
        page.text_entities.append(mention)
        mentions.append(mention)
        caption = RelatedLinesMetadata('caption', 'MODS_CAPTION', [line], LineRelation.CAPTION,
                    title={Language.CZECH: 'Spisovatel'}, description='Původní popisek')
        metadata = GraphicalObjectMetadata('photo', 'MODS_PHOTO', creation_date_time='2026-01-01',
                    tag_description='source', caption={Language.CZECH: 'Čapek'},
                    topics={Language.ENGLISH: ['literature']}, color=ColorInfo('RGB', [DominantColorInfo('red', .3)]),
                    description={Language.CZECH: 'Portrét'}, title='Portrét', caption_lines_metadata=caption,
                    reference_lines_metadata=RelatedLinesMetadata('ref', 'MODS_REF', [line], LineRelation.REFERENCE),
                    continuing_line=line, prompts=['describe this'], used_ai_models={'model': 'v1'}, confidence=.876)
        photo = AnnoPageRegionLayout('source', np.array([[0, 0], [10, 0], [10, 10], [0, 10]]),
                                     'illustration', 'Photograph', .876, metadata)
        photo.metadata = {'annotation': ['original', 'unchanged']}
        photo.embeddings = [np.array([1., 2.])]
        page.regions.append(photo)
        face_meta = PeopleGatorFaceMetadata('face', 'MODS_FACE', wrapper, *[Position(i, i + .5) for i in range(5)])
        page.regions.append(PeopleGatorFaceRegionLayout('face', photo.polygon.copy(), face_meta, photo,
                                                      category='face', detection_confidence=.98))
        page.metadata = {'owner': page, 'custom': {'source': 'original', 'ordered': ['b', 'a']}}
        pages.append(page)
    cluster = PeopleGatorTextEntityCluster(mentions, person, 'Karel Čapek', 'Český spisovatel', 'spisovatel')
    doc = PeopleGatorDocument('document', 'Příloha', 'library', pages, text_entity_clusters=[cluster])
    doc.source_metadata = {'document': {'custom': [1, 2]}, 'original': 'all preserved'}
    doc.entity_linking_journal = [{'state': 'created', 'targets': (cluster, person),
                                 'source': {'name': 'Karel Čapek', 'aliases': []}, 'entity_id': 'app-person'}]
    doc.extra = {'blob': b'\x00\xff', 'mutable': bytearray(b'xy'), 'empty': (), 'set': frozenset({1, 2}),
                 'scalar': np.int16(9), 'path': Path('source'), 'nonfinite': float('inf')}
    return doc


def assert_graph_equal(original, restored, mapping=None):
    """Compare every field and the alias graph, including inherited data."""
    import numpy as np
    from enum import Enum
    import inspect
    if mapping is None:
        mapping = {}
    assert type(original) is type(restored)
    if original is None or type(original) in (str, int, bool, float, bytes) or isinstance(original, (Enum, np.generic)):
        if isinstance(original, float) and np.isnan(original):
            assert np.isnan(restored)
        else:
            assert original == restored
        return
    if inspect.isfunction(original):
        assert original is restored
        return
    if id(original) in mapping:
        assert mapping[id(original)] is restored
        return
    assert all(value is not restored for value in mapping.values())
    mapping[id(original)] = restored
    if type(original) is np.ndarray:
        assert original.dtype == restored.dtype
        assert original.shape == restored.shape
        assert original.flags.writeable == restored.flags.writeable
        np.testing.assert_array_equal(original, restored)
    elif isinstance(original, dict):
        assert len(original) == len(restored)
        for (key, value), (other_key, other_value) in zip(original.items(), restored.items()):
            assert_graph_equal(key, other_key, mapping)
            assert_graph_equal(value, other_value, mapping)
    elif isinstance(original, (list, tuple)):
        assert len(original) == len(restored)
        for value, other in zip(original, restored):
            assert_graph_equal(value, other, mapping)
    elif isinstance(original, (set, frozenset, Path, datetime, bytearray)) or not hasattr(original, '__dict__'):
        assert original == restored
    else:
        assert vars(original).keys() == vars(restored).keys()
        for key in vars(original):
            assert_graph_equal(vars(original)[key], vars(restored)[key], mapping)


@pytest.mark.parametrize('fmt', ['alto', 'page'])
def test_entire_graph_round_trip(fmt):
    from people_gator.core.checkpoint_graph import GraphEncoder, restore_document
    doc = rich_document(fmt)
    graph = GraphEncoder().document(doc)
    restored = restore_document(json.loads(json.dumps(graph, allow_nan=False)))
    assert_graph_equal(doc, restored)
    page = restored.page_layouts[0]
    assert page.faces[0].source_region is page.regions[-2]
    assert page.regions[-2].graphical_metadata.caption_lines_metadata.lines[0] is page.regions[0].lines[0]
    assert restored.text_entity_clusters[0].text_entities[0] is page.text_entities[0]
    assert page.faces[0].face_metadata.page_identity.identity is restored.text_entity_clusters[0].identity
    assert restored.entity_linking_journal[0]['targets'][0] is restored.text_entity_clusters[0]


@pytest.mark.parametrize('empty_pages', [0, 1, 3])
def test_empty_document_round_trip(empty_pages):
    from people_gator.core.layout import PeopleGatorDocument, PeopleGatorPageLayout
    from people_gator.core.checkpoint_graph import GraphEncoder, restore_document
    doc = PeopleGatorDocument(page_layouts=[PeopleGatorPageLayout(str(i)) for i in range(empty_pages)])
    assert_graph_equal(doc, restore_document(GraphEncoder().document(doc)))


def pipeline(tmp_path, monkeypatch, methods=('TEXT_ENTITY_DETECTION',) * 3, directory=True):
    from people_gator.core import document_parser
    cfg = ConfigParser()
    cfg.read_dict({'PARSE_FOLDER': {'PROCESSING_CHECKPOINTS': str(tmp_path / 'snapshots') if directory else ''}})
    engines = []
    for index, method in enumerate(methods):
        cfg[f'ENGINE_{index}'] = {'METHOD': method, 'API_KEY': 'sensitive-credential-012345', 'MODEL_NAME': 'test-model'}
        engine = Mock()
        engine.process_document.side_effect = lambda doc, i=index: mark(doc, i)
        engines.append(engine)
    monkeypatch.setattr(document_parser, 'engine_factory', Mock(side_effect=engines))
    return document_parser.DocumentParser(cfg, 'cpu', str(tmp_path)), engines, cfg


def mark(doc, ordinal):
    if doc.source_metadata is None:
        doc.source_metadata = {}
    doc.source_metadata.setdefault('stages', []).append(ordinal)
    return doc


def snapshots(tmp_path):
    return sorted((tmp_path / 'snapshots').rglob('*.checkpoint.json'))


def resign(data):
    from people_gator.core.checkpoints import _digest
    data.pop('integrity_sha256', None)
    data['integrity_sha256'] = _digest(data)
    return data


@pytest.mark.parametrize('fmt', ['alto', 'page'])
@pytest.mark.parametrize('resume_index', [0, 1, 2])
def test_resume_each_boundary_matches_uninterrupted(tmp_path, monkeypatch, fmt, resume_index):
    parser, engines, config = pipeline(tmp_path, monkeypatch)
    full = parser.process_document(rich_document(fmt))
    original_paths = snapshots(tmp_path)
    assert len(original_paths) == 3
    payloads = [json.loads(p.read_text()) for p in original_paths]
    assert [p['last_completed'] for p in payloads] == [0, 1, 2]
    assert [p['completed_steps'][-1]['section'] for p in payloads] == ['ENGINE_0', 'ENGINE_1', 'ENGINE_2']
    assert all(p['schema_version'] == 1 for p in payloads)
    for engine in engines:
        engine.process_document.reset_mock()
    restored = parser.process_document(None, resume_from_checkpoint=original_paths[resume_index])
    assert_graph_equal(full, restored)
    assert [e.process_document.call_count for e in engines] == [int(i > resume_index) for i in range(3)]
    assert len(snapshots(tmp_path)) == 3 + 2 - resume_index
    assert [json.loads(p.read_text()) for p in original_paths] == payloads
    latest = json.loads((Path(payloads[0]['run_directory']) / 'latest.json').read_text())
    assert Path(latest['checkpoint']).exists()


def test_disabled_mode_and_distinct_runs(tmp_path, monkeypatch):
    parser, engines, config = pipeline(tmp_path, monkeypatch, directory=False)
    doc = rich_document()
    doc.unsupported = object()
    assert parser.process_document(doc) is doc
    assert not (tmp_path / 'snapshots').exists()
    del doc.unsupported
    config['PARSE_FOLDER']['PROCESSING_CHECKPOINTS'] = str(tmp_path / 'snapshots')
    parser.process_document(doc)
    parser.process_document(doc)
    files = snapshots(tmp_path)
    assert len(files) == 6
    assert len({json.loads(p.read_text())['run_id'] for p in files}) == 2


def test_engine_failure_preserves_last_good_snapshot(tmp_path, monkeypatch):
    from people_gator.core.checkpoint_graph import restore_document
    parser, engines, config = pipeline(tmp_path, monkeypatch)
    def fail(doc):
        doc.source_metadata['partial'] = True
        raise RuntimeError('engine failed')
    engines[1].process_document.side_effect = fail
    with pytest.raises(RuntimeError, match='engine failed'):
        parser.process_document(rich_document())
    paths = snapshots(tmp_path)
    assert len(paths) == 1
    payload = json.loads(paths[0].read_text())
    assert payload['next_step'] == 1
    assert 'partial' not in restore_document(payload['document']).source_metadata
    engines[1].process_document.side_effect = lambda d: mark(d, 1)
    assert parser.process_document(None, resume_from_checkpoint=paths[0]).source_metadata['stages'] == [0, 1, 2]


def test_atomic_failure_preserves_snapshot_and_completion(tmp_path, monkeypatch):
    from people_gator.core import checkpoints
    parser, engines, config = pipeline(tmp_path, monkeypatch)
    replace = checkpoints.os.replace
    def fail_second(source, destination):
        if Path(destination).name.startswith('0002-'):
            raise OSError('private path and payload')
        replace(source, destination)
    monkeypatch.setattr(checkpoints.os, 'replace', fail_second)
    with pytest.raises(checkpoints.CheckpointError, match='write failed'):
        parser.process_document(rich_document())
    paths = snapshots(tmp_path)
    assert len(paths) == 1
    assert json.loads(paths[0].read_text())['next_step'] == 1
    assert not list((tmp_path / 'snapshots').rglob('*.tmp'))
    monkeypatch.setattr(checkpoints.os, 'replace', replace)
    assert parser.process_document(None, resume_from_checkpoint=paths[0]).source_metadata['stages'] == [0, 1, 2]


@pytest.mark.parametrize('damage', ['json', 'version', 'digest', 'history', 'next', 'field', 'reference', 'document', 'model', 'duplicate'])
def test_reject_corrupt_snapshots(tmp_path, monkeypatch, damage):
    from people_gator.core.checkpoints import CheckpointError
    parser, engines, config = pipeline(tmp_path, monkeypatch)
    parser.process_document(rich_document())
    path = snapshots(tmp_path)[0]
    data = json.loads(path.read_text())
    if damage == 'version': data['schema_version'] = 999
    if damage == 'digest': data['next_step'] = 7
    if damage == 'history': data['completed_steps'][0]['section'] = 'ENGINE_2'
    if damage == 'next': data['next_step'] = True
    if damage == 'document': data['document_identity'][0] = 'different'
    if damage == 'model': data['model_identity'] = {}
    if damage in ('field', 'reference'):
        fields = data['document']['objects'][0]['fields']
        if damage == 'field': del fields['page_layouts']
        else: fields['page_layouts'] = {'ref': 999999}
    raw = json.dumps(data if damage == 'digest' else resign(data))
    if damage == 'json': raw = '{"private":'
    if damage == 'duplicate': raw = '{"schema_version":1,"schema_version":2}'
    path.write_text(raw)
    for engine in engines: engine.process_document.reset_mock()
    with pytest.raises(CheckpointError):
        parser.process_document(None, resume_from_checkpoint=path)
    assert not any(e.process_document.called for e in engines)


@pytest.mark.parametrize('change', ['order', 'method', 'setting', 'prompt', 'credential_missing'])
def test_configuration_and_resource_compatibility(tmp_path, monkeypatch, change):
    from people_gator.core.checkpoints import CheckpointError
    parser, engines, config = pipeline(tmp_path, monkeypatch)
    prompt = tmp_path / 'prompt.json'
    prompt.write_text('{"user":"original"}')
    config['ENGINE_0']['PROMPT_TEMPLATE_PATH'] = str(prompt)
    parser.process_document(rich_document())
    path = snapshots(tmp_path)[0]
    if change == 'order':
        values = dict(config['ENGINE_0'])
        config.remove_section('ENGINE_0')
        config['ENGINE_0'] = values
    if change == 'method': config['ENGINE_0']['METHOD'] = 'ENTITY_MATCHING'
    if change == 'setting': config['ENGINE_0']['MODEL_NAME'] = 'changed'
    if change == 'prompt': prompt.write_text('{"user":"changed"}')
    if change == 'credential_missing': config['ENGINE_0']['API_KEY'] = ''
    with pytest.raises(CheckpointError, match='changed'):
        parser.process_document(None, resume_from_checkpoint=path)


def test_credentials_and_logs_are_private(tmp_path, monkeypatch, caplog):
    from people_gator.core.checkpoints import CheckpointError
    parser, engines, config = pipeline(tmp_path, monkeypatch)
    parser.process_document(rich_document())
    path = snapshots(tmp_path)[0]
    assert 'sensitive-credential-012345' not in path.read_text()
    assert 'sensitive-credential-012345' not in caplog.text
    assert str(tmp_path / 'snapshots') not in caplog.text
    assert path.stat().st_mode & 0o777 == 0o600
    assert path.parent.stat().st_mode & 0o777 == 0o700
    config['ENGINE_0']['API_KEY'] = 'replacement-credential-987654'
    parser.process_document(None, resume_from_checkpoint=path)
    doc = rich_document()
    doc.source_metadata['accidental'] = config['ENGINE_0']['API_KEY']
    with pytest.raises(CheckpointError, match='Credential found'):
        parser.process_document(doc)
    assert all('replacement-credential-987654' not in p.read_text() for p in snapshots(tmp_path))


def test_unknown_fields_and_handlers_fail_before_engine(tmp_path, monkeypatch):
    from people_gator.core.checkpoints import CheckpointError
    parser, engines, config = pipeline(tmp_path, monkeypatch)
    for add in (lambda d: setattr(d, 'extra', object()),
                lambda d: d.page_layouts[0].to_pagexml_started.__iadd__(lambda *args: None)):
        doc = rich_document()
        add(doc)
        with pytest.raises(CheckpointError, match='Unsupported'):
            parser.process_document(doc)
    assert not any(e.process_document.called for e in engines)


@pytest.mark.parametrize('fmt', ['alto', 'page'])
@pytest.mark.parametrize('cached', [False, True])
def test_assets_lazy_and_modified_images_and_relocation(tmp_path, monkeypatch, fmt, cached):
    import cv2
    import numpy as np
    from people_gator.core.layout import PeopleGatorDocument
    from people_gator.core.checkpoints import CheckpointError
    parser, engines, config = pipeline(tmp_path, monkeypatch)
    image_dir = tmp_path / 'images'
    xml_dir = tmp_path / 'xml'
    image_dir.mkdir(); xml_dir.mkdir()
    source = Path(__file__).parent / 'resources' / 'text_chunking' / f'input.{fmt}.xml'
    shutil.copyfile(source, xml_dir / 'input.xml')
    metadata = tmp_path / 'metadata.json'
    metadata.write_text(json.dumps({'document': {'id': 'original'}, 'custom': {'keep': 'entire metadata'}}))
    doc = PeopleGatorDocument(page_images_dir=str(image_dir), metadata_path=str(metadata),
        **{'alto_xmls_dir' if fmt == 'alto' else 'page_xmls_dir': str(xml_dir)})
    page = doc.page_layouts[0]
    image_path = image_dir / f'{page.id}.jpg'
    cv2.imwrite(str(image_path), np.full((20, 30, 3), 40, np.uint8))
    if cached:
        image = doc.get_page_image(page)
        image[0, 0] = [0, 128, 255]
        doc.page_images[page.id] = image
    parser.process_document(doc)
    path = snapshots(tmp_path)[0]
    restored = parser.process_document(None, resume_from_checkpoint=path)
    assert restored.source_metadata['custom'] == {'keep': 'entire metadata'}
    assert_graph_equal(doc.get_page_image(page), restored.get_page_image(restored.page_layouts[0]))
    relocated = tmp_path / 'relocated-images'
    shutil.copytree(image_dir, relocated)
    config['PARSE_FOLDER']['INPUT_IMAGE_PATH'] = str(relocated)
    image_path.unlink()
    parser.process_document(None, resume_from_checkpoint=path)
    (relocated / image_path.name).write_bytes(b'changed')
    with pytest.raises(CheckpointError, match='input changed'):
        parser.process_document(None, resume_from_checkpoint=path)
    config['PARSE_FOLDER']['INPUT_IMAGE_PATH'] = str(image_dir)
    with pytest.raises(CheckpointError, match='missing'):
        parser.process_document(None, resume_from_checkpoint=path)


@pytest.mark.parametrize('hazard', ['crash', 'checkpoint_failure', 'old_snapshot'])
def test_uncertain_app_stage_is_never_replayed(tmp_path, monkeypatch, hazard):
    from people_gator.core import checkpoints
    parser, engines, config = pipeline(tmp_path, monkeypatch,
        methods=('TEXT_ENTITY_CLUSTERING', 'ENTITY_MATCHING', 'TEXT_ENTITY_DETECTION'))
    creates = Mock()
    def linking(doc):
        creates()
        if hazard == 'crash': raise RuntimeError('connection lost after create')
        return mark(doc, 1)
    engines[1].process_document.side_effect = linking
    replace = checkpoints.os.replace
    def fail_checkpoint(source, destination):
        if Path(destination).name.startswith('0002-'): raise OSError('interrupted')
        replace(source, destination)
    if hazard == 'checkpoint_failure': monkeypatch.setattr(checkpoints.os, 'replace', fail_checkpoint)
    if hazard != 'old_snapshot':
        with pytest.raises((RuntimeError, checkpoints.CheckpointError)):
            parser.process_document(rich_document())
    else: parser.process_document(rich_document())
    first = snapshots(tmp_path)[0]
    with pytest.raises(checkpoints.CheckpointError, match='reconcile manually'):
        parser.process_document(None, resume_from_checkpoint=first)
    assert creates.call_count == 1
    if hazard == 'old_snapshot':
        second = snapshots(tmp_path)[1]
        parser.process_document(None, resume_from_checkpoint=second)
        assert creates.call_count == 1


def test_export_repeat_and_missing_ledger_are_blocked(tmp_path, monkeypatch):
    from people_gator.core import document_parser, checkpoints
    parser, engines, config = pipeline(tmp_path, monkeypatch)
    parser.db_api_service = Mock()
    exported = Mock()
    imported = Mock(side_effect=lambda d, db: d)
    monkeypatch.setattr(document_parser, 'export_document', exported)
    monkeypatch.setattr(document_parser, 'import_document', imported)
    parser.process_document(rich_document(), import_from_app=True, export_to_app=True)
    path = snapshots(tmp_path)[-1]
    with pytest.raises(checkpoints.CheckpointError, match='export was already attempted'):
        parser.process_document(None, import_from_app=True, export_to_app=True, resume_from_checkpoint=path)
    parser.process_document(None, import_from_app=True, export_to_app=False, resume_from_checkpoint=path)
    assert imported.call_count == exported.call_count == 1
    ledger = Path(json.loads(path.read_text())['run_directory']) / 'run-state.json'
    ledger.unlink()
    with pytest.raises(checkpoints.CheckpointError, match='ledger'):
        parser.process_document(None, import_from_app=True, resume_from_checkpoint=path)


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
    paths = sorted(expected.rglob('*.checkpoint.json'))
    assert len(paths) == (2 if mode in ('cli', 'ini', 'override') else 0)
    assert not ini_dir.exists() if mode == 'override' else True
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
        assert len(list(expected.rglob('*.checkpoint.json'))) == 2


def test_token_limit_is_nonsecret_compatibility_setting(tmp_path, monkeypatch):
    from people_gator.core.checkpoints import CheckpointError
    parser, engines, config = pipeline(tmp_path, monkeypatch)
    config['ENGINE_0']['MAX_OUTPUT_TOKENS'] = '6000'
    config['ENGINE_0']['ACCESS_TOKEN'] = 'private-access-token-123456'
    parser.process_document(rich_document())
    path = snapshots(tmp_path)[0]
    assert 'private-access-token-123456' not in path.read_text()
    settings = json.loads(path.read_text())['initial_configuration'][1]['settings']
    assert settings['max_output_tokens'] == '6000'
    config['ENGINE_0']['MAX_OUTPUT_TOKENS'] = '1000'
    with pytest.raises(CheckpointError, match='changed'):
        parser.process_document(None, resume_from_checkpoint=path)


def test_abrupt_write_leaves_only_finalized_snapshot_usable(tmp_path, monkeypatch):
    from people_gator.core import checkpoints
    parser, engines, config = pipeline(tmp_path, monkeypatch)
    parser.process_document(rich_document())
    path = snapshots(tmp_path)[0]
    previous = path.read_bytes()
    script = '''
import os, sys
from pathlib import Path
from people_gator.core import checkpoints
path = Path(sys.argv[1])
def crash(source, destination):
    os._exit(79)
checkpoints.os.replace = crash
checkpoints.atomic_json(path, {"partial": "write"})
'''
    result = subprocess.run([sys.executable, '-c', script, str(path)], capture_output=True)
    assert result.returncode == 79
    assert path.read_bytes() == previous
    temporary, = path.parent.glob('*.tmp')
    with pytest.raises(checkpoints.CheckpointError, match='finalized'):
        parser.process_document(None, resume_from_checkpoint=temporary)
    parser.process_document(None, resume_from_checkpoint=path)


def test_concurrent_resume_lock_and_foreign_document(tmp_path, monkeypatch):
    from people_gator.core.checkpoints import CheckpointError, _run_lock
    from people_gator.core.layout import PeopleGatorDocument
    parser, engines, config = pipeline(tmp_path, monkeypatch)
    parser.process_document(rich_document())
    path = snapshots(tmp_path)[0]
    with pytest.raises(CheckpointError, match='different document'):
        parser.process_document(PeopleGatorDocument(id='foreign'), resume_from_checkpoint=path)
    lock = Path(json.loads(path.read_text())['run_directory']) / '.lock'
    with _run_lock(lock):
        with pytest.raises(CheckpointError, match='already active'):
            parser.process_document(None, resume_from_checkpoint=path)


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
    full = parser.process_document(document(fmt))
    assert db.create_entity.call_count == 1
    path, = snapshots(tmp_path)
    engine.process_document = Mock(side_effect=AssertionError('completed linker must not rerun'))
    restored = parser.process_document(None, resume_from_checkpoint=path)
    assert_graph_equal(full, restored)
    cluster = restored.text_entity_clusters[0]
    assert restored.entity_linking_journal[0]['targets'][0] is cluster
    assert cluster.identity.peoplegator_id == 'created'
    assert db.create_entity.call_count == 1


@pytest.mark.parametrize('damage', ['missing', 'modified', 'extra'])
def test_xml_dependencies_checked_without_reimport(tmp_path, monkeypatch, damage):
    from people_gator.core.layout import PeopleGatorDocument
    from people_gator.core.checkpoints import CheckpointError
    parser, engines, config = pipeline(tmp_path, monkeypatch)
    source = Path(__file__).parent / 'resources' / 'text_chunking' / 'input.page.xml'
    directory = tmp_path / 'xml'
    directory.mkdir()
    xml = directory / 'input.xml'
    shutil.copyfile(source, xml)
    parser.process_document(PeopleGatorDocument(page_xmls_dir=str(directory)))
    path = snapshots(tmp_path)[0]
    if damage == 'missing': xml.unlink()
    if damage == 'modified': xml.write_text('<changed/>')
    if damage == 'extra': shutil.copyfile(source, directory / 'extra.xml')
    with pytest.raises(CheckpointError, match='input|XML input set'):
        parser.process_document(None, resume_from_checkpoint=path)


def test_failed_export_is_fenced_before_any_retry(tmp_path, monkeypatch):
    from people_gator.core import document_parser
    from people_gator.core.checkpoints import CheckpointError
    parser, engines, config = pipeline(tmp_path, monkeypatch)
    parser.db_api_service = Mock()
    exported = Mock(side_effect=RuntimeError('partial export'))
    monkeypatch.setattr(document_parser, 'export_document', exported)
    with pytest.raises(RuntimeError, match='partial export'):
        parser.process_document(rich_document(), export_to_app=True, drop_existing_annotations=True)
    path = snapshots(tmp_path)[-1]
    with pytest.raises(CheckpointError, match='manual reconciliation'):
        parser.process_document(None, export_to_app=True, drop_existing_annotations=True, resume_from_checkpoint=path)
    assert exported.call_count == 1
    parser.process_document(None, resume_from_checkpoint=path)


def test_unknown_engine_and_moved_resource(tmp_path, monkeypatch):
    from people_gator.core import document_parser
    from people_gator.core.checkpoints import CheckpointError
    parser, engines, config = pipeline(tmp_path, monkeypatch)
    resource = tmp_path / 'original.json'
    resource.write_text('{}')
    config['ENGINE_0']['PROMPT_TEMPLATE_PATH'] = str(resource)
    parser.process_document(rich_document())
    path = snapshots(tmp_path)[0]
    moved = tmp_path / 'moved.json'
    resource.rename(moved)
    config['ENGINE_0']['PROMPT_TEMPLATE_PATH'] = str(moved)
    parser.process_document(None, resume_from_checkpoint=path)
    config['ENGINE_UNKNOWN'] = {'METHOD': 'UNKNOWN'}
    monkeypatch.setattr(document_parser, 'engine_factory', Mock(return_value=None))
    invalid = document_parser.DocumentParser(config, 'cpu', str(tmp_path))
    with pytest.raises(CheckpointError, match='load successfully'):
        invalid.process_document(rich_document())


def test_device_change_and_uncertain_receipt_require_reconciliation(tmp_path, monkeypatch):
    from people_gator.core.checkpoints import CheckpointError
    parser, engines, config = pipeline(tmp_path, monkeypatch)
    parser.process_document(rich_document())
    path = snapshots(tmp_path)[0]
    parser.device = 'cuda:0'
    with pytest.raises(CheckpointError, match='device changed'):
        parser.process_document(None, resume_from_checkpoint=path)
    parser.device = 'cpu'
    doc = rich_document()
    doc.entity_linking_journal[0]['state'] = 'uncertain'
    with pytest.raises(CheckpointError, match='manual reconciliation'):
        parser.process_document(doc)


@pytest.mark.parametrize('sparse_format', ['csr', 'coo'])
def test_sparse_ocr_formats_preserve_all_fields(sparse_format):
    from people_gator.core.checkpoint_graph import GraphEncoder, restore_document
    doc = rich_document()
    line = doc.page_layouts[0].regions[0].lines[0]
    line.logits = line.logits.asformat(sparse_format)
    assert_graph_equal(doc, restore_document(GraphEncoder().document(doc)))


def test_killed_app_engine_leaves_durable_fence_and_releases_lock(tmp_path, monkeypatch):
    from people_gator.core.checkpoints import CheckpointError
    parser, engines, config = pipeline(tmp_path, monkeypatch,
        methods=('TEXT_ENTITY_DETECTION', 'ENTITY_MATCHING'))
    # Save only the pure first stage; the initial linker has not run or written.
    engines[1].process_document.side_effect = RuntimeError('before app operation')
    # Generate that first snapshot without invoking a side-effect stage in parent.
    from people_gator.core.checkpoints import CheckpointRun
    doc = rich_document()
    run = CheckpointRun(config, str(tmp_path), str(tmp_path / 'snapshots'),
        dict(import_from_app=False, export_to_app=False, drop_existing_annotations=False, device='cpu'), document=doc)
    with run.locked(): run.save(mark(doc, 0), 0, .01)
    path, = snapshots(tmp_path)
    ini = tmp_path / 'crash.ini'
    with ini.open('w') as target: config.write(target)
    script = '''
import os, sys
from configparser import ConfigParser
from unittest.mock import Mock
from people_gator.core import document_parser
config = ConfigParser()
config.read(sys.argv[1])
engine = Mock()
engine.process_document.side_effect = lambda doc: os._exit(81)
document_parser.engine_factory = Mock(return_value=engine)
parser = document_parser.DocumentParser(config, 'cpu', '.')
parser.process_document(None, resume_from_checkpoint=sys.argv[2])
'''
    result = subprocess.run([sys.executable, '-c', script, str(ini), str(path)], capture_output=True)
    assert result.returncode == 81, result.stderr.decode()
    with pytest.raises(CheckpointError, match='reconcile manually'):
        parser.process_document(None, resume_from_checkpoint=path)


@pytest.mark.parametrize('damage', ['checksum', 'incomplete', 'identity'])
def test_damaged_ledger_cannot_authorize_replay(tmp_path, monkeypatch, damage):
    from people_gator.core.checkpoints import CheckpointError, _sealed
    parser, engines, config = pipeline(tmp_path, monkeypatch)
    parser.process_document(rich_document())
    path = snapshots(tmp_path)[0]
    ledger = Path(json.loads(path.read_text())['run_directory']) / 'run-state.json'
    data = json.loads(ledger.read_text())
    if damage == 'checksum': data['side_effect_step'] = 0
    if damage == 'incomplete': data = []
    if damage == 'identity':
        data.pop('integrity_sha256')
        data['run_id'] = str(uuid4())
        data = _sealed(data)
    ledger.write_text(json.dumps(data))
    for engine in engines: engine.process_document.reset_mock()
    with pytest.raises(CheckpointError, match='ledger'):
        parser.process_document(None, resume_from_checkpoint=path)
    assert not any(engine.process_document.called for engine in engines)


def test_metadata_timestamps_uuid_and_special_float_are_lossless():
    from datetime import date, timedelta
    from uuid import UUID, SafeUUID
    import struct
    from people_gator.core.checkpoint_graph import GraphEncoder, restore_document
    doc = rich_document()
    doc.extra['date'] = date(2026, 11, 12)
    doc.extra['time'] = datetime(2026, 11, 12, 1, 30, fold=1,
                                tzinfo=timezone(timedelta(hours=2), 'named-offset'))
    doc.extra['uuid'] = UUID(str(uuid4()), is_safe=SafeUUID.safe)
    doc.extra['nan'] = struct.unpack('!d', bytes.fromhex('fff8000000000001'))[0]
    restored = restore_document(GraphEncoder().document(doc))
    assert restored.extra['time'].fold == 1
    assert restored.extra['time'].tzname() == 'named-offset'
    assert restored.extra['uuid'].is_safe is SafeUUID.safe
    assert struct.pack('!d', restored.extra['nan']) == struct.pack('!d', doc.extra['nan'])
    assert_graph_equal(doc, restored)


@pytest.mark.parametrize('kind', ['object', 'structured', 'metadata', 'overlap', 'timezone'])
def test_unsupported_populated_values_fail_without_loss(kind):
    import numpy as np
    from zoneinfo import ZoneInfo
    from people_gator.core.checkpoint_graph import GraphEncoder, CheckpointError
    doc = rich_document()
    if kind == 'object': doc.extra['data'] = np.array([object()], dtype=object)
    if kind == 'structured': doc.extra['data'] = np.zeros(2, dtype=[('field', 'i4')])
    if kind == 'metadata': doc.extra['data'] = np.zeros(2, dtype=np.dtype('i4', metadata={'unit': 'pixel'}))
    if kind == 'overlap':
        array = np.arange(10)
        doc.extra['data'] = [array, array[2:]]
    if kind == 'timezone': doc.extra['data'] = datetime(2026, 11, 12, tzinfo=ZoneInfo('UTC'))
    with pytest.raises(CheckpointError, match='Unsupported|Overlapping'):
        GraphEncoder().document(doc)
