"""Mocked text extraction, evidence matching, atomicity and parser regressions."""

from configparser import ConfigParser
from copy import deepcopy
from pathlib import Path
from types import SimpleNamespace as NS
from unittest.mock import Mock

import pytest


@pytest.fixture(autouse=True)
def processing_only(runtime_mode):
    if runtime_mode == 'client':
        pytest.skip('Text detection requires processing extras')


def engine(**options):
    from people_gator.core.document_parser import engine_factory
    config = ConfigParser()
    config.read_dict({'ENGINE_1': {'METHOD': 'TEXT_ENTITY_DETECTION',
        'PROMPT_TEMPLATE_PATH': str(Path(__file__).parent / 'resources' / 'text_entity_detection' / 'prompt.json'),
        **options}})
    return engine_factory(config['ENGINE_1'], '.', 'cpu')


def document(*texts):
    from people_gator.core.layout import PeopleGatorDocument
    doc = PeopleGatorDocument()
    doc.page_layouts = [NS(id='p', reading_order=None, text_entities=[],
                          regions=[NS(id='r', category='text', lines=[NS(id='l', transcription=t) for t in texts])])]
    return doc


def entity(name='Karel', context='Karel came', proposed='Karel Čapek'):
    return {'name': proposed, 'type': 'being', 'info': 'spisovatel',
            'mentions': [{'name': name, 'context': context}]}


def test_single_line_metadata_legacy_and_idempotence():
    from people_gator.core.layout import PeopleGatorTextEntityMention, PeopleGatorPageIdentity, PeopleGatorIdentity
    doc = document('Karel came')
    detector = engine()
    detector.llm_prompter = Mock(return_value={'entities': [entity()]})
    assert detector.process_document(doc) is doc
    mention = doc.page_layouts[0].text_entities[0]
    assert (mention.name, mention.text, mention.span) == ('Karel', 'Karel came', (0, 5))
    assert mention.line is doc.page_layouts[0].regions[0].lines[0]
    assert (mention.proposed_name, mention.description, mention.identity_name) == ('Karel Čapek', 'spisovatel', None)
    assert mention.source_spans[0].source.line_id == 'l'
    repr(mention)
    detector.process_document(doc)
    assert len(doc.page_layouts[0].text_entities) == 1
    doc.build_text_entity_clusters()
    assert doc.text_entity_clusters == []
    identity = PeopleGatorIdentity('Manual', 'id')
    manual = PeopleGatorTextEntityMention('Karel', 'manual', mention.line, (0, 5),
                                         PeopleGatorPageIdentity('t', 'm', identity))
    doc.page_layouts[0].text_entities[:] = [manual]
    detector.process_document(doc)
    assert doc.page_layouts[0].text_entities == [manual]
    assert manual.identity_name == 'Manual'


@pytest.mark.parametrize('text,name,context,expected', [
    ('Karel came; Karel left', 'Karel', 'Karel left', (12, 17)),
    ('Karel came; Karel left', 'Karel', 'Karel', None),
    ('Karel Karel', 'Karel', 'Karel Karel', None),
    ('Čapek 😀 came', 'Čapek 😀', 'Čapek 😀 came', (0, 7)),
    ('Kar-\nel Čapek', 'Karel Čapek', 'Karel Čapek', (0, 13)),
    ('Karel   Čapek', 'karel čapek', 'karel čapek', (0, 13)),
    ('Kare1 Čapek came', 'Karel Čapek', 'Karel Čapek came', (0, 11)),
    ('Kare1 Čapek; KareI Čapek', 'Karel Čapek', 'Karel Čapek', None),
    ('Karel came', 'Zeus', 'Zeus came', None),
])
def test_matching(text, name, context, expected):
    from people_gator.engines.text_entity_detection import match_mention
    result = match_mention(text, name, context)
    assert (result[:2] if result else None) == expected


def test_multiline_and_original_offsets():
    doc = document('😀 Karel', 'Čapek came')
    detector = engine()
    detector.llm_prompter = Mock(return_value=[entity('Karel\nČapek', '😀 Karel\nČapek came')])
    detector.process_document(doc)
    mention = doc.page_layouts[0].text_entities[0]
    assert mention.name == 'Karel\nČapek'
    assert mention.line is mention.span is None
    assert [(s.source.line_index, s.start, s.end) for s in mention.source_spans] == [(0, 2, 7), (1, 0, 5)]
    assert mention.identity_name is None
    repr(mention)


def test_overlap_distinct_positions_and_repeated_runs():
    doc = document('Karel came Karel left')
    detector = engine(CHUNKING_MAX_CHARS='17', CHUNKING_OVERLAP_CHARS='11')
    def predict(data, **kwargs):
        return {'entities': [entity('Karel', context) for context in ('Karel came', 'Karel left') if context in data['text']]}
    detector.llm_prompter = Mock(side_effect=predict)
    detector.process_document(doc)
    detector.process_document(doc)
    mentions = doc.page_layouts[0].text_entities
    assert [m.span for m in mentions] == [(0, 5), (11, 16)]


@pytest.mark.parametrize('options', [
    {'MENTION_MATCH_SCORE_CUTOFF': x} for x in ('no', 'nan', 'inf', '-1', '101')
] + [{'CHUNKING_MAX_CHARS': '0'}, {'CHUNKING_BAD': '1'}, {'CHUNKING_METHOD': 'BAD'}])
def test_invalid_config(options):
    with pytest.raises(ValueError):
        engine(**options)


def test_config_defaults_lowercase_and_isolation():
    detector = engine(chunking_max_chars='17', model_name='mock')
    assert (detector.chunker.max_chars, detector.chunker.overlap_chars) == (17, 0)
    assert detector.model_name == 'mock'
    assert engine().match_cutoff == 80


@pytest.mark.parametrize('response', [[], {'entities': []}, {'entities': [None, {'type': 'place'}]}])
def test_empty_and_invalid_candidates(response):
    doc = document('Karel came')
    detector = engine()
    detector.llm_prompter = Mock(return_value=response)
    detector.process_document(doc)
    assert not doc.page_layouts[0].text_entities


def test_partial_invalid_and_safe_logs(caplog):
    doc = document('Karel came')
    detector = engine(API_KEY='secret')
    caplog.set_level('DEBUG')
    detector.llm_prompter = Mock(return_value={'entities': [None, entity(), {**entity(), 'type': 'place'},
        {**entity(), 'mentions': [None, {'name': 'Invented', 'context': 'Invented'}, {'name': 'Karel', 'context': 'Karel came'}]}]})
    detector.process_document(doc)
    assert len(doc.page_layouts[0].text_entities) == 1
    assert all(value not in caplog.text for value in ('Karel', 'secret', 'Invented'))


@pytest.mark.parametrize('failure', [None, {}, 'unparseable', RuntimeError('private payload')])
def test_failure_atomicity(failure, caplog):
    doc = document('Karel came', 'Karel came')
    detector = engine(CHUNKING_MAX_CHARS='10')
    detector.llm_prompter = Mock(side_effect=[{'entities': [entity()]}, failure])
    with pytest.raises(RuntimeError, match='chunk 1'):
        detector.process_document(doc)
    assert not doc.page_layouts[0].text_entities
    assert 'private payload' not in caplog.text


def test_no_source_no_request():
    detector = engine()
    detector.llm_prompter = Mock()
    from people_gator.core.layout import PeopleGatorDocument
    for doc in (PeopleGatorDocument(), document(), document('', None, '  ')):
        detector.process_document(doc)
    detector.llm_prompter.assert_not_called()


@pytest.mark.parametrize('format', ['alto', 'page'])
def test_document_parser_xml(format, tmp_path, monkeypatch):
    from people_gator.core.document_parser import DocumentParser
    from people_gator.core.layout import PeopleGatorDocument, PeopleGatorFaceRegionLayout
    from people_gator.engines.llm import LLMPrompter
    fixtures = Path(__file__).parent / 'resources' / 'text_chunking'
    for index in range(2):
        (tmp_path / f'p{index}.xml').write_text((fixtures / f'input.{format}.xml').read_text())
    doc = PeopleGatorDocument(**{'alto_xmls_dir' if format == 'alto' else 'page_xmls_dir': str(tmp_path)})
    face = PeopleGatorFaceRegionLayout(id='face', polygon=[[0, 0], [1, 1], [1, 0]], category='face', face_metadata=None, source_region=None)
    doc.page_layouts[0].regions.append(face)
    before = deepcopy([[(l.id, l.transcription) for r in p.regions for l in r.lines] for p in doc.page_layouts])
    config = ConfigParser()
    settings = {'METHOD': 'TEXT_ENTITY_DETECTION', 'PROMPT_TEMPLATE_PATH':
                str(Path(__file__).parent / 'resources' / 'text_entity_detection' / 'prompt.json')}
    config.read_dict({'ENGINE_2': settings, 'ENGINE_1': settings})
    monkeypatch.setattr(LLMPrompter, '__call__', Mock(return_value={'entities': [entity('Čapek', 'Čapek 😀')]}))
    parser = DocumentParser(config, 'cpu', str(tmp_path))
    assert [e.config.name for e in parser.engines] == ['ENGINE_2', 'ENGINE_1']
    assert parser.process_document(doc) is doc
    for index, page in enumerate(doc.page_layouts):
        assert len(page.text_entities) == 1
        assert page.text_entities[0].source_spans[0].source.page_index == index
    assert doc.page_layouts[0].faces == [face]
    assert before == [[(l.id, l.transcription) for r in p.regions for l in r.lines] for p in doc.page_layouts]
    assert doc.page_images == {}


def test_responses_retry_empty_and_partial(monkeypatch):
    import people_gator.engines.llm as llm
    detector = engine(API_URL='https://example.invalid', API_KEY='secret', MODEL_NAME='mock')
    responses = Mock(side_effect=[NS(output_text='bad json'), NS(output_text='{}'),
                                 NS(output_text='{"entities": []}')])
    monkeypatch.setattr(llm, 'OpenAI', Mock(return_value=NS(responses=NS(create=responses))))
    doc = document('Karel came')
    detector.process_document(doc)
    assert responses.call_count == 3
    assert not doc.page_layouts[0].text_entities
    responses.side_effect = None
    responses.return_value = NS(output_text='```json\n{"entities": [null]}\n```')
    detector.process_document(doc)
    assert responses.call_count == 4
    responses.return_value = NS(output_text='{}')
    with pytest.raises(RuntimeError):
        detector.process_document(doc)
    responses.side_effect = OSError('private')
    with pytest.raises(RuntimeError):
        detector.process_document(doc)


def test_configured_template_and_model_schema(tmp_path):
    import json
    from people_gator.engines.text_entity_detection import TextEntityDetectionResult

    (tmp_path / 'prompt.json').write_text(json.dumps({'system': 'custom', 'user': '{{ text }}'}))
    # Shared LLM configuration still supports this path, but response_model takes
    # precedence as in the existing face/entity engines.
    schema = {'type': 'object', 'properties': {'unrelated': {'type': 'string'}}}
    (tmp_path / 'schema.json').write_text(json.dumps(schema))
    detector = engine(PROMPT_TEMPLATE_PATH=str(tmp_path / 'prompt.json'), JSON_SCHEMA_PATH=str(tmp_path / 'schema.json'))
    request = detector.llm_prompter._prepare_request_args({'text': 'OCR'}, response_model=TextEntityDetectionResult)
    assert request['input'][0]['content'][0]['text'] == 'custom'
    assert request['input'][1]['content'][0]['text'] == 'OCR'
    assert request['text']['format']['schema'] == TextEntityDetectionResult.model_json_schema()
    assert request['text']['format']['schema'] != schema
    assert request['text']['format']['name'] == 'TextEntityDetectionResult'


def test_no_built_in_prompt_or_schema():
    detector = engine()
    assert detector.prompt_template_user == '{{ text }}'
    assert detector.json_schema is None
    assert detector.llm_prompter.prompt_template_user.render(text='OCR') == 'OCR'
    assert detector.llm_prompter.json_schema is None


def test_pydantic_models_filter_candidates_without_losing_valid_mentions():
    from pydantic import BaseModel
    from people_gator.engines.text_entity_detection import (
        TextEntityDetectionResult, TextEntityResult, TextEntityMentionResult,
    )
    assert all(issubclass(model, BaseModel) for model in (
        TextEntityDetectionResult, TextEntityResult, TextEntityMentionResult))
    good = entity(' Karel\nČapek ', ' Karel\nČapek came ')
    raw = {'entities': [None, {**entity(), 'type': 'place'}, {**entity(), 'name': 3},
                        {**entity(), 'name': '  '},
                        {**good, 'mentions': [None, {'name': 3, 'context': 'bad'},
                                             {'name': 'Karel', 'context': '  '}, *good['mentions']]}]}
    before = deepcopy(raw)
    result = TextEntityDetectionResult.model_validate(raw)
    assert raw == before
    assert result._rejected_candidates == 7
    assert len(result.entities) == 1
    assert isinstance(result.entities[0], TextEntityResult)
    mention = result.entities[0].mentions[0]
    assert isinstance(mention, TextEntityMentionResult)
    assert mention.name == good['mentions'][0]['name']
    assert mention.context == good['mentions'][0]['context']
    assert result.model_dump() == {'entities': [good]}
    assert TextEntityDetectionResult.model_validate(result) is result
    legacy = TextEntityDetectionResult.model_validate([entity()])
    assert legacy.entities[0].type == 'being'
    missing_info = entity()
    del missing_info['info']
    assert TextEntityDetectionResult.model_validate([missing_info]).entities[0].info is None


@pytest.mark.parametrize('payload', [None, {}, {'entities': None}, {'entities': 'invalid'}, {'entities': [], 'extra': True}])
def test_pydantic_response_rejects_invalid_envelopes(payload):
    from pydantic import ValidationError
    from people_gator.engines.text_entity_detection import TextEntityDetectionResult
    with pytest.raises(ValidationError):
        TextEntityDetectionResult.model_validate(payload)


def test_model_schema_has_typed_required_fields_only():
    from people_gator.engines.text_entity_detection import TextEntityDetectionResult
    schema = TextEntityDetectionResult.model_json_schema()
    assert schema['required'] == ['entities']
    assert schema['additionalProperties'] is False
    assert schema['properties']['entities']['items'] == {'$ref': '#/$defs/TextEntityResult'}
    candidate = schema['$defs']['TextEntityResult']
    assert set(candidate['required']) == {'name', 'type', 'info', 'mentions'}
    assert candidate['properties']['type']['const'] == 'being'
    assert candidate['properties']['mentions']['items'] == {'$ref': '#/$defs/TextEntityMentionResult'}
    assert set(schema['$defs']['TextEntityMentionResult']['required']) == {'name', 'context'}
    assert '_rejected' not in str(schema)


def test_engine_passes_response_class_and_consumes_typed_result():
    from people_gator.engines.text_entity_detection import TextEntityDetectionResult
    detector = engine()
    typed = TextEntityDetectionResult.model_validate({'entities': [entity()]})
    detector.llm_prompter = Mock(return_value=typed)
    doc = document('Karel came')
    detector.process_document(doc)
    assert detector.llm_prompter.call_args.args[0] == {'text': 'Karel came'}
    assert detector.llm_prompter.call_args.kwargs['response_model'] is TextEntityDetectionResult
    assert doc.page_layouts[0].text_entities[0].proposed_name == 'Karel Čapek'


def test_conflicting_metadata_first_wins_and_long_line_offsets():
    doc = document('xxxxx Zeus came and Sherlock left')
    detector = engine(CHUNKING_MAX_CHARS='15', CHUNKING_OVERLAP_CHARS='12')
    def predict(data, **kwargs):
        result = []
        for name, context in [('Zeus', 'Zeus came'), ('Sherlock', 'Sherlock left')]:
            if context in data['text']:
                result.extend([entity(name, context, name), entity(name, context, 'conflict')])
        return result
    detector.llm_prompter = Mock(side_effect=predict)
    detector.process_document(doc)
    mentions = doc.page_layouts[0].text_entities
    assert [(m.span, m.proposed_name) for m in mentions] == [((6, 10), 'Zeus'), ((20, 28), 'Sherlock')]


def test_multiline_identity_helpers():
    from people_gator.core.layout import PeopleGatorTextEntityMention, PeopleGatorTextEntityCluster, PeopleGatorIdentity
    doc = document()
    mention = PeopleGatorTextEntityMention('name', 'context')
    identity = PeopleGatorIdentity('Resolved later', 'id')
    doc.page_layouts[0].text_entities.append(mention)
    doc.text_entity_clusters = [PeopleGatorTextEntityCluster([mention], identity)]
    doc.distribute_text_entity_identities()
    assert mention.identity_name == 'Resolved later'
    doc.build_text_entity_clusters(drop_mentions_identities=True)
    assert mention.identity_name is None
    assert doc.text_entity_clusters[0].identity is identity
