"""Review regressions: reject unusable detector prompts before pages or requests."""

import builtins
from configparser import ConfigParser
import json
from pathlib import Path
from unittest.mock import Mock

import pytest


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


def invalid_configuration(tmp_path, case, monkeypatch):
    config = ConfigParser()
    config.read_dict({'ENGINE_1': {'METHOD': 'TEXT_ENTITY_DETECTION'}})
    path = tmp_path / 'prompt.json'
    if case == 'missing-path':
        return config
    config['ENGINE_1']['PROMPT_TEMPLATE_PATH'] = 'prompt.json'
    if case in ('empty-path', 'whitespace-path'):
        config['ENGINE_1']['PROMPT_TEMPLATE_PATH'] = '' if case == 'empty-path' else '  \t '
        return config
    if case == 'missing-file':
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


@pytest.mark.parametrize('case', BAD_PROMPTS)
def test_invalid_prompt_fails_initialization_before_prompter(case, tmp_path, monkeypatch):
    from people_gator.core.document_parser import engine_factory
    from people_gator.engines import llm
    from people_gator.engines.text_entity_detection import TextEntityPromptError
    config = invalid_configuration(tmp_path, case, monkeypatch)
    prompter = Mock()
    client = Mock()
    monkeypatch.setattr(llm, 'LLMPrompter', prompter)
    monkeypatch.setattr(llm, 'OpenAI', client)
    with pytest.raises(TextEntityPromptError) as caught:
        engine_factory(config['ENGINE_1'], config_path=str(tmp_path), device='cpu')
    assert 'TEXT_ENTITY_DETECTION' in str(caught.value)
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
    assert 'TEXT_ENTITY_DETECTION' in caplog.text
    assert 'private-prompt-contents' not in caplog.text
    assert output.read_text() == 'earlier result'
    loader.assert_not_called()
    prompter.assert_not_called()
    client.assert_not_called()


@pytest.mark.parametrize('content,roles', [
    ({'user': '{{ text }}'}, ['user']),
    ({'system': 'Extract from {{ text }}'}, ['system']),
    ({'system': 'Extract beings.', 'user': '{{ text }}'}, ['system', 'user']),
    ({'system': ' \n\t', 'user': '{{ text }}'}, ['user']),
    ({'system': '{{ text }}', 'user': ''}, ['system']),
])
def test_valid_prompt_uses_text_and_preserves_shared_configuration(content, roles, tmp_path, monkeypatch):
    from people_gator.core.document_parser import engine_factory
    from people_gator.engines import llm
    (tmp_path / 'prompt.json').write_text(json.dumps(content), encoding='utf-8')
    config = ConfigParser()
    config.read_dict({'ENGINE_1': {'METHOD': 'TEXT_ENTITY_DETECTION', 'PROMPT_TEMPLATE_PATH': 'prompt.json'}})
    client = Mock()
    monkeypatch.setattr(llm, 'OpenAI', client)
    detector = engine_factory(config['ENGINE_1'], config_path=str(tmp_path), device='cpu')
    request = detector.llm_prompter._prepare_request_args({'text': 'Unicode OCR 😀'})
    assert [message['role'] for message in request['input']] == roles
    assert any('Unicode OCR 😀' in message['content'][0]['text'] for message in request['input'])
    assert all(message['content'][0]['text'].strip() for message in request['input'])
    client.assert_not_called()


@pytest.mark.parametrize('content', [None, {}])
def test_other_llm_engines_still_allow_unset_templates(content, tmp_path):
    from people_gator.engines.entity_matching import EntityMatchingEngine
    config = ConfigParser()
    config.read_dict({'ENGINE_1': {'METHOD': 'ENTITY_MATCHING'}})
    if content is not None:
        (tmp_path / 'prompt.json').write_text(json.dumps(content))
        config['ENGINE_1']['PROMPT_TEMPLATE_PATH'] = 'prompt.json'
    detector = EntityMatchingEngine(config['ENGINE_1'], 'cpu', str(tmp_path))
    assert detector.prompt_template_system is detector.prompt_template_user is None
