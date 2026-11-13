"""Face-local raw LLM diagnostics, parallel association and opt-in JSON export."""

from configparser import ConfigParser
from copy import deepcopy
import json
import multiprocessing
from pathlib import Path
from types import SimpleNamespace as NS
from unittest.mock import Mock

import pytest


@pytest.fixture(autouse=True)
def processing_only(runtime_mode):
    if runtime_mode == 'client':
        pytest.skip('Face diagnostics require processing extras')


def install_provider(monkeypatch, create):
    from people_gator.engines import llm
    monkeypatch.setattr(llm, 'OpenAI', Mock(return_value=NS(responses=NS(create=create))))
    return llm


def rendered(request):
    return '\n'.join('[' + m['role'] + ']\n' + '\n'.join(
        c['text'] for c in m['content'] if c['type'] == 'input_text')
        for m in request['input'] if any(c['type'] == 'input_text' for c in m['content']))


def test_metadata_lists_checkpoint_fidelity_and_separate_persistence():
    from test_entity_matching import face_only, identity
    from people_gator.core.checkpoint_document import serialize_document, restore_document
    doc = face_only(identity(), identity())
    a, b = doc.faces
    assert a.face_metadata.prompts == b.face_metadata.prompts == []
    assert a.face_metadata.prompts is not b.face_metadata.prompts
    before = deepcopy(a.face_metadata.to_dict())
    record = dict(engine='LLM_FACE_ASSIGNMENT', prompt='[user]\nČapek', response='{bad JSON')
    a.face_metadata.prompts.append(record)
    assert b.face_metadata.prompts == []
    assert a.face_metadata.to_dict() == before
    restored = restore_document(serialize_document(doc))
    assert restored.faces[0].face_metadata.prompts == [record]
    assert restored.faces[1].face_metadata.prompts == []
    assert restored.faces[0].face_metadata.prompts is not a.face_metadata.prompts


@pytest.mark.parametrize('parallel', [False, True])
@pytest.mark.parametrize('failure', ['malformed', 'schema', 'transport', 'failed', 'incomplete', 'token-limit'])
@pytest.mark.parametrize('raise_on_failure', [False, True])
def test_raw_attempts_keep_existing_results_and_failure_semantics(monkeypatch, parallel, failure, raise_on_failure):
    from test_llm_prompts import InlinePool
    from people_gator.engines.llm import LLMPrompter, LLMRequestError, LLMResponseError
    invalid = {
        'malformed': NS(status='completed', output_text=' ```json\n{Čapek\n``` '),
        'schema': NS(status='completed', output_text='{"wrong": "Čapek"}'),
        'transport': OSError('do not export this exception or API key'),
        'failed': NS(status='failed', output_text='raw failed output'),
        'incomplete': NS(status='incomplete', output_text='raw partial output', incomplete_details=NS(reason='other')),
        'token-limit': NS(status='incomplete', output_text='raw token-limited output', incomplete_details=NS(reason='max_output_tokens')),
    }[failure]
    create = Mock(side_effect=[invalid, invalid])
    llm = install_provider(monkeypatch, create)
    monkeypatch.setattr(llm.multiprocessing, 'Pool', InlinePool)
    prompter = LLMPrompter('https://example.invalid', 'private-api-key', 'mock',
        prompt_template_system='Use {{ name }}.', prompt_template_user='Name {{ name }}',
        json_schema={'type': 'object', 'required': ['ok']}, max_attempts=2, raise_on_failure=raise_on_failure)
    interactions = []
    operation = lambda: prompter.process_parallel(
        [{'name': 'Čapek'}], images_list=[{'crop label': 'data:image/jpeg;base64,PRIVATE'}],
        interactions=interactions) if parallel else prompter.process(
            {'name': 'Čapek'}, images={'crop label': 'data:image/jpeg;base64,PRIVATE'}, interactions=interactions)
    if raise_on_failure:
        error = LLMResponseError if failure in ('malformed', 'schema') else LLMRequestError
        with pytest.raises(error):
            operation()
    else:
        result = operation()
        expected = {'wrong': 'Čapek'} if failure == 'schema' else None
        assert result == ([expected] if parallel else expected)
    expected_count = 1 if failure == 'token-limit' else 2
    assert create.call_count == expected_count
    records = interactions[0] if parallel else interactions
    assert len(records) == expected_count
    assert records == [dict(prompt='[system]\nUse Čapek.\n[user]\nName Čapek\n[user]\ncrop label',
                            response=None if failure == 'transport' else invalid.output_text)] * expected_count
    assert 'PRIVATE' not in json.dumps(records) and 'private-api-key' not in json.dumps(records)


def diagnostic_document():
    from test_face_assignment_text_entities import engine_document
    from test_entity_matching import page_identity
    from people_gator.core.layout import PeopleGatorFaceRegionLayout, PeopleGatorFaceMetadata, Position
    doc, _ = engine_document()
    p, q = doc.page_layouts
    copies = deepcopy([r for r in p.regions if isinstance(r, PeopleGatorFaceRegionLayout)][:2])
    copies[0].source_region.graphical_metadata.title = 'Caption Č'
    q.regions.extend(copies)
    for pg in doc.page_layouts:
        for f in pg.regions:
            if isinstance(f, PeopleGatorFaceRegionLayout):
                f.face_metadata = PeopleGatorFaceMetadata(f.id, 'MODS_' + f.id, page_identity(), *[Position(1, 1) for _ in range(5)])
    return doc


@pytest.mark.parametrize('mode', ['single', 'sequential', 'page_parallel', 'document_parallel'])
def test_assignment_modes_attach_exact_attempts_to_only_participating_faces(tmp_path, monkeypatch, mode):
    from test_face_assignment_text_entities import make_engine
    from test_llm_prompts import InlinePool
    from people_gator.core.layout import PeopleGatorFaceRegionLayout
    engine = make_engine(tmp_path, mode)
    from jinja2 import Template
    engine.llm_prompter.prompt_template_system = Template('Identify {{ caption_text }}')
    engine.llm_prompter.prompt_template_user = Template('{{ face_coordinates | default(faces) }}')
    doc = diagnostic_document()
    # A legacy trusted checkpoint can lack this newly introduced attribute.
    first = next(r for r in doc.page_layouts[0].regions if isinstance(r, PeopleGatorFaceRegionLayout))
    del first.face_metadata.prompts
    requests = []
    counts = {}

    def create(**request):
        prompt = rendered(request)
        requests.append(request)
        count = counts[prompt] = counts.get(prompt, 0) + 1
        if count == 1:
            return NS(status='completed', output_text='malformed Čapek')
        if count == 2:
            raise OSError('private transport error')
        raw = json.dumps({'name_normalized': None, 'name_in_text': None, 'faces': [], 'prompt': prompt}, ensure_ascii=False)
        return NS(status='completed', output_text=raw)

    llm = install_provider(monkeypatch, create)
    monkeypatch.setattr(llm.multiprocessing, 'Pool', InlinePool)
    assert engine.process_document(doc) is doc
    for pg in doc.page_layouts:
        for face in (r for r in pg.regions if isinstance(r, PeopleGatorFaceRegionLayout)):
            records = face.face_metadata.prompts
            assert len(records) == 3
            method = 'LLM_FACE_ASSIGNMENT' if mode == 'single' else 'LLM_BATCH_FACE_ASSIGNMENT'
            assert all(set(r) == {'engine', 'prompt', 'response'} and r['engine'] == method for r in records)
            assert all(face.source_region.graphical_metadata.title in r['prompt'] for r in records)
            assert records[0]['response'] == 'malformed Čapek'
            assert records[1]['response'] is None
            assert json.loads(records[2]['response'])['prompt'] == records[2]['prompt']
            assert any(records[2]['prompt'] == rendered(request) for request in requests)
            assert records[0]['prompt'] == records[1]['prompt'] == records[2]['prompt']
            assert 'data:image' not in json.dumps(records)
    faces = [f for p in doc.page_layouts for f in p.regions if isinstance(f, PeopleGatorFaceRegionLayout)]
    faces[0].face_metadata.prompts[0]['response'] = 'changed'
    assert all(f.face_metadata.prompts[0]['response'] == 'malformed Čapek' for f in faces[1:])
    assert len(requests) == (18 if mode == 'single' else 9)


@pytest.mark.skipif('fork' not in multiprocessing.get_all_start_methods(), reason='POSIX fork smoke test')
def test_real_pool_returns_worker_records_to_original_faces(tmp_path, monkeypatch):
    from test_face_assignment_text_entities import make_engine
    from people_gator.core.layout import PeopleGatorFaceRegionLayout
    engine = make_engine(tmp_path, 'document_parallel')
    engine.llm_prompter.num_processes = 2
    llm = install_provider(monkeypatch, Mock(return_value=NS(status='completed', output_text='{"faces": []}')))
    monkeypatch.setattr(llm.multiprocessing, 'Pool', multiprocessing.get_context('fork').Pool)
    doc = diagnostic_document()
    engine.process_document(doc)
    faces = [f for p in doc.page_layouts for f in p.regions if isinstance(f, PeopleGatorFaceRegionLayout)]
    assert len(faces) == 6
    assert all(len(f.face_metadata.prompts) == 1 for f in faces)
    assert all(f.face_metadata.prompts[0]['response'] == '{"faces": []}' for f in faces)


@pytest.mark.parametrize('fail', [False, True])
def test_matching_multiple_faces_text_only_and_unrelated_units(tmp_path, monkeypatch, fail):
    from test_entity_matching import face_only, identity, add_cluster
    from people_gator.engines.entity_matching import EntityMatchingEngine
    shared = identity()
    doc = face_only(shared, shared, identity(''), identity('Protected', 'keep'))
    a, b, unnamed, protected = doc.faces
    earlier = dict(engine='LLM_FACE_ASSIGNMENT', prompt='[user]\nearlier', response='earlier')
    a.face_metadata.prompts.append(earlier)
    if not fail:
        add_cluster(doc, name='Ada Lovelace')
    prompt = tmp_path / 'matching.json'
    prompt.write_text(json.dumps({'system': 'Resolve {{ name }}', 'user': '{{ context }} {{ entities }}'}))
    config = ConfigParser()
    config.read_dict({'ENGINE': {'PROMPT_TEMPLATE_PATH': str(prompt)}})
    db = Mock()
    db.search_entities.return_value = {'items': []}
    engine = EntityMatchingEngine(config['ENGINE'], 'cpu', str(tmp_path), db_api_service=db)
    raw = '{bad Čapek' if fail else json.dumps(dict(action='unresolved', source_is_person=True, item_id=None, name=None, reason='No matching evidence.'))
    create = Mock(return_value=NS(status='completed', output_text=raw))
    install_provider(monkeypatch, create)
    if fail:
        with pytest.raises(RuntimeError, match='LLM decision failed|inspect safe operation'):
            engine.process_document(doc)
    else:
        assert engine.process_document(doc) is doc
    expected_count = 3 if fail else 1
    assert a.face_metadata.prompts == [earlier, *b.face_metadata.prompts]
    assert len(b.face_metadata.prompts) == expected_count
    assert all(r['engine'] == 'ENTITY_MATCHING' and r['response'] == raw for r in b.face_metadata.prompts)
    assert all('Ada Lovelace' not in r['prompt'] for r in b.face_metadata.prompts)
    assert unnamed.face_metadata.prompts == protected.face_metadata.prompts == []
    assert create.call_count == (3 if fail else 2)
    db.create_entity.assert_not_called()


@pytest.mark.parametrize('fmt', ['alto', 'page'])
def test_export_every_face_unique_stable_unicode_and_no_xml_changes(tmp_path, fmt):
    from test_entity_matching import document, face
    from user_scripts.parse_folder import save_face_prompts
    doc = document(fmt)
    if fmt == 'alto':
        import shutil
        source_dir = tmp_path / 'source'
        source_dir.mkdir()
        fixture = Path(__file__).parent / 'resources' / 'text_chunking' / 'input.alto.xml'
        for page in doc.page_layouts:
            shutil.copyfile(fixture, source_dir / (page.id + '.xml'))
        doc.alto_xmls_dir = str(source_dir)
    for page in doc.page_layouts:
        face(page)
    first = doc.faces[0]
    original = [dict(engine='ENTITY_MATCHING', prompt='[user]\nČapek', response='raw Žluťoučký')]
    writer = doc.to_altoxml if fmt == 'alto' else doc.to_pagexml
    before_dir, after_dir = tmp_path / 'before', tmp_path / 'after'
    before_dir.mkdir(); after_dir.mkdir()
    writer(before_dir)
    first.face_metadata.prompts.extend(original)
    writer(after_dir)
    from lxml import etree
    def normalized(directory):
        result = {}
        for path in directory.glob('*.xml'):
            root = etree.parse(str(path))
            for element in root.iter():
                if etree.QName(element).localname in ('Created', 'LastChange', 'recordCreationDate', 'processingDateTime'):
                    element.text = 'TIMESTAMP'
                if 'date' in element.attrib:
                    element.set('date', 'TIMESTAMP')
            result[path.name] = etree.tostring(root)
        return result
    assert normalized(before_dir) == normalized(after_dir)
    # Repeated page/face IDs, delimiter collisions, separators and absent metadata.
    for page in doc.page_layouts:
        page.id = '../same_page'
        faces = page.faces
        faces[0].face_metadata.tag_id = '../face_tag'
    extra = deepcopy(first)
    extra.face_metadata = None
    doc.page_layouts[0].regions.append(extra)
    out = tmp_path / 'nested' / 'prompts'
    save_face_prompts(doc, out)
    files = sorted(out.glob('*.json'))
    assert len(files) == len(doc.faces)
    content = {f.name: f.read_text(encoding='utf-8') for f in files}
    lists = [json.loads(value) for value in content.values()]
    assert lists.count(original) == 1
    assert lists.count([]) == len(files) - 1
    assert any('Čapek' in value and 'Žluťoučký' in value for value in content.values())
    assert all('/' not in name and '\\' not in name for name in content)
    save_face_prompts(doc, out)
    assert {f.name: f.read_text(encoding='utf-8') for f in out.glob('*.json')} == content
    assert all('prompts' not in r.face_metadata.to_dict() for r in doc.faces if r.face_metadata)


@pytest.mark.parametrize('mode', ['absent', 'empty', 'ini', 'override', 'disable', 'resume'])
def test_cli_ini_precedence_disabled_output_and_final_processed_document(tmp_path, monkeypatch, mode):
    import sys
    from test_entity_matching import face_only, identity
    from user_scripts import parse_folder
    doc = face_only(identity(), identity())
    doc.faces[0].face_metadata.prompts.append(dict(engine='ENTITY_MATCHING', prompt='Čapek', response='raw'))
    # Legacy checkpoint metadata still exports an empty list when no new call ran.
    del doc.faces[1].face_metadata.prompts
    ini = tmp_path / 'ini-output'
    cli = tmp_path / 'cli-output'
    config = ConfigParser()
    config['PARSE_FOLDER'] = {}
    if mode in ('ini', 'override', 'disable', 'resume'):
        config['PARSE_FOLDER']['OUTPUT_FACE_PROMPTS_PATH'] = str(ini)
    elif mode == 'empty':
        config['PARSE_FOLDER']['OUTPUT_FACE_PROMPTS_PATH'] = ''
    path = tmp_path / 'pipeline.ini'
    with path.open('w') as stream:
        config.write(stream)
    args = ['peoplegator', '--config', str(path)]
    if mode == 'override': args += ['--output-face-prompts-path', str(cli)]
    if mode == 'disable': args += ['--output-face-prompts-path=']
    if mode == 'resume': args += ['--resume-from-checkpoint', 'trusted-checkpoint']
    monkeypatch.setattr(sys, 'argv', args)
    parser = Mock()
    parser.process_document.return_value = doc
    monkeypatch.setattr(parse_folder, 'create_document_parser', Mock(return_value=parser))
    loader = Mock(return_value=object())
    monkeypatch.setattr(parse_folder, 'load_document', loader)
    assert parse_folder.main() == 0
    target = cli if mode == 'override' else ini
    if mode in ('absent', 'empty', 'disable'):
        assert not ini.exists() and not cli.exists()
    else:
        assert sorted((json.loads(f.read_text()) for f in target.glob('*.json')), key=len) == [[], doc.faces[0].face_metadata.prompts]
        assert not (ini if mode == 'override' else cli).exists()
    if mode == 'resume':
        loader.assert_not_called()
        assert parser.process_document.call_args.args == (None,)


def test_checkpoint_resume_can_enable_or_relocate_prompt_output(tmp_path, monkeypatch):
    from test_checkpoints import pipeline, rich_document, snapshots
    parser, _, config = pipeline(tmp_path, monkeypatch)
    doc = rich_document()
    record = dict(engine='LLM_FACE_ASSIGNMENT', prompt='[user]\nČapek', response='raw')
    doc.faces[0].face_metadata.prompts.append(record)
    parser.process_document(doc)
    path = snapshots(tmp_path)[-1]
    config['PARSE_FOLDER']['OUTPUT_FACE_PROMPTS_PATH'] = str(tmp_path / 'new-output')
    restored = parser.process_document(None, resume_from_checkpoint=path)
    assert restored.faces[0].face_metadata.prompts == [record]
    config['PARSE_FOLDER']['OUTPUT_FACE_PROMPTS_PATH'] = str(tmp_path / 'relocated-output')
    restored = parser.process_document(None, resume_from_checkpoint=path)
    assert restored.faces[0].face_metadata.prompts == [record]


def test_app_face_payload_is_identical_with_or_without_diagnostics():
    from test_entity_matching import face_only, identity
    from people_gator.core.db import DatabaseApiService
    service = DatabaseApiService.__new__(DatabaseApiService)
    service.api_url = 'https://app.example.invalid'
    service.connector = Mock()
    service.connector.post.return_value = NS(status_code=201, json=lambda: {'id': 'created'})
    face = face_only(identity(entity_id='existing')).faces[0]
    assert service.create_face(face, 'page-source') == {'id': 'created'}
    before = deepcopy(service.connector.post.call_args.kwargs)
    face.face_metadata.prompts.append(dict(engine='ENTITY_MATCHING', prompt='private OCR', response='private response'))
    assert service.create_face(face, 'page-source') == {'id': 'created'}
    assert service.connector.post.call_args.kwargs == before
    assert 'private' not in repr(service.connector.post.call_args.kwargs)


@pytest.mark.parametrize('method', ['process', '__call__', 'process_parallel'])
def test_explicit_collection_preserves_existing_entries_and_is_request_local(monkeypatch, method):
    from test_llm_prompts import InlinePool
    from people_gator.engines.llm import LLMPrompter
    create = Mock(return_value=NS(status='completed', output_text=' {"ok": "Čapek"}\n'))
    llm = install_provider(monkeypatch, create)
    monkeypatch.setattr(llm.multiprocessing, 'Pool', InlinePool)
    prompter = LLMPrompter('https://example.invalid', 'private-key', 'mock', prompt_template_user='{{ name }}')
    prior = {'prompt': 'earlier', 'response': 'earlier'}
    parallel = method == 'process_parallel'
    interactions = [[prior]] if parallel else [prior]
    argument = [{'name': 'first'}] if parallel else {'name': 'first'}
    operation = getattr(prompter, method)
    expected = [{'ok': 'Čapek'}] if parallel else {'ok': 'Čapek'}
    assert operation(argument, interactions=interactions) == expected
    first = {'prompt': '[user]\nfirst', 'response': ' {"ok": "Čapek"}\n'}
    assert interactions == ([[prior], [first]] if parallel else [prior, first])
    # Calls without a sink neither retain diagnostics nor mutate an earlier sink.
    saved = deepcopy(interactions)
    assert operation(argument) == expected
    assert interactions == saved
    separate = []
    other = [{'name': 'second'}] if parallel else {'name': 'second'}
    assert operation(other, interactions=separate) == expected
    second = {'prompt': '[user]\nsecond', 'response': ' {"ok": "Čapek"}\n'}
    assert separate == ([[second]] if parallel else [second])
    assert interactions == saved
    assert operation(other, interactions=interactions) == expected
    assert interactions == saved + ([[second]] if parallel else [second])
    assert create.call_count == 4


@pytest.mark.parametrize('raise_on_failure', [False, True])
def test_parallel_capture_preserves_all_request_groups_on_failure(monkeypatch, raise_on_failure):
    from test_llm_prompts import InlinePool
    from people_gator.engines.llm import LLMPrompter, LLMResponseError

    def create(**request):
        text = rendered(request)
        raw = 'invalid Čapek' if 'bad' in text else '{"ok": true}'
        return NS(status='completed', output_text=raw)

    llm = install_provider(monkeypatch, Mock(side_effect=create))
    monkeypatch.setattr(llm.multiprocessing, 'Pool', InlinePool)
    prompter = LLMPrompter('https://example.invalid', 'private-key', 'mock',
        prompt_template_user='{{ name }}', max_attempts=2, raise_on_failure=raise_on_failure)
    prior = [{'prompt': 'earlier', 'response': None}]
    interactions = [prior]
    requests = [{'name': 'first'}, {'name': 'bad'}, {'name': 'last'}]
    if raise_on_failure:
        with pytest.raises(LLMResponseError):
            prompter.process_parallel(requests, interactions=interactions)
    else:
        assert prompter.process_parallel(requests, interactions=interactions) == [{'ok': True}, None, {'ok': True}]
    assert interactions == [prior,
        [{'prompt': '[user]\nfirst', 'response': '{"ok": true}'}],
        [{'prompt': '[user]\nbad', 'response': 'invalid Čapek'}] * 2,
        [{'prompt': '[user]\nlast', 'response': '{"ok": true}'}]]


def test_empty_parallel_requests_do_not_change_the_output_collection(monkeypatch):
    from test_llm_prompts import InlinePool
    from people_gator.engines.llm import LLMPrompter
    create = Mock()
    llm = install_provider(monkeypatch, create)
    monkeypatch.setattr(llm.multiprocessing, 'Pool', InlinePool)
    prompter = LLMPrompter('https://example.invalid', 'private-key', 'mock', prompt_template_user='empty')
    prior = [{'prompt': 'earlier', 'response': None}]
    interactions = [prior]
    assert prompter.process_parallel([], interactions=interactions) == []
    assert interactions == [prior]
    create.assert_not_called()


@pytest.mark.parametrize('mode', ['single', 'sequential', 'page_parallel', 'document_parallel'])
def test_assignment_retains_attempts_when_an_explicit_request_raises(tmp_path, monkeypatch, mode):
    from test_face_assignment_text_entities import make_engine
    from test_llm_prompts import InlinePool
    from people_gator.core.layout import PeopleGatorFaceRegionLayout
    from people_gator.engines.llm import LLMResponseError
    engine = make_engine(tmp_path, mode)
    engine.llm_prompter.raise_on_failure = True
    engine.llm_prompter.max_attempts = 2
    llm = install_provider(monkeypatch, Mock(return_value=NS(status='completed', output_text='bad Čapek')))
    monkeypatch.setattr(llm.multiprocessing, 'Pool', InlinePool)
    doc = diagnostic_document()
    with pytest.raises(LLMResponseError):
        engine.process_document(doc)
    groups = [[r for r in p.regions if isinstance(r, PeopleGatorFaceRegionLayout)] for p in doc.page_layouts]
    expected_faces = groups[0][:1] if mode == 'single' else groups[0][:2] if mode == 'sequential' else groups[0] if mode == 'page_parallel' else sum(groups, [])
    for face in sum(groups, []):
        records = face.face_metadata.prompts
        if face in expected_faces:
            assert len(records) == 2
            assert all(record['response'] == 'bad Čapek' for record in records)
        else:
            assert records == []
