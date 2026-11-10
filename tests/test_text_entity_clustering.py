"""Document-wide fuzzy candidates, typed partitions and protected provenance."""

from configparser import ConfigParser
from copy import deepcopy
import json
from pathlib import Path
from types import SimpleNamespace as NS
from unittest.mock import Mock

import pytest


@pytest.fixture(autouse=True)
def processing_only(runtime_mode):
    if runtime_mode == 'client':
        pytest.skip('Text clustering requires processing extras')


@pytest.fixture
def engine(tmp_path):
    from people_gator.core.document_parser import engine_factory

    def create(**options):
        prompt = tmp_path / 'clustering.json'
        prompt.write_text(json.dumps({'user': '{{ entities }}'}), encoding='utf-8')
        config = ConfigParser()
        config.read_dict({'ENGINE_1': {'METHOD': 'TEXT_ENTITY_CLUSTERING',
            'PROMPT_TEMPLATE_PATH': str(prompt), 'API_URL': 'https://example.invalid',
            'API_KEY': 'private-key', 'MODEL_NAME': 'mock', **options}})
        return engine_factory(config['ENGINE_1'], str(tmp_path), 'cpu')
    return create


def mention(name='Karel Čapek', proposed=None, description='spisovatel', **options):
    from people_gator.core.layout import PeopleGatorTextEntityMention
    return PeopleGatorTextEntityMention(name, f'context: {name}', proposed_name=proposed,
                                        description=description, **options)


def document(*pages):
    from people_gator.core.layout import PeopleGatorDocument
    return PeopleGatorDocument(page_layouts=[NS(id='repeated', text_entities=list(ms), regions=[]) for ms in pages])


def cluster(indices, name='Karel Čapek', **options):
    return {'name': name, 'short_description': 'spisovatel', 'long_description': None,
            'entity_indices': indices, **options}


def membership(doc):
    return [c.text_entities for c in doc.text_entity_clusters]


def assert_partition(doc):
    expected = [id(m) for p in doc.page_layouts for m in p.text_entities]
    actual = [id(m) for c in doc.text_entity_clusters for m in c.text_entities]
    assert sorted(actual) == sorted(expected)
    assert len(actual) == len(set(actual))


@pytest.mark.parametrize('pages', [(), ([],), ([], [])])
def test_empty_documents(engine, pages):
    doc = document(*pages)
    e = engine()
    e.llm_prompter = Mock()
    assert e.process_document(doc) is doc
    assert doc.text_entity_clusters == []
    e.llm_prompter.assert_not_called()


def test_singleton_no_llm_and_compatible_model(engine):
    from people_gator.core.layout import PeopleGatorTextEntityCluster, PeopleGatorIdentity
    m = mention('K. Čapek', 'Karel Čapek')
    doc, e = document([m]), engine()
    e.llm_prompter = Mock()
    e.process_document(doc)
    result = doc.text_entity_clusters[0]
    assert (result.name, result.description, result.identity) == ('Karel Čapek', 'spisovatel', None)
    assert result.text_entities == [m]
    assert result.short_description is None
    assert 'identity_id=None' in repr(result)
    identity = PeopleGatorIdentity('old', 'id')
    legacy = PeopleGatorTextEntityCluster([m], identity, 'old', 'description')
    assert legacy.identity is identity and legacy.description == 'description'
    e.llm_prompter.assert_not_called()


@pytest.mark.parametrize('options', [
    {'CLUSTER_THRESHOLD': x} for x in ['-1', '101', 'nan', 'inf', 'no']
] + [{'NAME_WEIGHT': x} for x in ['-1', 'nan', 'inf', 'bad']]
  + [{'MENTION_WEIGHT': x} for x in ['-1', 'nan', 'inf', 'bad']]
  + [{'NAME_WEIGHT': '0', 'MENTION_WEIGHT': '0'},
     {'NAME_WEIGHT': '1e308', 'MENTION_WEIGHT': '1e308'},
     {'SIMILARITY_AGGREGATION': 'median'}, {'SIMILARITY_AGGREGATION': 'MAX'}])
def test_invalid_options(engine, options):
    with pytest.raises(ValueError):
        engine(**options)


def test_defaults_and_lowercase_options(engine):
    e = engine()
    assert (e.threshold, e.name_weight, e.mention_weight, e.aggregation) == (92, .7, .3, 'max')
    e = engine(cluster_threshold='100', name_weight='1', mention_weight='0', similarity_aggregation='min')
    assert (e.threshold, e.name_weight, e.mention_weight, e.aggregation) == (100, 1, 0, 'min')


@pytest.mark.parametrize('name', ['Čapek Karel', 'Čapek', 'K. Čapek', 'Ｋａｒｅｌ  Čapek', 'Karel\n  Čapek'])
def test_obvious_variants_are_candidates(engine, name):
    e = engine()
    first, second = mention(), mention(name)
    assert e.similarity(first, second) >= 92
    assert e._candidate_groups([first, second]) == [[first, second]]


def test_weighted_alias_scores_aggregation_and_close_nonmatches(engine):
    a, b = mention('Ada', 'Ada Lovelace'), mention('Ada', 'Grace Hopper')
    assert engine().similarity(a, b) < 92
    assert engine(NAME_WEIGHT='0', MENTION_WEIGHT='1').similarity(a, b) == 100
    canonical = mention('unrelated', 'Ada Lovelace')
    assert engine().similarity(a, canonical) == 100
    assert engine(SIMILARITY_AGGREGATION='mean').similarity(a, canonical) < 100
    assert engine(SIMILARITY_AGGREGATION='min').similarity(a, canonical) < 92
    assert engine().similarity(mention('Karel Čapek'), mention('Josef Čapek')) < 92
    assert engine(CLUSTER_THRESHOLD='90').similarity(mention(), mention('Kare1 Čapek')) >= 90
    assert len(engine(CLUSTER_THRESHOLD='90')._candidate_groups([mention(), mention('Kare1 Čapek')])) == 1
    exact = engine(CLUSTER_THRESHOLD='100')
    assert len(exact._candidate_groups([mention(), mention('Kare1 Čapek')])) == 2
    assert engine(NAME_WEIGHT='1e308', MENTION_WEIGHT='0').similarity(a, canonical) == 100


def test_reference_weight_formula_and_threshold_connectivity(engine):
    from rapidfuzz.fuzz import partial_token_sort_ratio
    from people_gator.engines.text_entity_clustering import _normalized_name
    a, b = mention('K. Čapek', 'Karel Čapek'), mention('Kare1 Čapek', 'Čapek Karel')
    for aggregation in ['max', 'mean', 'min']:
        e = engine(SIMILARITY_AGGREGATION=aggregation)
        left, right = [a.proposed_name, a.name], [b.proposed_name, b.name]
        weights = [.7, .3]
        scores = [partial_token_sort_ratio(_normalized_name(x), _normalized_name(y)) *
                  (weights[i] + weights[j]) / 1.4
                  for i, x in enumerate(left) for j, y in enumerate(right)]
        expected = {'max': max(scores), 'min': min(scores), 'mean': sum(scores) / len(scores)}
        assert e.similarity(a, b) == pytest.approx(expected[aggregation])
    e = engine()
    third = mention('Zeus')
    e.similarity = Mock(side_effect=[92, 0, 92])
    assert e._candidate_groups([a, b, third]) == [[a, b, third]]


def test_cross_page_partition_evidence_and_reruns(engine):
    from people_gator.engines.text_entity_clustering import TextEntityClusteringResult
    a, b, c = mention('K. Čapek', 'Karel Čapek'), mention(), mention('Zeus')
    doc, e = document([a], [], [b, c]), engine()
    e.llm_prompter = Mock(return_value=TextEntityClusteringResult.model_validate(
        {'clusters': [cluster([2, 1], long_description='spisovatel a dramatik')]}))
    assert e.process_document(doc) is doc
    assert membership(doc) == [[a, b], [c]]
    result = doc.text_entity_clusters[0]
    assert result.identity is None and result.short_description == 'spisovatel'
    assert result.description == 'spisovatel a dramatik'
    evidence = json.loads(e.llm_prompter.call_args.args[0]['entities'])
    assert evidence == [dict(index=i, name=m.proposed_name or m.name, aliases=[m.name],
                            description=m.description, context=m.text) for i, m in enumerate([a, b], 1)]
    assert e.llm_prompter.call_args.kwargs['response_model'] is TextEntityClusteringResult
    previous = doc.text_entity_clusters[:]
    e.process_document(doc)
    assert doc.text_entity_clusters == previous
    assert e.llm_prompter.call_count == 1
    assert a.page_identity is b.page_identity is c.page_identity is None
    assert_partition(doc)
    new = mention('Karel')
    doc.page_layouts[0].text_entities.append(new)
    e.process_document(doc)
    assert membership(doc) == [[a, b], [new], [c]]
    assert doc.text_entity_clusters[0] is result
    assert_partition(doc)


def test_same_name_homonyms_split_with_context_and_stable_order(engine):
    a, b, c = [mention(description=d) for d in ['author', 'sailor', 'author']]
    doc, e = document([a, b], [c]), engine()
    e.llm_prompter = Mock(return_value={'clusters': [cluster([2]), cluster([3, 1])]})
    e.process_document(doc)
    assert membership(doc) == [[a, c], [b]]
    assert [r['description'] for r in json.loads(e.llm_prompter.call_args.args[0]['entities'])] == ['author', 'sailor', 'author']
    assert_partition(doc)


@pytest.mark.parametrize('payload', [
    {}, [], 'bad', {'clusters': None}, {'clusters': []},
    {'clusters': [cluster([]), cluster([1, 2])]},
    {'clusters': [cluster([1])]}, {'clusters': [cluster([1, 1])]},
    {'clusters': [cluster([0, 1])]}, {'clusters': [cluster([1, 3])]},
    {'clusters': [cluster([1, '2'])]}, {'clusters': [cluster([1, 2.0])]},
    {'clusters': [cluster([True, 2])]}, {'clusters': [cluster([1, 2]), cluster([2])]},
    {'clusters': [cluster([1, 2], name='invented person')]},
    {'clusters': [cluster([1, 2], name=' ')]},
    {'clusters': [cluster([1, 2], short_description=' ')]},
    {'clusters': [cluster([1, 2], long_description='bad\x00text')]},
    {'clusters': [cluster([1, 2], aliases=['invented'])]},
    {'clusters': [cluster([1, 2])], 'extra': 'field'},
])
def test_invalid_partitions_fallback_atomically_to_singletons(engine, payload, caplog):
    a, b = mention(), mention()
    doc, e = document([a], [b]), engine()
    e.llm_prompter = Mock(return_value=payload)
    e.process_document(doc)
    assert membership(doc) == [[a], [b]]
    assert all(c.identity is None and c.description == 'spisovatel' for c in doc.text_entity_clusters)
    assert 'singletons' in caplog.text
    assert 'Karel' not in caplog.text
    assert_partition(doc)


def test_name_must_be_supported_by_its_own_members(engine):
    a, b = mention(), mention('K. Čapek')
    doc, e = document([a, b]), engine()
    e.llm_prompter = Mock(return_value={'clusters': [cluster([1], name=b.name), cluster([2], name=a.name)]})
    e.process_document(doc)
    assert [c.name for c in doc.text_entity_clusters] == [a.name, b.name]


@pytest.mark.parametrize('failure', [None, RuntimeError('private OCR'), OSError('private key')])
def test_transport_failure_no_partial_commit(engine, failure, caplog):
    from people_gator.core.layout import PeopleGatorTextEntityCluster
    original = mention('Manual')
    a, b, c, d = mention(), mention(), mention('Ada Lovelace'), mention('Ada Lovelace')
    doc, e = document([original, a, b], [c, d]), engine()
    protected = PeopleGatorTextEntityCluster([original], name='Manual')
    doc.text_entity_clusters = [protected]
    original_list = doc.text_entity_clusters
    before = [m.__dict__.copy() for m in [original, a, b, c, d]]
    e.llm_prompter = Mock(side_effect=[{'clusters': [cluster([1, 2])]}, failure])
    with pytest.raises(RuntimeError, match='Text clustering failed'):
        e.process_document(doc)
    assert e.llm_prompter.call_count == 2
    assert doc.text_entity_clusters is original_list
    assert doc.text_entity_clusters == [protected]
    assert [m.__dict__ for m in [original, a, b, c, d]] == before
    assert 'private' not in caplog.text


def test_linked_manual_and_existing_cluster_protection(engine):
    from people_gator.core.layout import PeopleGatorIdentity, PeopleGatorPageIdentity, PeopleGatorTextEntityCluster
    a, b, c, d = [mention() for _ in range(4)]
    ids = [PeopleGatorIdentity('manual', value) for value in ['id-one', 'id-two', None]]
    for m, identity in zip([a, b, c], ids):
        m.page_identity = PeopleGatorPageIdentity('tag', 'mods', identity)
    doc, e = document([a, b], [c, d]), engine()
    old = PeopleGatorTextEntityCluster([d], name='manual cluster', description='protected')
    doc.text_entity_clusters = [old]
    before = [m.page_identity for m in [a, b, c, d]]
    e.llm_prompter = Mock()
    e.process_document(doc)
    assert membership(doc) == [[a], [b], [c], [d]]
    assert [cluster.identity for cluster in doc.text_entity_clusters[:3]] == ids
    assert doc.text_entity_clusters[-1] is old
    assert [m.page_identity for m in [a, b, c, d]] == before
    e.process_document(doc)
    e.llm_prompter.assert_not_called()
    assert_partition(doc)


@pytest.mark.parametrize('case', ['duplicate', 'foreign', 'empty', 'overlap', 'conflict', 'cluster-conflict', 'repeated-input'])
def test_ambiguous_existing_clusters_rejected_without_mutation(engine, case):
    from people_gator.core.layout import PeopleGatorIdentity, PeopleGatorPageIdentity, PeopleGatorTextEntityCluster
    a, b = mention(), mention()
    doc, e = document([a, b]), engine()
    members = {'duplicate': [a, a], 'foreign': [mention()], 'empty': []}.get(case, [a, b])
    old = PeopleGatorTextEntityCluster(members)
    doc.text_entity_clusters = [old]
    if case == 'overlap':
        doc.text_entity_clusters.append(PeopleGatorTextEntityCluster([a]))
    if case in ['conflict', 'cluster-conflict']:
        a.page_identity = PeopleGatorPageIdentity('t', 'm', PeopleGatorIdentity('manual', 'one'))
        if case == 'conflict':
            b.page_identity = PeopleGatorPageIdentity('t', 'm', PeopleGatorIdentity('manual', 'two'))
        else:
            old.identity = PeopleGatorIdentity('manual', 'two')
    if case == 'repeated-input':
        doc.page_layouts[0].text_entities.append(a)
    previous = doc.text_entity_clusters
    e.llm_prompter = Mock()
    with pytest.raises(ValueError):
        e.process_document(doc)
    assert doc.text_entity_clusters is previous
    e.llm_prompter.assert_not_called()


def test_multiline_unicode_provenance_ocr_faces_images_preserved(engine):
    from people_gator.text import SourceLine, SourceSpan
    a, b = mention('😀 Karel\nČapek', 'Karel Čapek'), mention('Kare1 Čapek', 'Karel Čapek')
    a.source_spans = tuple(SourceSpan(SourceLine('p', 'r', 'l', 0, 0, i), 0, 5) for i in range(2))
    b.source_spans = (SourceSpan(SourceLine('p', 'r', 'l', 1, 0, 0), 0, 11),)
    line = NS(id='l', transcription=b.name)
    b.line, b.span = line, (0, 11)
    doc, e = document([a], [b]), engine()
    face, image = object(), object()
    doc.page_layouts[0].regions.append(face)
    doc.page_images['p'] = image
    before = [m.__dict__.copy() for m in [a, b]]
    e.llm_prompter = Mock(return_value={'clusters': [cluster([1, 2])]})
    e.process_document(doc)
    assert membership(doc) == [[a, b]]
    for m, fields in zip([a, b], before):
        for key, value in fields.items():
            assert getattr(m, key) is value
    assert doc.page_layouts[0].regions == [face]
    assert doc.page_images['p'] is image
    assert line.transcription == 'Kare1 Čapek'


def test_typed_schema_external_template_and_warnings(engine, caplog):
    from people_gator.engines.text_entity_clustering import TextEntityClusteringResult
    e = engine()
    e.llm_prompter.prompt_template_user = __import__('jinja2').Template('{{ typo }}')
    e.llm_prompter._template_variables = {'typo'}
    request = e.llm_prompter._prepare_request_args({'entities': 'private OCR'}, response_model=TextEntityClusteringResult)
    schema = request['text']['format']['schema']
    assert schema == TextEntityClusteringResult.model_json_schema()
    assert schema['required'] == ['clusters']
    model = schema['$defs']['TextEntityClusterResult']
    assert set(model['required']) == {'name', 'short_description', 'long_description', 'entity_indices'}
    assert model['properties']['entity_indices']['items']['type'] == 'integer'
    assert e.json_schema is None
    assert 'typo is missing' in caplog.text and 'entities is unused' in caplog.text
    assert 'private OCR' not in caplog.text


@pytest.mark.parametrize('format', ['alto', 'page'])
def test_detection_then_clustering_parser_xml(format, engine, tmp_path, monkeypatch):
    from people_gator.core.document_parser import DocumentParser
    from people_gator.core.layout import PeopleGatorDocument, PeopleGatorFaceRegionLayout
    from people_gator.engines.llm import LLMPrompter
    from people_gator.engines.text_entity_detection import TextEntityDetectionResult
    from people_gator.engines.text_entity_clustering import TextEntityClusteringResult
    fixtures = Path(__file__).parent / 'resources' / 'text_chunking'
    for i in range(2):
        (tmp_path / f'p{i}.xml').write_text((fixtures / f'input.{format}.xml').read_text())
    doc = PeopleGatorDocument(**{'alto_xmls_dir' if format == 'alto' else 'page_xmls_dir': str(tmp_path)})
    face = PeopleGatorFaceRegionLayout(id='face', polygon=[[0, 0], [1, 1], [1, 0]], category='face', face_metadata=None, source_region=None)
    doc.page_layouts[0].regions.append(face)
    original_pages = doc.page_layouts[:]
    original_regions = [r for p in doc.page_layouts for r in p.regions]
    lines = [l for r in original_regions for l in r.lines]
    before = deepcopy([(l.id, l.transcription) for l in lines])
    config = ConfigParser()
    config.read_dict({
        'ENGINE_9': {'METHOD': 'TEXT_ENTITY_DETECTION', 'PROMPT_TEMPLATE_PATH': str(Path(__file__).parent / 'resources' / 'text_entity_detection' / 'prompt.json')},
        'ENGINE_1': {'METHOD': 'TEXT_ENTITY_CLUSTERING', 'PROMPT_TEMPLATE_PATH': engine().prompt_template_path}})
    seen = []
    def predict(self, data, response_model):
        seen.append(response_model)
        if response_model is TextEntityDetectionResult:
            return {'entities': [{'name': 'Karel Čapek', 'type': 'being', 'info': 'spisovatel',
                'mentions': [{'name': 'Čapek', 'context': 'Čapek 😀'}]}]}
        return {'clusters': [cluster([1, 2])]}
    monkeypatch.setattr(LLMPrompter, '__call__', predict)
    parser = DocumentParser(config, 'cpu', str(tmp_path))
    # Every real engine receives the original instance in configured order.
    for e in parser.engines:
        e.process_document = Mock(wraps=e.process_document)
    assert parser.process_document(doc) is doc
    assert [e.config.name for e in parser.engines] == ['ENGINE_9', 'ENGINE_1']
    assert all(e.process_document.call_args.args[0] is doc for e in parser.engines)
    assert seen == [TextEntityDetectionResult, TextEntityDetectionResult, TextEntityClusteringResult]
    assert len(doc.text_entity_clusters) == 1
    assert_partition(doc)
    members = doc.text_entity_clusters[0].text_entities
    assert members == [p.text_entities[0] for p in doc.page_layouts]
    assert [m.source_spans[0].source.page_index for m in members] == [0, 1]
    assert doc.page_layouts == original_pages
    assert [r for p in doc.page_layouts for r in p.regions] == original_regions
    assert [(l.id, l.transcription) for l in lines] == before
    assert doc.page_layouts[0].faces == [face]
    assert doc.page_images == {}


def test_real_responses_typed_retry_invalid_partition_and_service_failure(engine, monkeypatch):
    from people_gator.engines import llm
    e = engine()
    responses = Mock(side_effect=[NS(output_text='bad JSON'), NS(output_text=json.dumps({'clusters': [cluster([1, 2])]}))])
    monkeypatch.setattr(llm, 'OpenAI', Mock(return_value=NS(responses=NS(create=responses))))
    a, b = mention(), mention()
    doc = document([a, b])
    e.process_document(doc)
    assert responses.call_count == 2 and membership(doc) == [[a, b]]
    responses.side_effect = None
    responses.return_value = NS(output_text=json.dumps({'clusters': [cluster([1, 1])]}))
    doc = document([a, b])
    e.process_document(doc)
    assert membership(doc) == [[a], [b]]
    responses.return_value = NS(output_text='{"clusters": [null]}')
    doc = document([a, b])
    e.process_document(doc)
    assert membership(doc) == [[a], [b]]
    responses.return_value = NS(output_text='bad JSON')
    doc = document([a, b])
    e.process_document(doc)
    assert membership(doc) == [[a], [b]]
    for failure in [OSError('private OCR'),
                    NS(status='incomplete', incomplete_details=NS(reason='max_output_tokens'))]:
        responses.side_effect = failure if isinstance(failure, Exception) else None
        responses.return_value = failure
        doc = document([a, b])
        original = doc.text_entity_clusters
        with pytest.raises(RuntimeError):
            e.process_document(doc)
        assert doc.text_entity_clusters is original


def test_prior_invalid_content_cannot_mask_later_transport_failure(engine, monkeypatch):
    from people_gator.engines import llm
    e = engine()
    responses = Mock(side_effect=[NS(output_text='{"clusters": [null]}'),
                                  OSError('private transport'), OSError('private transport')])
    monkeypatch.setattr(llm, 'OpenAI', Mock(return_value=NS(responses=NS(create=responses))))
    doc = document([mention(), mention()])
    before = doc.text_entity_clusters
    with pytest.raises(RuntimeError):
        e.process_document(doc)
    assert doc.text_entity_clusters is before


def test_typed_result_is_revalidated_and_logs_only_counts(engine, caplog):
    from people_gator.engines.text_entity_clustering import TextEntityClusteringResult
    typed = TextEntityClusteringResult.model_validate({'clusters': [cluster([1, 2])]})
    typed.clusters[0].entity_indices = [True, 2]
    e = engine()
    e.llm_prompter = Mock(return_value=typed)
    doc = document([mention(), mention()])
    caplog.set_level('DEBUG')
    e.process_document(doc)
    assert len(doc.text_entity_clusters) == 2
    assert 'singletons' in caplog.text
    assert not any(value in caplog.text for value in ['Karel', 'Čapek', 'spisovatel', 'context:', 'private-key'])


def test_generated_schema_takes_precedence_over_optional_file(engine, tmp_path):
    from people_gator.engines.text_entity_clustering import TextEntityClusteringResult
    schema_path = tmp_path / 'schema.json'
    schema_path.write_text('{"type": "object", "properties": {"unrelated": {"type": "string"}}}')
    e = engine(JSON_SCHEMA_PATH=str(schema_path))
    request = e.llm_prompter._prepare_request_args({'entities': '[]'}, response_model=TextEntityClusteringResult)
    assert request['text']['format']['schema'] == TextEntityClusteringResult.model_json_schema()
    assert request['text']['format']['schema'] != e.json_schema


@pytest.mark.parametrize('key', ['cluster_threshold', 'name_weight', 'mention_weight'])
def test_boolean_numeric_options_rejected(key):
    from people_gator.engines.text_entity_clustering import _number
    with pytest.raises(ValueError, match=key.upper()):
        _number({key: True}, key, 0)
