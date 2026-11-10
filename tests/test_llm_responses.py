"""Safe Responses API completion diagnostics and truncated-output rejection."""

import json
import logging
from types import SimpleNamespace as NS
from unittest.mock import Mock

import pytest


@pytest.fixture(autouse=True)
def processing_only(runtime_mode):
    if runtime_mode == 'client':
        pytest.skip('LLM processing requires the tool extra')


def prompter_client(monkeypatch, responses):
    from people_gator.engines import llm
    create = Mock(side_effect=responses)
    monkeypatch.setattr(llm, 'OpenAI', Mock(return_value=NS(responses=NS(create=create))))
    return llm, create


@pytest.mark.parametrize('text', ['', '{"entities": [', '{"entities": []}'])
def test_output_token_limit_is_not_json_error_or_identically_retried(text, monkeypatch, caplog):
    response = NS(status='incomplete', incomplete_details=NS(reason='max_output_tokens'), output_text=text)
    llm, create = prompter_client(monkeypatch, [response])
    request = {'max_output_tokens': 1500}
    with caplog.at_level(logging.DEBUG):
        assert llm.LLMPrompter._send_request('https://example.invalid', 'secret', request, 3, None) is None
    assert create.call_count == 1
    assert request == {'max_output_tokens': 1500}
    assert 'MAX_OUTPUT_TOKENS=1500' in caplog.text
    assert 'reasoning tokens' in caplog.text
    assert 'JSONDecodeError' not in caplog.text
    assert 'secret' not in caplog.text


def test_incomplete_response_never_returns_previous_invalid_candidate(monkeypatch, caplog):
    llm, create = prompter_client(monkeypatch, [NS(status='completed', output_text='{"private": "sensitive"}'),
        NS(status='incomplete', incomplete_details=NS(reason='max_output_tokens'), output_text='')])
    assert llm.LLMPrompter._send_request('https://example.invalid', 'secret', {'max_output_tokens': 1500},
        3, {'type': 'object', 'required': ['required']}) is None
    assert create.call_count == 2
    assert 'sensitive' not in caplog.text


def test_http_json_error_has_distinct_safe_diagnostic(monkeypatch, caplog):
    llm, create = prompter_client(monkeypatch, [json.JSONDecodeError('bad', 'private response', 0)] * 2)
    assert llm.LLMPrompter._send_request('https://example.invalid', 'secret', {}, 2, None) is None
    assert create.call_count == 2
    assert 'HTTP response decoding' in caplog.text
    assert 'private response' not in caplog.text


def test_model_json_error_and_safe_token_metadata(monkeypatch, caplog):
    llm, create = prompter_client(monkeypatch, [NS(status='completed', output_text='private response',
        usage=NS(output_tokens=25, output_tokens_details=NS(reasoning_tokens=10)))])
    with caplog.at_level(logging.DEBUG):
        assert llm.LLMPrompter._send_request('https://example.invalid', 'secret', {}, 1, None) is None
    assert 'model output decoding' in caplog.text
    assert 'text characters=16, output tokens=25, reasoning tokens=10' in caplog.text
    assert 'private response' not in caplog.text


def test_complete_json_response_still_succeeds(monkeypatch):
    llm, create = prompter_client(monkeypatch, [NS(status='completed', output_text='{"entities": []}')])
    assert llm.LLMPrompter._send_request('https://example.invalid', 'secret', {}, 3, None) == {'entities': []}
    assert create.call_count == 1


@pytest.mark.parametrize('kind', ['json', 'schema', 'transport', 'http-json', 'incomplete', 'token-limit'])
@pytest.mark.parametrize('parallel', [False, True])
def test_opt_in_failure_types_preserve_request_vs_content(kind, parallel, monkeypatch, caplog):
    from people_gator.engines import llm
    from test_llm_prompts import InlinePool
    invalid = {
        'json': NS(status='completed', output_text='private invalid JSON'),
        'schema': NS(status='completed', output_text='{"private": "data"}'),
        'transport': OSError('private transport'),
        'http-json': json.JSONDecodeError('bad', 'private HTTP', 0),
        'incomplete': NS(status='incomplete', incomplete_details=NS(reason='other')),
        'token-limit': NS(status='incomplete', incomplete_details=NS(reason='max_output_tokens')),
    }[kind]
    create = Mock(side_effect=invalid if isinstance(invalid, Exception) else None, return_value=invalid)
    monkeypatch.setattr(llm, 'OpenAI', Mock(return_value=NS(responses=NS(create=create))))
    monkeypatch.setattr(llm.multiprocessing, 'Pool', InlinePool)
    prompter = llm.LLMPrompter('https://example.invalid', 'private-key', 'mock',
        prompt_template_user='{{ entities }}', json_schema={'type': 'object', 'required': ['clusters']},
        max_attempts=2, raise_on_failure=True)
    error = llm.LLMResponseError if kind in ['json', 'schema'] else llm.LLMRequestError
    with pytest.raises(error) as caught:
        if parallel:
            prompter.process_parallel([{'entities': 'private OCR'}])
        else:
            prompter({'entities': 'private OCR'})
    assert create.call_count == (1 if kind == 'token-limit' else 2)
    assert 'private' not in str(caught.value) + caplog.text


@pytest.mark.parametrize('status', ['failed', 'cancelled', 'queued', 'in_progress', 'unknown', None])
@pytest.mark.parametrize('text', ['', '{"ok": true}'])
@pytest.mark.parametrize('strict', [False, True])
def test_noncompleted_status_is_request_failure_before_parsing(status, text, strict, monkeypatch, caplog):
    response = NS(status=status, output_text=text)
    llm, create = prompter_client(monkeypatch, [response, response])
    with caplog.at_level(logging.DEBUG):
        if strict:
            with pytest.raises(llm.LLMRequestError):
                llm.LLMPrompter._send_request('https://example.invalid', 'private-key', {}, 2, None,
                                             raise_on_failure=True)
        else:
            assert llm.LLMPrompter._send_request('https://example.invalid', 'private-key', {}, 2, None) is None
    assert create.call_count == 2
    assert 'non-completed response' in caplog.text
    assert 'JSONDecodeError' not in caplog.text
    assert 'text characters=' not in caplog.text
    assert 'LLM request completed' not in caplog.text
    assert 'private-key' not in caplog.text


@pytest.mark.parametrize('strict', [False, True])
def test_noncompleted_status_retries_until_completed(monkeypatch, strict):
    llm, create = prompter_client(monkeypatch, [NS(status='failed', output_text='{"unusable": true}'),
        NS(status='completed', output_text='{"ok": true}')])
    assert llm.LLMPrompter._send_request('https://example.invalid', 'private-key', {}, 2, None,
                                       raise_on_failure=strict) == {'ok': True}
    assert create.call_count == 2


@pytest.mark.parametrize('strict', [False, True])
def test_failed_status_discards_previous_invalid_content(monkeypatch, strict):
    llm, create = prompter_client(monkeypatch, [NS(status='completed', output_text='{"private": true}'),
        NS(status='failed', output_text='')])
    schema = {'type': 'object', 'required': ['ok']}
    if strict:
        with pytest.raises(llm.LLMRequestError):
            llm.LLMPrompter._send_request('https://example.invalid', 'private-key', {}, 2, schema,
                                         raise_on_failure=True)
    else:
        assert llm.LLMPrompter._send_request('https://example.invalid', 'private-key', {}, 2, schema) is None
    assert create.call_count == 2


@pytest.mark.parametrize('strict', [False, True])
def test_missing_status_is_not_completed(monkeypatch, strict):
    llm, create = prompter_client(monkeypatch, [NS(output_text='{"ok": true}')])
    if strict:
        with pytest.raises(llm.LLMRequestError):
            llm.LLMPrompter._send_request('https://example.invalid', 'private-key', {}, 1, None,
                                         raise_on_failure=True)
    else:
        assert llm.LLMPrompter._send_request('https://example.invalid', 'private-key', {}, 1, None) is None
    assert create.call_count == 1


def test_failed_status_does_not_access_output_text(monkeypatch):
    from unittest.mock import PropertyMock
    response = Mock(status='failed')
    output = PropertyMock(side_effect=AssertionError('Output must not be read'))
    type(response).output_text = output
    llm, create = prompter_client(monkeypatch, [response])
    with pytest.raises(llm.LLMRequestError):
        llm.LLMPrompter._send_request('https://example.invalid', 'private-key', {}, 1, None,
                                     raise_on_failure=True)
    output.assert_not_called()
