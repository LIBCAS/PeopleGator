"""Deployment examples and explicit INI selection through the real prompt loader."""

from configparser import ConfigParser
import json
from pathlib import Path
import sys
from types import SimpleNamespace as NS
from unittest.mock import Mock

import pytest


ROOT = Path(__file__).resolve().parents[1]
EXAMPLE_CONFIG = ROOT / 'resources' / 'config.example.ini'
PROMPTS = EXAMPLE_CONFIG.parent / 'prompts'
FILES = {
    'TEXT_ENTITY_DETECTION': 'text_entity_detection.json',
    'TEXT_ENTITY_CLUSTERING': 'text_entity_clustering.json',
    'LLM_FACE_ASSIGNMENT': 'llm_face_assignment.json',
    'LLM_BATCH_FACE_ASSIGNMENT': 'llm_batch_face_assignment.json',
    'ENTITY_MATCHING': 'entity_matching.json',
}

def test_example_paths_cover_all_engines_in_processing_order():
    config = ConfigParser()
    config.read(EXAMPLE_CONFIG)
    sections = [config[s] for s in config.sections() if s.startswith('ENGINE_')]
    assert [s['METHOD'] for s in sections] == [
        'TEXT_ENTITY_DETECTION', 'TEXT_ENTITY_CLUSTERING', 'FACE_DETECTION_YOLO',
        'LLM_FACE_ASSIGNMENT', 'LLM_BATCH_FACE_ASSIGNMENT', 'ENTITY_MATCHING',
    ]
    for section in sections:
        method = section['METHOD']
        if method not in FILES:
            continue
        path = EXAMPLE_CONFIG.parent / section['PROMPT_TEMPLATE_PATH']
        assert path == PROMPTS / FILES[method]
        content = json.loads(path.read_text(encoding='utf-8'))
        assert set(content) == {'system', 'user'}
        assert all(isinstance(v, str) and v.strip() for v in content.values())
        assert 'JSON_SCHEMA_PATH' not in section
        assert all(section.get(key) for key in ('API_URL', 'API_KEY', 'MODEL_NAME'))


@pytest.fixture
def factory(runtime_mode):
    if runtime_mode == 'client':
        pytest.skip('Prompt loading requires processing extras')
    from people_gator.core.document_parser import engine_factory
    return engine_factory


@pytest.mark.parametrize('method', sorted(FILES))
def test_example_populated_prompts_load_through_shared_engine_factory(method, factory):
    config = ConfigParser()
    config.read(EXAMPLE_CONFIG)
    section, = (config[s] for s in config.sections() if config[s]['METHOD'] == method)
    engine = factory(section, config_path=str(EXAMPLE_CONFIG.parent), device='cpu')
    assert engine.llm_prompter is not None


def test_example_prompt_jinja_inputs():
    from jinja2 import Environment, meta
    expected = {
        'TEXT_ENTITY_DETECTION': {'text'},
        'TEXT_ENTITY_CLUSTERING': {'entities'},
        'LLM_FACE_ASSIGNMENT': {'face_coordinates', 'caption_text', 'context_text'},
        'LLM_BATCH_FACE_ASSIGNMENT': {'faces', 'caption_text', 'context_text'},
        'ENTITY_MATCHING': {'name', 'context', 'entities'},
    }
    environment = Environment()
    for method, name in FILES.items():
        content = json.loads((PROMPTS / name).read_text(encoding='utf-8'))
        actual = set()
        for role in ('system', 'user'):
            actual.update(meta.find_undeclared_variables(environment.parse(content[role])))
        assert expected[method] <= actual


@pytest.mark.parametrize('method', sorted(FILES))
@pytest.mark.parametrize('absolute', [False, True])
def test_ini_selects_alternate_external_files_without_resources(
        method, absolute, factory, tmp_path, monkeypatch):
    from user_scripts.parse_folder import load_config
    from people_gator.engines.llm import LLMPromptConfigurationError

    config_dir = tmp_path / 'deployment'
    external = tmp_path / 'operator-prompts'
    working = tmp_path / 'unrelated-cwd'
    for directory in (config_dir, external, working):
        directory.mkdir()
    monkeypatch.chdir(working)
    config_path = config_dir / 'pipeline.ini'
    for label in ('first', 'replacement'):
        path = external / f'{label}.json'
        path.write_text(json.dumps({'user': label + ': {{ marker }}'}), encoding='utf-8')
        configured = str(path) if absolute else f'../operator-prompts/{path.name}'
        config_path.write_text(
            f'[ENGINE_1]\nMETHOD = {method}\nPROMPT_TEMPLATE_PATH = {configured}\n',
            encoding='utf-8')
        engine = factory(load_config(config_path)['ENGINE_1'],
                         config_path=str(config_dir), device='cpu')
        request = engine.llm_prompter._prepare_request_args({'marker': 'Čapek'})
        assert request['input'][0]['content'][0]['text'] == f'{label}: Čapek'

    # Invalid configured files must never fall back to an example resource.
    for invalid in ('{}', '{broken JSON'):
        path.write_text(invalid, encoding='utf-8')
        with pytest.raises(LLMPromptConfigurationError):
            factory(load_config(config_path)['ENGINE_1'], str(config_dir), 'cpu')
    path.unlink()
    with pytest.raises(LLMPromptConfigurationError):
        factory(load_config(config_path)['ENGINE_1'], str(config_dir), 'cpu')
    assert not (config_dir / 'resources').exists()
    assert not (working / 'resources').exists()


def test_detection_resource_renders_real_input_and_generated_model_schema(factory, caplog):
    from people_gator.engines.text_entity_detection import TextEntityDetectionResult
    config = ConfigParser()
    config.read(EXAMPLE_CONFIG)
    engine = factory(config['ENGINE_TEXT_DETECTION'], str(EXAMPLE_CONFIG.parent), 'cpu')
    request = engine.llm_prompter._prepare_request_args(
        {'text': 'Karel Čapek 😀'}, response_model=TextEntityDetectionResult)
    assert request['input'][1]['content'][0]['text'] == 'Karel Čapek 😀'
    assert request['text']['format']['schema'] == TextEntityDetectionResult.model_json_schema()
    assert not caplog.records


@pytest.mark.parametrize('xml_format', ['alto', 'page'])
def test_parse_folder_config_deployment_retains_engine_order_and_source_mapping(
        xml_format, factory, tmp_path, monkeypatch):
    from people_gator.engines import llm
    from user_scripts import parse_folder as cli

    deployment = tmp_path / 'deployment'
    inputs = tmp_path / 'inputs'
    working = tmp_path / 'unrelated-cwd'
    for directory in (deployment, inputs, working):
        directory.mkdir()
    # A deployed configuration works outside the checkout with arbitrary names.
    (deployment / 'extract.json').write_bytes((PROMPTS / FILES['TEXT_ENTITY_DETECTION']).read_bytes())
    (deployment / 'group.json').write_text(json.dumps({'user': '{{ entities }}'}))
    (deployment / 'link.json').write_bytes((PROMPTS / FILES['ENTITY_MATCHING']).read_bytes())
    sections = [('ENGINE_9', 'TEXT_ENTITY_DETECTION', 'extract.json'),
                ('ENGINE_1', 'TEXT_ENTITY_CLUSTERING', 'group.json'),
                ('ENGINE_0', 'ENTITY_MATCHING', 'link.json')]
    config = ConfigParser()
    config.read_dict({section: {'METHOD': method, 'PROMPT_TEMPLATE_PATH': prompt,
                               'API_URL': 'https://example.invalid/v1',
                               'API_KEY': 'test-only', 'MODEL_NAME': 'mock'}
                      for section, method, prompt in sections})
    config_path = deployment / 'pipeline.ini'
    with config_path.open('w', encoding='utf-8') as stream:
        config.write(stream)
    fixture = ROOT / 'tests' / 'resources' / 'text_chunking' / f'input.{xml_format}.xml'
    for i in range(2):
        (inputs / f'p{i}.xml').write_bytes(fixture.read_bytes())

    extraction = {'entities': [{'name': 'Karel Čapek', 'type': 'being', 'info': 'spisovatel',
                               'mentions': [{'name': 'Čapek', 'context': 'Čapek 😀'}]}]}
    grouping = {'clusters': [{'name': 'Karel Čapek', 'short_description': None,
                              'long_description': None, 'entity_indices': [1, 2]}]}
    create = Mock(side_effect=[NS(status='completed', output_text=json.dumps(payload))
                               for payload in (extraction, extraction, grouping)])
    monkeypatch.setattr(llm, 'OpenAI', Mock(return_value=NS(responses=NS(create=create))))
    real_create_parser = cli.create_document_parser
    seen, parsers = [], []

    def track_parser(*args, **kwargs):
        parser = real_create_parser(*args, **kwargs)
        parsers.append(parser)
        for engine in parser.engines:
            original = engine.process_document

            def process(document, engine=engine, original=original):
                seen.append((engine.config.name, document))
                return original(document)

            monkeypatch.setattr(engine, 'process_document', process)
        return parser

    monkeypatch.setattr(cli, 'create_document_parser', track_parser)
    monkeypatch.chdir(working)
    monkeypatch.setattr(sys, 'argv', ['parse_folder', '--config', str(config_path),
                                     f'--input-{"alto" if xml_format == "alto" else "xml"}-path',
                                     str(inputs), '--device', 'cpu'])
    assert cli.main() == 0
    assert [name for name, _ in seen] == [s[0] for s in sections]
    document = seen[0][1]
    assert all(doc is document for _, doc in seen)
    assert [e.prompt_template_path for e in parsers[0].engines] == [s[2] for s in sections]
    members = document.text_entity_clusters[0].text_entities
    assert members == [p.text_entities[0] for p in document.page_layouts]
    assert [m.source_spans[0].source.page_index for m in members] == [0, 1]
    assert all(m.name == 'Čapek' and m.identity_name is None for m in members)
    assert create.call_count == 3
    assert create.call_args_list[0].kwargs['input'][1]['content'][0]['text'].startswith('Čapek 😀')
    assert 'entity_indices' in create.call_args.kwargs['text']['format']['schema']['$defs']['TextEntityClusterResult']['properties']
