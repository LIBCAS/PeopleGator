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
    from people_gator.core.checkpoint_document import serialize_document, restore_document
    doc = rich_document(fmt)
    payload = serialize_document(doc)
    restored = restore_document(payload)
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
    from people_gator.core.checkpoint_document import serialize_document, restore_document
    doc = PeopleGatorDocument(page_layouts=[PeopleGatorPageLayout(str(i)) for i in range(empty_pages)])
    assert_graph_equal(doc, restore_document(serialize_document(doc)))


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
    return sorted((tmp_path / 'snapshots').rglob('checkpoint.json'))


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
    assert all(p['schema_version'] == 2 for p in payloads)
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
    from people_gator.core.checkpoint_document import restore_document
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
    assert 'partial' not in restore_document((paths[0].parent / 'document.pkl').read_bytes()).source_metadata
    engines[1].process_document.side_effect = lambda d: mark(d, 1)
    assert parser.process_document(None, resume_from_checkpoint=paths[0]).source_metadata['stages'] == [0, 1, 2]


def test_atomic_failure_preserves_snapshot_and_completion(tmp_path, monkeypatch):
    from people_gator.core import checkpoints
    parser, engines, config = pipeline(tmp_path, monkeypatch)
    replace = checkpoints.os.replace
    def fail_second(source, destination):
        if Path(destination).name == 'checkpoint.json' and Path(destination).parent.name.startswith('0002-'):
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


@pytest.mark.parametrize('damage', ['json', 'version', 'digest', 'history', 'next', 'document', 'duplicate'])
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
        with pytest.raises(CheckpointError, match='faithfully|Pickle|Unsupported'):
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
        if Path(destination).name == 'checkpoint.json' and Path(destination).parent.name.startswith('0002-'): raise OSError('interrupted')
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
    with pytest.raises(checkpoints.CheckpointError, match='ledger|protected local'):
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
    paths = sorted(expected.rglob('checkpoint.json'))
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
        assert len(list(expected.rglob('checkpoint.json'))) == 2


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
    from people_gator.core.checkpoint_document import serialize_document, restore_document
    doc = rich_document()
    line = doc.page_layouts[0].regions[0].lines[0]
    line.logits = line.logits.asformat(sparse_format)
    assert_graph_equal(doc, restore_document(serialize_document(doc)))


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
    with pytest.raises(CheckpointError, match='ledger|protected local'):
        parser.process_document(None, resume_from_checkpoint=path)
    assert not any(engine.process_document.called for engine in engines)


def test_metadata_timestamps_uuid_and_special_float_are_lossless():
    from datetime import date, timedelta
    from uuid import UUID, SafeUUID
    import struct
    from people_gator.core.checkpoint_document import serialize_document, restore_document
    doc = rich_document()
    doc.extra['date'] = date(2026, 11, 12)
    doc.extra['time'] = datetime(2026, 11, 12, 1, 30, fold=1,
                                tzinfo=timezone(timedelta(hours=2), 'named-offset'))
    doc.extra['uuid'] = UUID(str(uuid4()), is_safe=SafeUUID.safe)
    doc.extra['nan'] = struct.unpack('!d', bytes.fromhex('fff8000000000001'))[0]
    restored = restore_document(serialize_document(doc))
    assert restored.extra['time'].fold == 1
    assert restored.extra['time'].tzname() == 'named-offset'
    assert restored.extra['uuid'].is_safe is SafeUUID.safe
    assert struct.pack('!d', restored.extra['nan']) == struct.pack('!d', doc.extra['nan'])
    assert_graph_equal(doc, restored)


@pytest.mark.parametrize('kind', ['structured', 'metadata', 'timezone'])
def test_native_pickle_supports_metadata_previously_needing_json_adapters(kind):
    import numpy as np
    from zoneinfo import ZoneInfo
    from people_gator.core.checkpoint_document import serialize_document, restore_document
    doc = rich_document()
    if kind == 'structured': doc.extra['data'] = np.zeros(2, dtype=[('field', 'i4')])
    if kind == 'metadata': doc.extra['data'] = np.zeros(2, dtype=np.dtype('i4', metadata={'unit': 'pixel'}))
    if kind == 'timezone': doc.extra['data'] = datetime(2026, 11, 12, tzinfo=ZoneInfo('UTC'))
    restored = restore_document(serialize_document(doc))
    assert_graph_equal(doc, restored)
    if kind == 'metadata': assert restored.extra['data'].dtype.metadata == {'unit': 'pixel'}


def rewrite_registered_manifest(path, data):
    """Simulate a locally registered producer error, separately from corruption."""
    from people_gator.core.checkpoints import _sealed
    data = resign(data)
    path.write_text(json.dumps(data))
    ledger_path = Path(data['run_directory']) / 'run-state.json'
    ledger = json.loads(ledger_path.read_text())
    ledger.pop('integrity_sha256')
    ledger['checkpoints'][str(path.resolve())] = data['integrity_sha256']
    ledger_path.write_text(json.dumps(_sealed(ledger)))


def test_small_json_metadata_and_native_payload_pair(tmp_path, monkeypatch):
    import hashlib
    from people_gator.core.checkpoint_document import PROTOCOL
    parser, engines, config = pipeline(tmp_path, monkeypatch)
    doc = rich_document()
    large_text = 'private-ocr-state-' * 20000
    doc.page_layouts[0].regions[0].lines[0].transcription = large_text
    parser.process_document(doc)
    path = snapshots(tmp_path)[0]
    data = json.loads(path.read_text())
    payload = (path.parent / 'document.pkl').read_bytes()
    assert data['payload'] == {'filename': 'document.pkl', 'size': len(payload),
                               'sha256': hashlib.sha256(payload).hexdigest(), 'protocol': PROTOCOL}
    assert payload[:2] == bytes((0x80, PROTOCOL))
    assert 'document' not in data
    assert 'private-ocr-state-' not in path.read_text()
    assert path.stat().st_size < 20000 < len(payload)
    assert data['summary']['pages'] == 2
    assert data['summary']['faces'] == 2
    assert data['summary']['text_mentions'] == 2
    assert data['summary']['clusters'] == 1
    assert data['summary']['resolved_identities'] == 1
    from people_gator import globals
    assert data['compatibility'] == {'peoplegator_version': globals.software_version}
    assert (path.parent / 'document.pkl').stat().st_mode & 0o777 == 0o600
    assert 'sensitive-credential-012345' not in path.read_text()
    assert b'sensitive-credential-012345' not in payload
    # Directory and manifest are equivalent explicit resume entry points.
    parser.process_document(None, resume_from_checkpoint=path.parent)


@pytest.mark.parametrize('damage', ['missing_payload', 'hash', 'size', 'protocol', 'header',
    'manifest_field', 'input'])
def test_invalid_hybrid_checkpoint_rejected_before_unpickling(tmp_path, monkeypatch, damage):
    import hashlib
    from people_gator.core import checkpoints
    parser, engines, config = pipeline(tmp_path, monkeypatch)
    parser.process_document(rich_document())
    path = snapshots(tmp_path)[0]
    data = json.loads(path.read_text())
    payload_path = path.parent / 'document.pkl'
    if damage == 'missing_payload': payload_path.unlink()
    if damage == 'hash': payload_path.write_bytes(b'corrupt')
    if damage == 'size': data['payload']['size'] += 1
    if damage == 'protocol': data['payload']['protocol'] = 999
    if damage == 'header':
        raw = payload_path.read_bytes()
        raw = b'\x80\x04' + raw[2:]
        payload_path.write_bytes(raw)
        data['payload']['sha256'] = hashlib.sha256(raw).hexdigest()
    if damage == 'manifest_field': del data['summary']
    if damage == 'input': data['input_assets'] = [{'field': 'page_images_dir', 'path': str(tmp_path / 'missing'), 'files': []}]
    rewrite_registered_manifest(path, data)
    unpickle = Mock(side_effect=AssertionError('must reject before unpickling'))
    monkeypatch.setattr(checkpoints, 'restore_document', unpickle)
    with pytest.raises(checkpoints.CheckpointError):
        parser.process_document(None, resume_from_checkpoint=path)
    unpickle.assert_not_called()


@pytest.mark.parametrize('phase', ['payload', 'manifest'])
def test_two_file_commit_marker_published_last(tmp_path, monkeypatch, phase):
    from people_gator.core import checkpoints
    parser, engines, config = pipeline(tmp_path, monkeypatch)
    replace = checkpoints.os.replace
    def fail_second(source, destination):
        path = Path(destination)
        if path.parent.name.startswith('0002-'):
            if path.name == 'checkpoint.json':
                assert (path.parent / 'document.pkl').exists()
            if path.name == ('document.pkl' if phase == 'payload' else 'checkpoint.json'):
                raise OSError('interrupted')
        replace(source, destination)
    monkeypatch.setattr(checkpoints.os, 'replace', fail_second)
    with pytest.raises(checkpoints.CheckpointError, match='write failed'):
        parser.process_document(rich_document())
    assert len(snapshots(tmp_path)) == 1
    incomplete, = (tmp_path / 'snapshots').rglob('0002-ENGINE_1')
    assert not (incomplete / 'checkpoint.json').exists()
    with pytest.raises(checkpoints.CheckpointError):
        parser.process_document(None, resume_from_checkpoint=incomplete)
    monkeypatch.setattr(checkpoints.os, 'replace', replace)
    parser.process_document(None, resume_from_checkpoint=snapshots(tmp_path)[0])


@pytest.mark.parametrize('kind', ['copied', 'public_marker', 'public_stage', 'payload_symlink', 'raw_pickle'])
def test_only_protected_registered_local_checkpoints_can_unpickle(tmp_path, monkeypatch, kind):
    from people_gator.core import checkpoints
    parser, engines, config = pipeline(tmp_path, monkeypatch)
    parser.process_document(rich_document())
    path = snapshots(tmp_path)[0]
    if kind == 'copied':
        copied = tmp_path / 'download' / 'attempt' / 'stage'
        copied.parent.mkdir(mode=0o700, parents=True)
        copied.parent.parent.chmod(0o700)
        shutil.copytree(path.parent, copied)
        path = copied / 'checkpoint.json'
    if kind == 'public_marker': path.chmod(0o644)
    if kind == 'public_stage': path.parent.chmod(0o777)
    if kind == 'payload_symlink':
        payload = path.parent / 'document.pkl'
        target = path.parent / 'elsewhere.pkl'
        payload.rename(target)
        payload.symlink_to(target)
    if kind == 'raw_pickle': path = path.parent / 'document.pkl'
    unpickle = Mock(side_effect=AssertionError('untrusted files must not unpickle'))
    monkeypatch.setattr(checkpoints, 'restore_document', unpickle)
    with pytest.raises(checkpoints.CheckpointError):
        parser.process_document(None, resume_from_checkpoint=path)
    unpickle.assert_not_called()


@pytest.mark.parametrize('kind', ['db', 'session', 'mock'])
def test_live_clients_and_credentials_never_reach_either_file(tmp_path, monkeypatch, kind):
    import requests
    from people_gator.core.checkpoints import CheckpointError
    from people_gator.core.db import DatabaseApiService
    parser, engines, config = pipeline(tmp_path, monkeypatch)
    doc = rich_document()
    if kind == 'db':
        doc.client = object.__new__(DatabaseApiService)
        doc.client.password = 'sensitive-credential-012345'
    if kind == 'session': doc.client = requests.Session()
    if kind == 'mock': doc.client = Mock(password='sensitive-credential-012345')
    with pytest.raises(CheckpointError):
        parser.process_document(doc)
    assert not snapshots(tmp_path)
    assert not list((tmp_path / 'snapshots').rglob('document.pkl'))
    assert not any(e.process_document.called for e in engines)


class LossyMetadata:
    def __init__(self):
        self.populated = 'must survive'

    def __getstate__(self):
        return {}


def test_lossy_custom_pickle_state_is_rejected():
    from people_gator.core.checkpoint_document import serialize_document, CheckpointError
    doc = rich_document()
    doc.extra['lossy'] = LossyMetadata()
    with pytest.raises(CheckpointError, match='omitted'):
        serialize_document(doc)


def checkpoint_callback(*args):
    return None


def test_importable_runtime_callback_preserved():
    from people_gator.core.checkpoint_document import serialize_document, restore_document
    doc = rich_document()
    doc.page_layouts[0].to_pagexml_started += checkpoint_callback
    result = restore_document(serialize_document(doc))
    assert result.page_layouts[0].to_pagexml_started._handlers[-1] is checkpoint_callback


@pytest.mark.parametrize('cached_modified', [False, True])
def test_unchanged_image_cache_externalized_modified_pixels_embedded(tmp_path, monkeypatch, cached_modified):
    import cv2
    import numpy as np
    from people_gator.core.layout import PeopleGatorDocument, PeopleGatorPageLayout
    from people_gator.core.checkpoint_document import serialize_document, restore_document, CheckpointError
    image = np.random.default_rng(4).integers(0, 255, (100, 120, 3), dtype=np.uint8)
    cv2.imwrite(str(tmp_path / 'p.jpg'), image)
    doc = PeopleGatorDocument(page_layouts=[PeopleGatorPageLayout('p')], page_images_dir=str(tmp_path))
    original = doc.get_page_image(doc.page_layouts[0])
    if cached_modified: original[0, 0] = [0, 128, 255]
    doc.page_images['p'] = original
    doc.page_layouts[0].metadata['same_image'] = original
    payload = serialize_document(doc)
    assert (len(payload) > 20000) == cached_modified
    result = restore_document(payload, tmp_path)
    np.testing.assert_array_equal(result.page_images['p'], original)
    assert result.page_images['p'] is result.page_layouts[0].metadata['same_image']
    (tmp_path / 'p.jpg').unlink()
    if cached_modified:
        np.testing.assert_array_equal(restore_document(payload, tmp_path).page_images['p'], original)
    else:
        with pytest.raises(CheckpointError): restore_document(payload, tmp_path)


def test_diagnostic_inspection_is_selected_json_and_read_only(tmp_path, monkeypatch, capsys):
    from people_gator.core.checkpoint_inspection import inspect_checkpoint
    from user_scripts import inspect_checkpoint as cli
    parser, engines, config = pipeline(tmp_path, monkeypatch)
    parser.process_document(rich_document())
    path = snapshots(tmp_path)[0]
    before = {p: p.read_bytes() for p in (tmp_path / 'snapshots').rglob('*') if p.is_file()}
    for engine in engines: engine.process_document.reset_mock()
    selected = inspect_checkpoint(path, details=['ocr', 'entities'])
    assert selected['summary']['faces'] == 2
    assert selected['pages'][0]['ocr'][0]['text'].startswith('Karel Čapek')
    assert selected['pages'][0]['mentions'][0]['source_spans'][0]['start'] == 0
    assert selected['clusters'][0]['mentions'] == [0, 1]
    assert 'regions' not in selected['pages'][0]
    output = tmp_path / 'diagnostic.json'
    monkeypatch.setattr(sys, 'argv', ['inspect_checkpoint', str(path.parent), '--details', 'entities', '--output-path', str(output)])
    assert cli.main() == 0
    assert json.loads(output.read_text())['clusters'][0]['entity_id'] == 'app-person'
    assert output.stat().st_mode & 0o777 == 0o600
    monkeypatch.setattr(sys, 'argv', ['inspect_checkpoint', str(path)])
    assert cli.main() == 0
    assert json.loads(capsys.readouterr().out)['summary']['pages'] == 2
    ledger = Path(json.loads(path.read_text())['run_directory']) / 'run-state.json'
    monkeypatch.setattr(sys, 'argv', ['inspect_checkpoint', str(path), '--output-path', str(ledger)])
    assert cli.main() == 1
    assert {p: p.read_bytes() for p in before} == before
    assert not any(e.process_document.called for e in engines)


def test_installed_diagnostic_cli_outside_checkout(tmp_path, monkeypatch):
    parser, engines, config = pipeline(tmp_path, monkeypatch)
    parser.process_document(rich_document())
    path = snapshots(tmp_path)[0]
    result = subprocess.run([sys.executable, '-m', 'user_scripts.inspect_checkpoint', str(path)],
                            cwd=tmp_path, capture_output=True, text=True)
    assert result.returncode == 0, result.stderr
    data = json.loads(result.stdout)
    face = data['pages'][0]['faces'][0]
    assert face['name'] == 'Karel Čapek'
    assert face['entity_id'] == 'app-person'
    assert face['source_region_id'] == 'source'
    assert face['landmarks']['left_eye_position'] == {'x': 0, 'y': .5}


def test_overlapping_views_fail_instead_of_losing_relationships():
    import numpy as np
    from people_gator.core.checkpoint_document import serialize_document, CheckpointError
    doc = rich_document()
    image = np.arange(20)
    doc.extra['shared_views'] = [image, image[3:]]
    with pytest.raises(CheckpointError, match='overlapping'):
        serialize_document(doc)


def test_wrong_expected_document_rejected_before_unpickle(tmp_path, monkeypatch):
    from people_gator.core import checkpoints
    from people_gator.core.layout import PeopleGatorDocument
    parser, engines, config = pipeline(tmp_path, monkeypatch)
    parser.process_document(rich_document())
    unpickle = Mock(side_effect=AssertionError('wrong document must not unpickle'))
    monkeypatch.setattr(checkpoints, 'restore_document', unpickle)
    with pytest.raises(checkpoints.CheckpointError, match='different document'):
        parser.process_document(PeopleGatorDocument(id='foreign'), resume_from_checkpoint=snapshots(tmp_path)[0])
    unpickle.assert_not_called()


def test_peoplegator_version_is_the_only_recorded_software_identity(tmp_path, monkeypatch):
    from people_gator import globals
    parser, engines, config = pipeline(tmp_path, monkeypatch)
    parser.process_document(rich_document())
    data = json.loads(snapshots(tmp_path)[0].read_text())
    assert data['compatibility'] == {'peoplegator_version': globals.software_version}


@pytest.mark.parametrize('entry_point', ['resume', 'inspect'])
@pytest.mark.parametrize('metadata_format', ['current', 'legacy'])
def test_peoplegator_version_mismatch_warns_before_unpickle_and_continues(
        tmp_path, monkeypatch, caplog, entry_point, metadata_format):
    import logging
    from people_gator import globals
    from people_gator.core import checkpoints
    from people_gator.core.checkpoint_inspection import inspect_checkpoint
    parser, engines, config = pipeline(tmp_path, monkeypatch)
    complete = parser.process_document(rich_document())
    path = snapshots(tmp_path)[0]
    data = json.loads(path.read_text())
    original_paths = set(snapshots(tmp_path))
    saved_version = '0.0.0-review'
    if metadata_format == 'current':
        data['compatibility'] = {'peoplegator_version': saved_version}
    else:
        data['compatibility'] = {'packages': {'people-gator': saved_version, 'anno-page': 'old'},
            'python': [3, 10, 0], 'code': {'old-layout': 'different'}, 'implementation': 'other'}
    rewrite_registered_manifest(path, data)
    for engine in engines: engine.process_document.reset_mock()
    caplog.set_level(logging.WARNING)
    original_restore = checkpoints.restore_document
    def restore_after_warning(*args, **kwargs):
        warnings = [r for r in caplog.records if r.levelno == logging.WARNING]
        assert len(warnings) == 1
        assert saved_version in warnings[0].getMessage()
        assert globals.software_version in warnings[0].getMessage()
        return original_restore(*args, **kwargs)
    restored = Mock(side_effect=restore_after_warning)
    monkeypatch.setattr(checkpoints, 'restore_document', restored)
    if entry_point == 'resume':
        result = parser.process_document(None, resume_from_checkpoint=path)
        assert_graph_equal(complete, result)
        assert [e.process_document.call_count for e in engines] == [0, 1, 1]
        newest = [json.loads(p.read_text()) for p in set(snapshots(tmp_path)) - original_paths]
        assert len(newest) == 2
        assert all(p['compatibility'] == {'peoplegator_version': globals.software_version} for p in newest)
    else:
        result = inspect_checkpoint(path)
        assert result['summary']['pages'] == 2
        assert not any(e.process_document.called for e in engines)
    restored.assert_called_once()
    assert 'sensitive-credential-012345' not in caplog.text
    assert str(path) not in caplog.text


@pytest.mark.parametrize('difference', ['none', 'python', 'packages', 'code'])
def test_legacy_environment_metadata_is_not_a_resume_gate(tmp_path, monkeypatch, caplog, difference):
    import logging
    from people_gator import globals
    parser, engines, config = pipeline(tmp_path, monkeypatch)
    complete = parser.process_document(rich_document())
    path = snapshots(tmp_path)[0]
    data = json.loads(path.read_text())
    identity = {'packages': {'people-gator': globals.software_version}}
    if difference == 'python': identity.update(python=[2, 7, 0], implementation='different')
    if difference == 'packages': identity['packages'].update({'pero-ocr': 'other', 'anno-page': 'other', 'numpy': 'other'})
    if difference == 'code': identity['code'] = {'any.module': 'different-source-hash'}
    data['compatibility'] = identity
    rewrite_registered_manifest(path, data)
    caplog.set_level(logging.WARNING)
    result = parser.process_document(None, resume_from_checkpoint=path)
    assert_graph_equal(complete, result)
    assert not [r for r in caplog.records if r.levelno >= logging.WARNING]


@pytest.mark.parametrize('failure', ['corrupt', 'missing_class'])
def test_actual_pickle_restore_failure_is_actionable_after_version_warning(tmp_path, monkeypatch, caplog, failure):
    import hashlib
    import logging
    from people_gator.core.checkpoints import CheckpointError
    parser, engines, config = pipeline(tmp_path, monkeypatch)
    parser.process_document(rich_document())
    path = snapshots(tmp_path)[0]
    data = json.loads(path.read_text())
    raw = b'\x80\x05(' if failure == 'corrupt' else b'\x80\x05cpeoplegator_missing_module\nMissingClass\n.'
    (path.parent / 'document.pkl').write_bytes(raw)
    data['payload'].update(size=len(raw), sha256=hashlib.sha256(raw).hexdigest())
    data['compatibility'] = {'peoplegator_version': '0.0.0-review'}
    rewrite_registered_manifest(path, data)
    for engine in engines: engine.process_document.reset_mock()
    caplog.set_level(logging.WARNING)
    with pytest.raises(CheckpointError, match='restore.*Pickle.*classes.*dependencies'):
        parser.process_document(None, resume_from_checkpoint=path)
    assert '0.0.0-review' in caplog.text
    assert not any(e.process_document.called for e in engines)
