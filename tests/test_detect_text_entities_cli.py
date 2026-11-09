"""Diagnostic CLI contracts using real XML loaders and mocked LLM responses."""

from pathlib import Path
import json
import subprocess
import sys
from unittest.mock import Mock

import pytest


@pytest.fixture(autouse=True)
def processing_only(runtime_mode):
    if runtime_mode == 'client':
        pytest.skip('Diagnostic detection requires processing extras')


@pytest.fixture
def cli_input(tmp_path, monkeypatch):
    from people_gator.engines.llm import LLMPrompter
    from people_gator.core.layout import PeopleGatorDocument
    from people_gator.core.db import DatabaseApiService

    config = tmp_path / 'config.ini'
    config.write_text('''[ENGINE_FACE]
METHOD = FACE_DETECTION_YOLO
MODEL_PATH = missing-model
[ENGINE_TEXT]
METHOD = TEXT_ENTITY_DETECTION
[ENGINE_LINK]
METHOD = ENTITY_MATCHING
[DB_API]
api_url = invalid
''')
    # Any image or database access must fail the test, even without credentials.
    monkeypatch.setattr(PeopleGatorDocument, 'load_page_image', Mock(side_effect=AssertionError('images')))
    monkeypatch.setattr(DatabaseApiService, '__init__', Mock(side_effect=AssertionError('database')))
    response = {'entities': [{'name': 'Karel Čapek', 'type': 'being', 'info': 'spisovatel',
                             'mentions': [{'name': 'Čapek', 'context': 'Čapek 😀'},
                                          {'name': 'Karel \nMarie', 'context': ' Karel \nMarie'}]}]}
    prompter = Mock(return_value=response)
    monkeypatch.setattr(LLMPrompter, '__call__', prompter)
    return config, prompter


def xml_directory(tmp_path, format, pages=2):
    directory = tmp_path / 'input'
    directory.mkdir()
    fixture = Path(__file__).parent / 'resources' / 'text_chunking' / f'input.{format}.xml'
    for index in range(pages):
        (directory / f'{index}.xml').write_text(fixture.read_text(), encoding='utf-8')
    return directory


@pytest.mark.parametrize('format,option', [('alto', '--input-alto-path'), ('page', '--input-xml-path')])
def test_json_real_xml_and_only_detector(format, option, tmp_path, monkeypatch, cli_input, capsys):
    from user_scripts import detect_text_entities as cli
    import people_gator.core.document_parser as parser
    config, prompter = cli_input
    factory = Mock(wraps=parser.engine_factory)
    monkeypatch.setattr(parser, 'engine_factory', factory)
    directory = xml_directory(tmp_path, format)
    output = tmp_path / 'new' / 'entities.json'
    args = ['--config', str(config), option, str(directory), '--output-path', str(output)]
    assert cli.main(args) == 0
    factory.assert_called_once()
    assert factory.call_args.args[0].name == 'ENGINE_TEXT'
    assert factory.call_args.kwargs == {'config_path': str(tmp_path), 'device': 'cpu'}
    assert prompter.call_count == 2
    assert capsys.readouterr().out == ''
    raw = output.read_text(encoding='utf-8')
    assert 'Čapek' in raw and 'spisovatel' in raw
    result = json.loads(raw)
    assert set(result) == {'document_id', 'mentions'}
    assert result['document_id'] is None
    assert len(result['mentions']) == 4
    for index, mention in enumerate(result['mentions']):
        assert set(mention) == {'name', 'proposed_name', 'description', 'context', 'source_spans'}
        assert mention['proposed_name'] == 'Karel Čapek'
        assert mention['description'] == 'spisovatel'
        assert [s['page_index'] for s in mention['source_spans']] == [index // 2] * len(mention['source_spans'])
        for span in mention['source_spans']:
            assert set(span) == {'page_id', 'region_id', 'line_id', 'page_index',
                                 'region_index', 'line_index', 'start', 'end'}
    loaded_page = cli.load_document(directory, alto=format == 'alto').page_layouts[0]
    region_index = next(i for i, region in enumerate(loaded_page.regions) if region.id == 'r2')
    assert result['mentions'][0]['source_spans'][0] == {
        'page_id': loaded_page.id, 'region_id': 'r2', 'line_id': 'l3', 'page_index': 0,
        'region_index': region_index, 'line_index': 0, 'start': 0, 'end': 5}
    multiline = result['mentions'][1]
    assert multiline['name'] == 'Karel \nMarie'
    assert multiline['context'] == ' Karel \nMarie'
    assert [(s['start'], s['end']) for s in multiline['source_spans']] == [(1, 7), (0, 5)]
    assert [s['line_id'] for s in multiline['source_spans']] == ['l1', 'l2']
    # Same established input ordering and deterministic responses yield stable JSON.
    assert cli.main(args) == 0
    assert output.read_text(encoding='utf-8') == raw


def test_stdout_and_empty_modes(tmp_path, cli_input, capsys):
    from user_scripts import detect_text_entities as cli
    config, prompter = cli_input
    directory = xml_directory(tmp_path, 'page', pages=1)
    args = ['--config', str(config), '--input-xml-path', str(directory)]
    assert cli.main(args) == 0
    output = capsys.readouterr().out
    assert 'Detected 2' in output and 'Čapek' in output and 'chars [0, 5)' in output
    assert 'region' in output and 'line' in output and 'page' in output
    prompter.return_value = {'entities': []}
    assert cli.main(args) == 0
    assert capsys.readouterr().out == 'No text entity mentions detected.\n'
    target = tmp_path / 'empty.json'
    assert cli.main(args + ['--output-path', str(target)]) == 0
    assert json.loads(target.read_text()) == {'document_id': None, 'mentions': []}


@pytest.mark.parametrize('config_text,count', [('[ENGINE_FACE]\nMETHOD=FACE_DETECTION_YOLO\n', 0),
    ('[ENGINE_A]\nMETHOD=TEXT_ENTITY_DETECTION\n[ENGINE_B]\nMETHOD=TEXT_ENTITY_DETECTION\n', 2)])
def test_missing_or_ambiguous_detector(config_text, count, tmp_path, capsys):
    from user_scripts import detect_text_entities as cli
    config = tmp_path / 'config.ini'
    config.write_text(config_text)
    target = tmp_path / 'output.json'
    assert cli.main(['--config', str(config), '--input-xml-path', str(tmp_path), '--output-path', str(target)]) == 1
    captured = capsys.readouterr()
    assert not captured.out and f'found {count}' in captured.err and 'exactly one' in captured.err
    assert not target.exists()


@pytest.mark.parametrize('kind', ['missing', 'not-directory', 'empty', 'malformed', 'wrong-format', 'no-page', 'unreadable'])
def test_bad_xml_inputs(kind, tmp_path, cli_input, capsys, monkeypatch):
    from user_scripts import detect_text_entities as cli
    config, prompter = cli_input
    directory = tmp_path / 'input'
    if kind == 'not-directory':
        directory.write_text('file')
    elif kind != 'missing':
        directory.mkdir()
        if kind in ('malformed', 'wrong-format', 'no-page', 'unreadable'):
            (directory / 'input.xml').write_text({'malformed': '<private-ocr', 'wrong-format': '<alto><Page/></alto>',
                                                'no-page': '<PcGts/>', 'unreadable': '<PcGts><Page/></PcGts>'}[kind])
        if kind == 'unreadable':
            from lxml import etree
            monkeypatch.setattr(etree, 'parse', Mock(side_effect=PermissionError('private credentials')))
    assert cli.main(['--config', str(config), '--input-xml-path', str(directory)]) == 1
    captured = capsys.readouterr()
    assert not captured.out and 'Error:' in captured.err
    assert 'private' not in captured.err
    prompter.assert_not_called()


@pytest.mark.parametrize('kind', ['missing', 'malformed', 'invalid-option', 'unreadable'])
def test_bad_config(kind, tmp_path, capsys, monkeypatch):
    from user_scripts import detect_text_entities as cli
    config = tmp_path / 'config.ini'
    if kind != 'missing':
        config.write_text('[secret credentials' if kind == 'malformed' else
                          '[ENGINE_TEXT]\nMETHOD=TEXT_ENTITY_DETECTION\nCHUNKING_MAX_CHARS=invalid\n')
    if kind == 'unreadable':
        monkeypatch.setattr(Path, 'open', Mock(side_effect=PermissionError('secret credentials')))
    assert cli.main(['--config', str(config), '--input-xml-path', str(tmp_path)]) == 1
    captured = capsys.readouterr()
    assert not captured.out and 'Configuration failed' in captured.err
    assert 'secret' not in captured.err


@pytest.mark.parametrize('existing', [False, True])
def test_detection_failure_no_partial_output(tmp_path, cli_input, capsys, existing):
    from user_scripts import detect_text_entities as cli
    config, prompter = cli_input
    directory = xml_directory(tmp_path, 'page')
    prompter.side_effect = [prompter.return_value, RuntimeError('secret OCR and credentials')]
    output = tmp_path / 'output.json'
    if existing:
        output.write_text('previous complete result')
    assert cli.main(['--config', str(config), '--input-xml-path', str(directory), '--output-path', str(output)]) == 1
    captured = capsys.readouterr()
    assert not captured.out and 'Text detection failed' in captured.err and 'secret' not in captured.err
    assert output.read_text() == 'previous complete result' if existing else not output.exists()


def test_atomic_output_write_failure(tmp_path, cli_input, monkeypatch, capsys):
    from user_scripts import detect_text_entities as cli
    config, _ = cli_input
    directory = xml_directory(tmp_path, 'page', pages=1)
    output = tmp_path / 'output.json'
    output.write_text('previous complete result')
    monkeypatch.setattr(cli.os, 'replace', Mock(side_effect=PermissionError('secret')))
    assert cli.main(['--config', str(config), '--input-xml-path', str(directory), '--output-path', str(output)]) == 1
    captured = capsys.readouterr()
    assert not captured.out and 'Output writing failed' in captured.err and 'secret' not in captured.err
    assert output.read_text() == 'previous complete result'
    assert not list(tmp_path.glob('.entities-*.tmp'))


def test_output_parent_failure(tmp_path, cli_input, capsys):
    from user_scripts import detect_text_entities as cli
    config, _ = cli_input
    directory = xml_directory(tmp_path, 'page', pages=1)
    parent = tmp_path / 'file'
    parent.write_text('existing')
    assert cli.main(['--config', str(config), '--input-xml-path', str(directory), '--output-path', str(parent / 'out.json')]) == 1
    assert 'Output writing failed' in capsys.readouterr().err
    assert parent.read_text() == 'existing'


@pytest.mark.parametrize('arguments', [[], ['--config', 'c'], ['--config', 'c', '--input-alto-path', 'a', '--input-xml-path', 'p']])
def test_required_arguments(arguments):
    from user_scripts.detect_text_entities import main
    with pytest.raises(SystemExit) as error:
        main(arguments)
    assert error.value.code == 2


def test_module_help_and_nonzero_process(tmp_path):
    result = subprocess.run([sys.executable, '-m', 'user_scripts.detect_text_entities', '--help'],
                            text=True, capture_output=True, cwd=tmp_path)
    assert result.returncode == 0
    assert all(option in result.stdout for option in ('--config', '--input-alto-path', '--input-xml-path', '--output-path'))
    result = subprocess.run([sys.executable, '-m', 'user_scripts.detect_text_entities', '--config', str(tmp_path / 'missing'),
                             '--input-xml-path', str(tmp_path)], text=True, capture_output=True, cwd=tmp_path)
    assert result.returncode != 0 and not result.stdout and 'Configuration failed' in result.stderr


def test_nullable_detection_metadata_and_missing_ids():
    from types import SimpleNamespace as NS
    from people_gator.core.layout import PeopleGatorDocument, PeopleGatorTextEntityMention
    from people_gator.text import SourceSpan, SourceLine
    from user_scripts.detect_text_entities import detection_result

    spans = (SourceSpan(SourceLine(0, None, 1, None, 2, None), 3, 5),)
    mention = PeopleGatorTextEntityMention('😀é', '😀é here', source_spans=spans)
    doc = PeopleGatorDocument(page_layouts=[NS(text_entities=[mention])])
    result = detection_result(doc)
    assert result['document_id'] is None
    assert result['mentions'][0]['proposed_name'] is None
    assert result['mentions'][0]['description'] is None
    assert result['mentions'][0]['source_spans'] == [
        {'page_id': None, 'region_id': None, 'line_id': None, 'page_index': 0,
         'region_index': 1, 'line_index': 2, 'start': 3, 'end': 5}]
