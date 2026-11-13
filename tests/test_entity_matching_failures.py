"""Per-unit recovery, safe reasons and normal final output after linking failures."""

from copy import deepcopy
import json
import logging
from types import SimpleNamespace as NS
from unittest.mock import Mock

import pytest

from test_entity_matching import (
    engine, processing_only, add_cluster, candidate, decision, document, face,
    face_only, identity, page_identity,
)


@pytest.mark.parametrize('bad, entity_type, reason', [
    ({'item_id': 1}, 'person', 'invalid/unavailable candidate index'),
    ({'name': 'private-wrong-name'}, 'person', 'candidate name mismatch'),
    ({}, 'organization', 'non-person candidate'),
    ({'action': 'create', 'item_id': None, 'name': 'private-wrong-name'},
     'person', 'invalid create proposal'),
    ({'action': 'unsupported-private-action'}, 'person', 'invalid/unusable LLM decision schema'),
])
def test_unit_12_safe_validation_reason_and_later_success(engine, caplog, bad, entity_type, reason):
    doc = face_only(*(identity('private-manual', f'manual-{i}') for i in range(12)),
                    identity('private-proposal'), identity('private-later'))
    before = [deepcopy(f.face_metadata.to_dict()) for f in doc.faces]
    hit = candidate(entity_id='first-hit', name='private-candidate', entity_type=entity_type)
    later_hit = dict(hit, entity_id='existing', entity_type='person')
    engine.db_api_service.search_entities.side_effect = [{'items': [hit]}, {'items': [later_hit]}]
    engine.db_api_service.get_entity_info.side_effect = [hit, later_hit]
    payload = dict(action='select', source_is_person=True, item_id=0,
                   name=hit['name'], reason='private-reason OCR caption')
    engine.llm_prompter.side_effect = [dict(payload, **bad), dict(payload)]
    with caplog.at_level(logging.DEBUG):
        assert engine.process_document(doc) is doc
    assert [f.face_metadata.to_dict() for f in doc.faces[:13]] == before[:13]
    assert doc.faces[-1].face_metadata.page_identity.identity.peoplegator_id == 'existing'
    assert f'Entity unit 12: LLM decision failed (_MatchingValidationError): {reason}' in caplog.text
    if bad.get('action') != 'create':
        assert 'candidate_count=1' in caplog.text
    if reason in ('candidate name mismatch', 'non-person candidate'):
        assert 'candidate_index=0' in caplog.text
    assert '14 processed; 13 linked; 1 failed; 0 skipped' in caplog.text
    assert 'private-' not in caplog.text
    engine.db_api_service.create_entity.assert_not_called()
    assert engine.llm_prompter.call_count == 2


@pytest.mark.parametrize('failure, expected_stage, expected_reason', [
    ('search', 'candidate retrieval', 'external request or response processing error'),
    ('search_payload', 'candidate retrieval', 'invalid candidate search response'),
    ('search_hit', 'candidate retrieval', 'invalid candidate search hit'),
    ('details', 'candidate retrieval', 'external request or response processing error'),
    ('details_payload', 'candidate retrieval', 'invalid candidate details response'),
    ('llm_request', 'LLM decision', 'LLM request exhausted without a usable response'),
    ('llm_response', 'LLM decision', 'invalid/unusable LLM response after retries'),
    ('pydantic', 'LLM decision', 'invalid/unusable response schema'),
    ('create', 'entity creation', 'external request or response processing error'),
    ('create_payload', 'entity creation', 'invalid entity create response'),
])
def test_request_failures_preserve_unit_and_continue_without_fallback(
        engine, caplog, failure, expected_stage, expected_reason):
    from people_gator.engines.entity_matching import EntityMatchingResult
    from people_gator.engines.llm import LLMRequestError, LLMResponseError
    from pydantic import ValidationError
    person = identity()
    doc = document(linked=person)
    first = doc.text_entity_clusters[0]
    first.text_entities[0].page_identity = page_identity(person)
    attached = face(doc.page_layouts[0], person)
    before = deepcopy(attached.face_metadata.to_dict())
    wrapper = first.text_entities[0].page_identity
    later = add_cluster(doc, name='private-later')
    error = RuntimeError('private-credential private-OCR private-caption private-response')
    error.status_code = 503
    engine.llm_prompter.side_effect = [decision('create'), decision('create', name=later.name)]
    engine.db_api_service.create_entity.side_effect = [{'entity_id': 'first'}, {'entity_id': 'later'}]
    if failure.startswith('search'):
        bad = error if failure == 'search' else None if failure == 'search_payload' else {'items': [None]}
        engine.db_api_service.search_entities.side_effect = [bad, {'items': []}]
    if failure.startswith('details'):
        engine.db_api_service.search_entities.side_effect = [{'items': [{'entity_id': 'bad'}]}, {'items': []}]
        engine.db_api_service.get_entity_info.side_effect = [error if failure == 'details' else {'private': 'OCR'}]
    if failure.startswith('search') or failure.startswith('details'):
        engine.llm_prompter.side_effect = [decision('create', name=later.name)]
        engine.db_api_service.create_entity.side_effect = [{'entity_id': 'later'}]
    if failure in ('llm_request', 'llm_response', 'pydantic'):
        if failure == 'pydantic':
            try:
                EntityMatchingResult.model_validate({'private': 'private-response'})
            except ValidationError as exc:
                error = exc
        else:
            error = (LLMRequestError if failure == 'llm_request' else LLMResponseError)('private-payload')
        engine.llm_prompter.side_effect = [error, decision('create', name=later.name)]
        engine.db_api_service.create_entity.side_effect = [{'entity_id': 'later'}]
    if failure.startswith('create'):
        engine.db_api_service.create_entity.side_effect = [error if failure == 'create' else None, {'entity_id': 'later'}]
    with caplog.at_level(logging.DEBUG):
        assert engine.process_document(doc) is doc
    assert first.identity is person and person.peoplegator_id is None
    assert first.text_entities[0].page_identity is wrapper and wrapper.identity is person
    assert first.text_entities[1].page_identity is None
    assert attached.face_metadata.to_dict() == before
    assert later.identity.peoplegator_id == 'later'
    assert expected_stage + ' failed (' in caplog.text and expected_reason in caplog.text
    assert '2 processed; 1 linked; 1 failed; 0 skipped' in caplog.text
    assert 'private-' not in caplog.text and 'Karel Čapek' not in caplog.text
    if failure in ('search', 'details', 'create'):
        assert 'HTTP status=503' in caplog.text
    if failure.startswith('create'):
        receipt = doc.entity_linking_journal[0]
        assert receipt['state'] == 'uncertain' and receipt['entity_id'] is None
        assert 'manual reconciliation' in caplog.text
        assert engine.db_api_service.create_entity.call_count == 2
        engine.process_document(doc)
        assert engine.db_api_service.create_entity.call_count == 2
        assert receipt is doc.entity_linking_journal[0] and first.identity.peoplegator_id is None
        assert '2 processed; 1 linked; 0 failed; 1 skipped' in caplog.text
    else:
        engine.db_api_service.create_entity.assert_called_once_with(
            name=later.name, aliases=[], description='French painter', short_description='')


@pytest.mark.parametrize('interrupt', [KeyboardInterrupt, SystemExit])
def test_interrupts_still_propagate(engine, interrupt):
    doc = document()
    engine.llm_prompter.side_effect = interrupt()
    with pytest.raises(interrupt):
        engine.process_document(doc)
    engine.db_api_service.create_entity.assert_not_called()


@pytest.mark.parametrize('fmt', ['alto', 'page'])
@pytest.mark.parametrize('failure', ['selection', 'request', 'response'])
def test_parse_folder_exports_failed_face_diagnostics_and_normal_outputs(
        tmp_path, monkeypatch, caplog, fmt, failure):
    import shutil
    import sys
    import cv2
    import numpy as np
    from lxml import etree
    from people_gator.core import document_parser
    from user_scripts import parse_folder
    from test_face_prompts import install_provider
    from pathlib import Path
    doc = document(fmt)
    doc.text_entity_clusters = []
    for page in doc.page_layouts:
        page.text_entities = []
        face(page)
        doc.page_images[page.id] = np.full((*page.page_size, 3), 255, dtype=np.uint8)
    first, later = doc.faces
    later.face_metadata.page_identity.identity.name = 'private-later'
    earlier = dict(engine='LLM_FACE_ASSIGNMENT', prompt='private-earlier', response='private-earlier')
    first.face_metadata.prompts.append(earlier)
    # ALTO enrichment reads the original tree. PAGE fixtures use PAGE output;
    # source-less face ALTO conversion has a documented, unrelated namespace bug.
    if fmt == 'alto':
        source = tmp_path / 'source'
        source.mkdir()
        for page in doc.page_layouts:
            shutil.copyfile(Path(__file__).parent / 'resources/text_chunking/input.alto.xml', source / (page.id + '.xml'))
        doc.alto_xmls_dir = str(source)
    hit = candidate()
    db = Mock()
    db.search_entities.return_value = {'items': [hit]}
    db.get_entity_info.return_value = hit
    monkeypatch.setattr(document_parser, 'DatabaseApiService', Mock(return_value=db))
    valid = dict(action='select', source_is_person=True, item_id=0, name=hit['name'], reason='private-reason')
    invalid = dict(valid, name='private-mismatched-name')
    raw = json.dumps(invalid, ensure_ascii=False) if failure == 'selection' else '{private-malformed-response'
    attempts = 1 if failure == 'selection' else 3
    failed_response = OSError('private-provider-payload') if failure == 'request' else NS(status='completed', output_text=raw)
    provider = Mock(side_effect=[*[failed_response] * attempts, NS(status='completed', output_text=json.dumps(valid))])
    install_provider(monkeypatch, provider)
    config = tmp_path / 'config.ini'
    prompt = tmp_path / 'prompt.json'
    prompt.write_text(json.dumps({'user': '{{ name }} {{ context }} {{ entities }}'}))
    outputs = {name: tmp_path / name for name in ('xml', 'alto', 'renders', 'prompts')}
    config.write_text(f'''[PARSE_FOLDER]
OUTPUT_XML_PATH = {outputs['xml']}
OUTPUT_ALTO_PATH = {outputs['alto'] if fmt == 'alto' else ''}
OUTPUT_RENDER_PATH = {outputs['renders']}
OUTPUT_FACE_PROMPTS_PATH = {outputs['prompts']}
[DB_API]
API_URL = https://example.invalid
[ENGINE_1]
METHOD = ENTITY_MATCHING
PROMPT_TEMPLATE_PATH = {prompt}
API_KEY = private-api-key
''')
    monkeypatch.setattr(sys, 'argv', ['peoplegator', '--config', str(config), '--device', 'cpu', '--logging-level', 'DEBUG'])
    monkeypatch.setattr(parse_folder, 'load_document', Mock(return_value=doc))
    with caplog.at_level(logging.DEBUG):
        assert parse_folder.main() == 0
    assert first.face_metadata.page_identity.identity.peoplegator_id is None
    assert later.face_metadata.page_identity.identity.peoplegator_id == 'existing'
    records = first.face_metadata.prompts
    assert records[0] == earlier and len(records) == attempts + 1
    assert all(r['response'] == (None if failure == 'request' else raw) for r in records[1:])
    assert all(r['engine'] == 'ENTITY_MATCHING' and 'Karel Čapek' in r['prompt'] for r in records[1:])
    exported = [json.loads(p.read_text(encoding='utf-8')) for p in outputs['prompts'].glob('*.json')]
    assert records in exported and later.face_metadata.prompts in exported and len(exported) == 2
    for name in (('xml', 'alto') if fmt == 'alto' else ('xml',)):
        files = list(outputs[name].glob('*.xml'))
        assert len(files) == 2
        for path in files:
            etree.parse(str(path))
    for page in doc.page_layouts:
        assert cv2.imread(str(outputs['renders'] / (page.id + '.jpg'))) is not None
    db.create_entity.assert_not_called()
    assert 'private-' not in caplog.text and 'Karel Čapek' not in caplog.text
    assert '2 processed; 1 linked; 1 failed; 0 skipped' in caplog.text


def test_zero_candidates_invalid_selection_and_summary_skips(engine, caplog):
    doc = face_only(identity('first'), identity('later'), identity('unknown'), identity('protected', 'keep'))
    engine.llm_prompter.side_effect = [decision('select', 0), decision()]
    with caplog.at_level(logging.DEBUG):
        assert engine.process_document(doc) is doc
    assert 'invalid/unavailable candidate index; candidate_count=0; candidate_index=0' in caplog.text
    assert '4 processed; 1 linked; 1 failed; 2 skipped' in caplog.text
    engine.db_api_service.create_entity.assert_not_called()


@pytest.mark.parametrize('status', ['private-status', {'private': 'response'}, True, 999])
def test_arbitrary_external_status_is_not_logged(engine, caplog, status):
    error = RuntimeError('private-payload')
    error.status_code = status
    engine.db_api_service.search_entities.side_effect = error
    assert engine.process_document(document()) is not None
    assert 'private' not in caplog.text and 'HTTP status=' not in caplog.text
