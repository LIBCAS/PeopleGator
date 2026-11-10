"""Shared LLM prompt configuration and template/data diagnostics regressions."""

import builtins
from configparser import ConfigParser
import json
from pathlib import Path
from unittest.mock import Mock

import pytest


ENGINE_METHODS = ['LLM_FACE_ASSIGNMENT', 'LLM_BATCH_FACE_ASSIGNMENT', 'ENTITY_MATCHING', 'TEXT_ENTITY_DETECTION']


BAD_PROMPTS = [
    'missing-path', 'empty-path', 'whitespace-path', 'missing-file', 'unreadable-file',
    'empty-file', 'invalid-json', 'invalid-encoding', 'empty-object', 'no-roles',
    'null-roles', 'empty-roles', 'whitespace-roles', 'non-string-role',
    'non-object-json', 'invalid-jinja',
]


@pytest.fixture(autouse=True)
def processing_only(runtime_mode):
    if runtime_mode == 'client':
        pytest.skip('Text detector prompts require processing extras')


def invalid_configuration(tmp_path, case, monkeypatch, method="TEXT_ENTITY_DETECTION"):
    config = ConfigParser()
    config.read_dict({'ENGINE_1': {'METHOD': method}})
    path = tmp_path / 'prompt.json'
    if case == 'missing-path':
        return config
    config['ENGINE_1']['PROMPT_TEMPLATE_PATH'] = 'prompt.json'
    if case in ('empty-path', 'whitespace-path'):
        config['ENGINE_1']['PROMPT_TEMPLATE_PATH'] = '' if case == 'empty-path' else '  \t '
        return config
    if case == 'missing-file':
        config['ENGINE_1']['PROMPT_TEMPLATE_PATH'] = 'private-prompt-contents.json'
        return config
    content = {
        'empty-file': '', 'invalid-json': '{"user": "private-prompt-contents',
        'invalid-encoding': b'\xff\xfe', 'empty-object': {}, 'no-roles': {'other': 'private-prompt-contents'},
        'null-roles': {'system': None, 'user': None},
        'empty-roles': {'system': '', 'user': ''},
        'whitespace-roles': {'system': '  \n\t', 'user': '\n  '},
        'non-string-role': {'system': ['private-prompt-contents'], 'user': '{{ text }}'},
        'non-object-json': ['private-prompt-contents'],
        'invalid-jinja': {'user': '{{ private-prompt-contents'},
        'unreadable-file': {'user': '{{ text }}'},
    }[case]
    if isinstance(content, bytes):
        path.write_bytes(content)
    else:
        path.write_text(content if isinstance(content, str) else json.dumps(content), encoding='utf-8')
    if case == 'unreadable-file':
        original = builtins.open
        def deny_prompt(file, *args, **kwargs):
            if Path(file) == path:
                raise PermissionError('private-prompt-contents')
            return original(file, *args, **kwargs)
        monkeypatch.setattr(builtins, 'open', deny_prompt)
    return config


@pytest.mark.parametrize('method', ENGINE_METHODS)
@pytest.mark.parametrize('case', BAD_PROMPTS)
def test_invalid_prompt_fails_initialization_before_prompter(method, case, tmp_path, monkeypatch):
    from people_gator.core.document_parser import engine_factory
    from people_gator.engines import llm
    from people_gator.engines.llm import LLMPromptConfigurationError
    config = invalid_configuration(tmp_path, case, monkeypatch, method)
    prompter = Mock()
    client = Mock()
    monkeypatch.setattr(llm, 'LLMPrompter', prompter)
    monkeypatch.setattr(llm, 'OpenAI', client)
    with pytest.raises(LLMPromptConfigurationError) as caught:
        engine_factory(config['ENGINE_1'], config_path=str(tmp_path), device='cpu')
    assert 'PROMPT_TEMPLATE_PATH' in str(caught.value) or 'system/user' in str(caught.value)
    assert 'private-prompt-contents' not in str(caught.value)
    prompter.assert_not_called()
    client.assert_not_called()


@pytest.mark.parametrize('case', BAD_PROMPTS)
def test_invalid_prompt_cli_is_safe_and_loads_no_pages(case, tmp_path, monkeypatch, caplog, capsys):
    from user_scripts import detect_text_entities as cli
    from people_gator.engines import llm
    config = invalid_configuration(tmp_path, case, monkeypatch)
    path = tmp_path / 'config.ini'
    with path.open('w', encoding='utf-8') as stream:
        config.write(stream)
    loader, prompter, client = Mock(), Mock(), Mock()
    monkeypatch.setattr(cli, 'load_document', loader)
    monkeypatch.setattr(llm, 'LLMPrompter', prompter)
    monkeypatch.setattr(llm, 'OpenAI', client)
    output = tmp_path / 'output.json'
    output.write_text('earlier result')
    assert cli.main(['--config', str(path), '--input-alto-path', str(tmp_path / 'not-loaded'),
                     '--output-path', str(output)]) == 1
    assert capsys.readouterr().out == ''
    assert 'PROMPT_TEMPLATE_PATH' in caplog.text or 'system/user' in caplog.text
    assert 'private-prompt-contents' not in caplog.text
    assert output.read_text() == 'earlier result'
    loader.assert_not_called()
    prompter.assert_not_called()
    client.assert_not_called()


@pytest.mark.parametrize('method', ENGINE_METHODS)
@pytest.mark.parametrize('content,roles', [
    ({'user': '{{ text }}'}, ['user']),
    ({'system': 'Extract from {{ text }}'}, ['system']),
    ({'system': 'Extract beings.', 'user': '{{ text }}'}, ['system', 'user']),
    ({'system': ' \n\t', 'user': '{{ text }}'}, ['user']),
    ({'system': '{{ text }}', 'user': ''}, ['system']),
])
def test_valid_prompt_uses_text_and_preserves_shared_configuration(method, content, roles, tmp_path, monkeypatch):
    from people_gator.core.document_parser import engine_factory
    from people_gator.engines import llm
    (tmp_path / 'prompt.json').write_text(json.dumps(content), encoding='utf-8')
    config = ConfigParser()
    config.read_dict({'ENGINE_1': {'METHOD': method, 'PROMPT_TEMPLATE_PATH': 'prompt.json'}})
    client = Mock()
    monkeypatch.setattr(llm, 'OpenAI', client)
    detector = engine_factory(config['ENGINE_1'], config_path=str(tmp_path), device='cpu')
    request = detector.llm_prompter._prepare_request_args({'text': 'Unicode OCR 😀'})
    assert [message['role'] for message in request['input']] == roles
    assert any('Unicode OCR 😀' in message['content'][0]['text'] for message in request['input'])
    assert all(message['content'][0]['text'].strip() for message in request['input'])
    client.assert_not_called()


def test_all_inheritors_use_shared_validation():
    from people_gator.engines.llm import LLMBasedEngine
    from people_gator.engines.face_assignment import LLMFaceAssignmentEngine, LLMBatchFaceAssignmentEngine
    from people_gator.engines.entity_matching import EntityMatchingEngine
    from people_gator.engines.text_entity_detection import LLMTextEntityDetectionEngine
    for cls in (LLMFaceAssignmentEngine, LLMBatchFaceAssignmentEngine, EntityMatchingEngine, LLMTextEntityDetectionEngine):
        assert cls.load_prompt_template is LLMBasedEngine.load_prompt_template
        assert 'load_prompt_template' not in cls.__dict__


class InlinePool:
    """Run prepared parallel requests locally while preserving the pool call shape."""

    def __init__(self, processes):
        self.processes = processes

    def __enter__(self):
        return self

    def __exit__(self, *args):
        return None

    def starmap(self, function, arguments):
        return [function(*args) for args in arguments]


@pytest.mark.parametrize('parallel', [False, True])
@pytest.mark.parametrize('system,user,data,missing,unused', [
    (None, '{{ texxt }}', {'text': 'private-payload-value'}, {'texxt'}, {'text'}),
    ('{{ context }}', '{{ text }}', {'context': 'private-payload-value', 'text': 'private-payload-value'}, set(), set()),
    ('{{ shared }} {{ context }}', '{{ shared }} {{ text }}',
     {'shared': 'private-payload-value', 'context': 'private-payload-value', 'text': 'private-payload-value'}, set(), set()),
    ('{{ first }} {{ second }}', '{{ first }} {{ third }}',
     {'extra1': 'private-payload-value', 'extra2': 'private-payload-value'}, {'first', 'second', 'third'}, {'extra1', 'extra2'}),
    (None, "{{ absent | default('fallback') }}", {}, {'absent'}, set()),
    ('{% for i in range(count) %}{{ i }}{% endfor %}', '{{ text }}',
     {'count': 2, 'text': 'private-payload-value'}, set(), set()),
])
def test_template_data_warnings_are_shared_nonfatal_and_safe(system, user, data, missing, unused,
                                                            parallel, monkeypatch, caplog):
    import logging
    from types import SimpleNamespace as NS
    from people_gator.engines import llm
    create = Mock(return_value=NS(output_text='{"ok": true}'))
    monkeypatch.setattr(llm, 'OpenAI', Mock(return_value=NS(responses=NS(create=create))))
    monkeypatch.setattr(llm.multiprocessing, 'Pool', InlinePool)
    prompter = llm.LLMPrompter('https://example.invalid', 'private-api-value', 'mock',
                              prompt_template_system=system, prompt_template_user=user)
    count = 2 if parallel else 1
    with caplog.at_level(logging.WARNING, logger=llm.__name__):
        if parallel:
            assert prompter.process_parallel([data, data]) == [{'ok': True}, {'ok': True}]
        else:
            assert prompter(data) == {'ok': True}
    expected = [f'LLM template placeholder {name} is missing from data' for name in sorted(missing)]
    expected += [f'LLM data key {name} is unused by system/user templates' for name in sorted(unused)]
    records = [record for record in caplog.records if record.name == llm.__name__]
    assert len(records) == len(expected) * count
    assert all(record.levelno == logging.WARNING for record in records)
    for message in expected:
        assert [record.getMessage() for record in records].count(message) == count
    assert create.call_count == count
    assert 'private-payload-value' not in caplog.text
    assert 'private-api-value' not in caplog.text
    if 'texxt' in missing:
        assert create.call_args.kwargs['input'][0]['content'][0]['text'] == ''
    if 'absent' in missing:
        assert create.call_args.kwargs['input'][0]['content'][0]['text'] == 'fallback'


@pytest.mark.parametrize('method', ENGINE_METHODS)
@pytest.mark.parametrize('parallel', [False, True])
def test_all_engine_response_models_keep_existing_shared_request_contract(method, parallel, tmp_path,
                                                                        monkeypatch, caplog):
    import logging
    from types import SimpleNamespace as NS
    from people_gator.core.document_parser import engine_factory
    from people_gator.engines import llm
    from people_gator.engines.face_assignment import FaceAssignmentResult, BatchFaceAssignmentResult
    from people_gator.engines.entity_matching import EntityMatchingResult
    from people_gator.engines.text_entity_detection import TextEntityDetectionResult
    cases = {
        'LLM_FACE_ASSIGNMENT': (FaceAssignmentResult,
            {'face_coordinates': (0, 0, 1, 1), 'context_text': 'private-payload-value', 'caption_text': ''},
            {'name_normalized': 'Candidate', 'name_in_text': None}),
        'LLM_BATCH_FACE_ASSIGNMENT': (BatchFaceAssignmentResult,
            {'faces': [], 'context_text': 'private-payload-value', 'caption_text': ''}, {'faces': []}),
        'ENTITY_MATCHING': (EntityMatchingResult,
            {'name': 'private-payload-value', 'context': '', 'entities': []}, {'item_id': None, 'name': None}),
        'TEXT_ENTITY_DETECTION': (TextEntityDetectionResult, {'text': 'private-payload-value'}, {'entities': []}),
    }
    model, data, payload = cases[method]
    (tmp_path / 'prompt.json').write_text(json.dumps({'user': ' '.join('{{ ' + key + ' }}' for key in data)}))
    config = ConfigParser()
    config.read_dict({'ENGINE_1': {'METHOD': method, 'PROMPT_TEMPLATE_PATH': 'prompt.json',
                                  'API_URL': 'https://example.invalid', 'API_KEY': 'private-api-value', 'MODEL_NAME': 'mock'}})
    engine = engine_factory(config['ENGINE_1'], config_path=str(tmp_path), device='cpu')
    create = Mock(return_value=NS(output_text=json.dumps(payload)))
    monkeypatch.setattr(llm, 'OpenAI', Mock(return_value=NS(responses=NS(create=create))))
    monkeypatch.setattr(llm.multiprocessing, 'Pool', InlinePool)
    with caplog.at_level(logging.WARNING, logger=llm.__name__):
        results = engine.llm_prompter.process_parallel([data, data], response_model=model) if parallel else [
            engine.llm_prompter(data, response_model=model)]
    assert all(isinstance(result, model) and result.model_dump() == payload for result in results)
    assert create.call_count == (2 if parallel else 1)
    assert create.call_args.kwargs['text']['format']['schema'] == model.model_json_schema()
    assert not [record for record in caplog.records if record.name == llm.__name__]
