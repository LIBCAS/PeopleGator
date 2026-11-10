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
    llm, create = prompter_client(monkeypatch, [NS(output_text='{"private": "sensitive"}'),
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
