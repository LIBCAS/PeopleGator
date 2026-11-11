"""Document-wide app linking with source evidence and failure-safe mutations."""

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
        pytest.skip('Entity linking requires processing extras')


@pytest.fixture
def engine(tmp_path):
    from people_gator.core.document_parser import engine_factory
    prompt = tmp_path / 'linking.json'
    prompt.write_text(json.dumps({'system': 'Use only supplied evidence. Never infer identity from a name or score.',
                                  'user': '{{ name }} {{ context }} {{ entities }}'}))
    config = ConfigParser()
    config.read_dict({'ENGINE_1': {'METHOD': 'ENTITY_MATCHING', 'PROMPT_TEMPLATE_PATH': str(prompt),
        'API_URL': 'https://example.invalid', 'API_KEY': 'private-credential', 'MODEL_NAME': 'mock'}})
    db = Mock()
    db.search_entities.return_value = {'items': []}
    db.create_entity.return_value = {'entity_id': 'created'}
    instance = engine_factory(config['ENGINE_1'], str(tmp_path), 'cpu', db)
    instance.llm_prompter = Mock(return_value=decision('create'))
    return instance


def decision(action='unresolved', index=None, name='Karel Čapek', evidence=(), person=True):
    from people_gator.engines.entity_matching import EntityMatchingResult
    return EntityMatchingResult(action=action, source_is_person=person, item_id=index,
        name=name if action != 'unresolved' else None, reason='Supplied evidence supports this outcome.',
        evidence=list(evidence))


def comparison(index=0, source='Czech writer', candidate='Czech writer'):
    return {'item_id': index, 'source_quote': source, 'candidate_quote': candidate}


def candidate(entity_id='existing', name='Karel Čapek', description='Czech writer', **options):
    return {'entity_id': entity_id, 'name': name, 'entity_type': 'person',
            'aliases': ['K. Čapek'], 'description': description, 'short_description': '', **options}


def identity(name='Karel Čapek', entity_id=None):
    from people_gator.core.layout import PeopleGatorIdentity
    return PeopleGatorIdentity(name, entity_id, {'wikidata': 'Q155855'})


def page_identity(person=None, suffix='old'):
    from people_gator.core.layout import PeopleGatorPageIdentity
    return PeopleGatorPageIdentity('person_' + suffix, 'MODS_PERSON_' + suffix, person or identity(),
                                   used_ai_models={'manual': 'review'}, confidence=.95)


def document(fmt='alto', names=('Karel Čapek', 'K. Čapek'), linked=None):
    from people_gator.core.layout import PeopleGatorDocument, PeopleGatorTextEntityMention, PeopleGatorTextEntityCluster, PeopleGatorPageLayout
    from people_gator.text import LineAwareTextChunker
    root = Path(__file__).parent / 'resources' / 'text_chunking' / ('input.' + fmt + '.xml')
    pages = []
    for i in range(2):
        page = PeopleGatorPageLayout()
        getattr(page, 'from_altoxml' if fmt == 'alto' else 'from_pagexml')(str(root))
        page.id = 'p' + str(i)
        pages.append(page)
    doc = PeopleGatorDocument(page_layouts=pages)
    for page, name in zip(doc.page_layouts, names):
        first = LineAwareTextChunker(max_chars=10000).chunk_document(
            PeopleGatorDocument(page_layouts=[page])).chunks[0].mappings[0].source
        page.regions[first.region_index].lines[first.line_index].transcription = name + ', Czech writer.'
    chunks = LineAwareTextChunker(max_chars=10000).chunk_document(doc).chunks
    members = []
    for page, chunk, name in zip(doc.page_layouts, chunks, names):
        first = next(m for m in chunk.mappings if m.source is not None)
        spans = chunk.source_spans(first.start, first.start + len(name))
        m = PeopleGatorTextEntityMention(name, chunk.text[first.start:first.end],
                source_spans=spans, proposed_name='Karel Čapek', description='Czech writer')
        page.text_entities.append(m)
        members.append(m)
    cluster = PeopleGatorTextEntityCluster(members, linked, name='Karel Čapek',
                                         description='Czech writer', short_description='writer')
    doc.text_entity_clusters = [cluster]
    return doc


def face(page, person=None, source=None, suffix='1'):
    import numpy as np
    from people_gator.core.layout import PeopleGatorFaceRegionLayout, PeopleGatorFaceMetadata, Position
    meta = PeopleGatorFaceMetadata('face_' + suffix, 'MODS_FACE_' + suffix, page_identity(person, suffix),
                                  *[Position(10, 10) for _ in range(5)])
    result = PeopleGatorFaceRegionLayout('face_' + suffix, np.array([(0, 0), (20, 0), (20, 20), (0, 20)]), meta, source)
    page.regions.append(result)
    return result


def face_only(*persons):
    from people_gator.core.layout import PeopleGatorDocument, PeopleGatorPageLayout
    page = PeopleGatorPageLayout('p1', (100, 100))
    for i, person in enumerate(persons):
        face(page, person, suffix=str(i))
    return PeopleGatorDocument(page_layouts=[page])


def add_cluster(doc, name='Karel Čapek', description='French painter', person=None):
    from people_gator.core.layout import PeopleGatorTextEntityMention, PeopleGatorTextEntityCluster
    m = PeopleGatorTextEntityMention(name, description, proposed_name=name, description=description)
    doc.page_layouts[-1].text_entities.append(m)
    c = PeopleGatorTextEntityCluster([m], person, name=name, description=description)
    doc.text_entity_clusters.append(c)
    return c


@pytest.mark.parametrize('fmt', ['alto', 'page'])
def test_text_only_cross_page_aliases_rerun_and_xml(engine, fmt, tmp_path):
    from lxml import etree
    doc = document(fmt)
    cluster = doc.text_entity_clusters[0]
    members = list(cluster.text_entities)
    before = [(m.name, m.text, m.source_spans, m.line, m.span) for m in members]
    cluster_list = doc.text_entity_clusters
    assert engine.process_document(doc) is doc
    assert doc.text_entity_clusters is cluster_list
    assert cluster.identity.peoplegator_id == 'created'
    assert all(m.page_identity.identity is cluster.identity for m in members)
    assert [(m.name, m.text, m.source_spans, m.line, m.span) for m in members] == before
    assert all(m.page_identity.tag_id and m.page_identity.mods_id for m in members)
    assert len(doc.entity_linking_journal) == 1
    engine.db_api_service.search_entities.assert_called_once_with(query=['Karel Čapek', 'K. Čapek', 'writer', 'Czech writer'])
    engine.db_api_service.create_entity.assert_called_once_with(name='Karel Čapek', aliases=['K. Čapek'],
                                                               description='Czech writer', short_description='writer')
    data = engine.llm_prompter.call_args.kwargs['data']
    assert len(data['context']['sources']) == 2
    assert [s['source_spans'][0]['page_index'] for s in data['context']['sources']] == [0, 1]
    wrappers = [m.page_identity for m in members]
    engine.process_document(doc)
    assert [m.page_identity for m in members] == wrappers
    engine.db_api_service.create_entity.assert_called_once()
    out = tmp_path / 'xml'
    out.mkdir()
    getattr(doc, 'to_altoxml' if fmt == 'alto' else 'to_pagexml')(str(out))
    assert len(list(out.glob('*.xml'))) == 2
    for file in out.glob('*.xml'):
        etree.parse(str(file))
    assert doc.text_entity_clusters is cluster_list


@pytest.mark.parametrize('count', [1, 3])
def test_ambiguous_candidates_never_create_or_overwrite(engine, count):
    doc = document()
    candidates = [candidate(str(i)) for i in range(count)]
    engine.db_api_service.search_entities.return_value = {'items': candidates}
    engine.db_api_service.get_entity_info.side_effect = lambda i: candidates[int(i)]
    engine.llm_prompter.return_value = decision()
    engine.process_document(doc)
    assert doc.text_entity_clusters[0].identity is None
    assert all(m.page_identity is None for m in doc.text_entities)
    engine.db_api_service.create_entity.assert_not_called()
    assert engine.llm_prompter.call_count == 1


def test_existing_candidate_requires_context_even_for_one_hit(engine):
    doc = document()
    c = candidate()
    engine.db_api_service.search_entities.return_value = {'items': [dict(c, score=999, item_id=99)]}
    engine.db_api_service.get_entity_info.return_value = c
    engine.llm_prompter.return_value = decision('select', 0, evidence=[comparison()])
    engine.process_document(doc)
    assert doc.text_entity_clusters[0].identity.peoplegator_id == 'existing'
    engine.db_api_service.create_entity.assert_not_called()
    supplied = engine.llm_prompter.call_args.kwargs['data']['entities']
    assert supplied[0]['item_id'] == 0 and 'score' not in supplied[0]
    assert supplied[0]['aliases'] == ['K. Čapek']


@pytest.mark.parametrize('bad', [
    None, {}, {'item_id': 0, 'name': 'Karel Čapek'},
    {'action': 'select', 'source_is_person': True, 'item_id': True, 'name': 'Karel Čapek', 'reason': 'x', 'evidence': []},
    {'action': 'create', 'source_is_person': True, 'item_id': None, 'name': 'Karel Čapek', 'reason': '', 'evidence': []},
])
def test_malformed_model_results_raise_without_creation(engine, bad):
    doc = document()
    engine.llm_prompter.return_value = bad
    with pytest.raises(RuntimeError, match='unit 0'):
        engine.process_document(doc)
    engine.db_api_service.create_entity.assert_not_called()
    assert doc.text_entity_clusters[0].identity is None


@pytest.mark.parametrize('result', [
    lambda: decision('select', 5, evidence=[comparison()]),
    lambda: decision('select', 0, name='Invented', evidence=[comparison()]),
    lambda: decision('select', 0),
    lambda: decision('select', 0, evidence=[comparison(source='not in source')]),
    lambda: decision('select', 0, evidence=[comparison(candidate='invented biography')]),
    lambda: decision('select', 0, evidence=[comparison(source='Karel Čapek')]),
    lambda: decision('create'),
    lambda: dict(action='create', source_is_person=False, item_id=None, name='Karel Čapek', reason='x', evidence=[]),
])
def test_invalid_decisions_never_select_or_fall_through_to_create(engine, result):
    doc = document()
    engine.db_api_service.search_entities.return_value = {'items': [candidate()]}
    engine.db_api_service.get_entity_info.return_value = candidate()
    engine.llm_prompter.return_value = result()
    with pytest.raises(RuntimeError):
        engine.process_document(doc)
    engine.db_api_service.create_entity.assert_not_called()
    assert doc.text_entity_clusters[0].identity is None


def test_positive_different_being_evidence_can_create(engine):
    doc = document()
    engine.db_api_service.search_entities.return_value = {'items': [candidate(description='French painter')]}
    engine.db_api_service.get_entity_info.return_value = candidate(description='French painter')
    engine.llm_prompter.return_value = decision('create', evidence=[comparison(candidate='French painter')])
    engine.process_document(doc)
    assert doc.text_entity_clusters[0].identity.peoplegator_id == 'created'


@pytest.mark.parametrize('response', [None, {}, {'items': None}, {'items': [None]}, {'items': [{'entity_id': ''}]}])
def test_bad_search_is_not_empty_search(engine, response):
    doc = document()
    engine.db_api_service.search_entities.return_value = response
    with pytest.raises(RuntimeError):
        engine.process_document(doc)
    engine.llm_prompter.assert_not_called()
    engine.db_api_service.create_entity.assert_not_called()


@pytest.mark.parametrize('detail', [None, {}, candidate(entity_id='wrong'), candidate(entity_type=None),
                                         candidate(aliases=[1]), candidate(description=42)])
def test_invalid_hydration_never_creates(engine, detail):
    doc = document()
    engine.db_api_service.search_entities.return_value = {'items': [{'entity_id': 'existing'}]}
    engine.db_api_service.get_entity_info.return_value = detail
    with pytest.raises(RuntimeError):
        engine.process_document(doc)
    engine.db_api_service.create_entity.assert_not_called()


def test_non_person_candidate_cannot_be_selected(engine):
    doc = document()
    engine.db_api_service.search_entities.return_value = {'items': [candidate(entity_type='organization')]}
    engine.db_api_service.get_entity_info.return_value = candidate(entity_type='organization')
    engine.llm_prompter.return_value = decision('select', 0, evidence=[comparison()])
    with pytest.raises(RuntimeError):
        engine.process_document(doc)
    engine.db_api_service.create_entity.assert_not_called()


def test_shared_faces_resolve_once_and_unnamed_faces_stay_unchanged(engine):
    person = identity()
    doc = face_only(person, person, identity(None), identity('  '))
    before = [deepcopy(f.face_metadata.to_dict()) for f in doc.faces]
    engine.process_document(doc)
    assert [f.face_metadata.page_identity.identity.peoplegator_id for f in doc.faces] == ['created', 'created', None, None]
    engine.db_api_service.create_entity.assert_called_once()
    for f, original in zip(doc.faces[2:], before[2:]):
        assert f.face_metadata.to_dict() == original


def test_explicit_face_text_identity_reuses_one_resolution(engine):
    person = identity()
    doc = document(linked=person)
    f = face(doc.page_layouts[1], person)
    wrapper = f.face_metadata.page_identity
    engine.process_document(doc)
    assert doc.text_entity_clusters[0].identity is person
    assert wrapper.identity is person and person.peoplegator_id == 'created'
    engine.db_api_service.create_entity.assert_called_once()


def caption_document():
    from people_gator.core.layout import PeopleGatorDocument, PeopleGatorPageLayout, PeopleGatorTextEntityMention, PeopleGatorTextEntityCluster
    from people_gator.text import SourceLine, SourceSpan
    from pero_ocr.core.layout import TextLine, RegionLayout
    import numpy as np
    p = PeopleGatorPageLayout('p', (100, 100))
    polygon = np.array([(0, 0), (90, 0), (90, 10), (0, 10)])
    ln = TextLine(id='l', transcription='Karel Čapek, Czech writer.', polygon=polygon)
    region = RegionLayout('r', polygon=polygon)
    region.lines = [ln]
    p.regions.append(region)
    m = PeopleGatorTextEntityMention('Karel Čapek', ln.transcription, source_spans=(SourceSpan(SourceLine(0, 'p', 0, 'r', 0, 'l'), 0, 11),), description='Czech writer')
    p.text_entities.append(m)
    c = PeopleGatorTextEntityCluster([m], name='Karel Čapek', description='Czech writer')
    doc = PeopleGatorDocument(page_layouts=[p], text_entity_clusters=[c])
    src = NS(graphical_metadata=NS(title=ln.transcription, caption_lines_metadata=NS(lines=[ln])))
    f = face(p, source=src)
    return doc, c, f


def test_caption_support_reconciles_named_face_and_cluster(engine):
    doc, cluster, f = caption_document()
    wrapper, person = f.face_metadata.page_identity, f.face_metadata.page_identity.identity
    engine.process_document(doc)
    assert cluster.identity.peoplegator_id == person.peoplegator_id == 'created'
    assert f.face_metadata.page_identity is wrapper
    assert wrapper.identity is person and person.other_ids == {'wikidata': 'Q155855'}
    engine.db_api_service.create_entity.assert_called_once()


@pytest.mark.parametrize('ambiguous', [False, True])
def test_same_name_on_page_or_ambiguous_caption_does_not_reconcile(engine, ambiguous):
    doc, cluster, f = caption_document()
    if ambiguous:
        add_cluster(doc)
        # A second caption occurrence from another cluster shares the exact source.
        doc.text_entity_clusters[-1].text_entities[0].source_spans = cluster.text_entities[0].source_spans
        doc.text_entity_clusters[-1].text_entities[0].text = cluster.text_entities[0].text
    else:
        f.source_region.graphical_metadata.title = None
    engine.llm_prompter.side_effect = [decision('create'), *[decision() for _ in range(2 if ambiguous else 1)]]
    engine.process_document(doc)
    assert cluster.identity.peoplegator_id == 'created'
    assert f.face_metadata.page_identity.identity.peoplegator_id is None
    # Prior same-name create is offered as a candidate despite search-index lag.
    assert engine.llm_prompter.call_args.kwargs['data']['entities'][0]['entity_id'] == 'created'
    engine.db_api_service.create_entity.assert_called_once()


def test_distinct_homonymous_clusters_not_collapsed(engine):
    doc = document()
    other = add_cluster(doc)
    engine.db_api_service.create_entity.side_effect = [{'entity_id': 'writer'}, {'entity_id': 'painter'}]
    engine.llm_prompter.side_effect = [decision('create'), decision('create', evidence=[comparison(source='French painter', candidate='Czech writer')])]
    original_clusters = list(doc.text_entity_clusters)
    engine.process_document(doc)
    assert doc.text_entity_clusters == original_clusters
    assert [c.identity.peoplegator_id for c in doc.text_entity_clusters] == ['writer', 'painter']
    assert other.text_entities[0].page_identity.identity.peoplegator_id == 'painter'
    assert engine.db_api_service.create_entity.call_count == 2


def test_search_lag_reuses_created_entity_only_with_context(engine):
    doc = document()
    other = add_cluster(doc, description='Czech writer')
    engine.llm_prompter.side_effect = [decision('create'), decision('select', 0, evidence=[comparison()])]
    engine.process_document(doc)
    assert other.identity.peoplegator_id == doc.text_entity_clusters[0].identity.peoplegator_id == 'created'
    assert len(doc.text_entity_clusters) == 2
    engine.db_api_service.create_entity.assert_called_once()


def test_protected_ids_and_local_identity_metadata_survive(engine):
    doc = document(linked=identity(entity_id='manual'))
    m = doc.text_entities[0]
    m.page_identity = page_identity(identity('source spelling', 'manual'))
    wrapper, person = m.page_identity, m.page_identity.identity
    before = deepcopy(wrapper.to_dict())
    f = face(doc.page_layouts[0], doc.text_entity_clusters[0].identity)
    engine.process_document(doc)
    assert m.page_identity is wrapper and wrapper.identity is person
    assert wrapper.to_dict() == before
    assert all(m.page_identity.identity.peoplegator_id == 'manual' for m in doc.text_entities)
    assert f.face_metadata.page_identity.identity.peoplegator_id == 'manual'
    engine.db_api_service.search_entities.assert_not_called()
    engine.db_api_service.create_entity.assert_not_called()


def test_conflicting_protected_cluster_members_remain_untouched(engine):
    doc = document(linked=identity(entity_id='one'))
    m = doc.text_entities[0]
    m.page_identity = page_identity(identity(entity_id='two'))
    engine.process_document(doc)
    doc.distribute_text_entity_identities()
    assert doc.text_entity_clusters[0].identity.peoplegator_id == 'one'
    assert m.page_identity.identity.peoplegator_id == 'two'
    assert doc.text_entities[1].page_identity is None
    engine.db_api_service.search_entities.assert_not_called()


@pytest.mark.parametrize('response', [None, {}, {'entity_id': ''}, {'entity_id': 1}, {'entity_id': 'x', 'entity_type': 'organization'}])
def test_uncertain_write_is_journaled_and_not_retried(engine, response):
    doc = document()
    engine.db_api_service.create_entity.return_value = response
    with pytest.raises(RuntimeError):
        engine.process_document(doc)
    assert doc.entity_linking_journal[0]['state'] == 'uncertain'
    assert all(m.page_identity is None for m in doc.text_entities)
    engine.process_document(doc)
    engine.db_api_service.create_entity.assert_called_once()


@pytest.mark.parametrize('operation', ['search_entities', 'get_entity_info', 'llm', 'create_entity'])
def test_failures_keep_private_payloads_out_and_never_fabricate_success(engine, operation, caplog):
    doc = document()
    if operation == 'get_entity_info':
        engine.db_api_service.search_entities.return_value = {'items': [{'entity_id': 'existing'}]}
    target = engine.llm_prompter if operation == 'llm' else getattr(engine.db_api_service, operation)
    target.side_effect = RuntimeError('private-credential OCR name provider body')
    with pytest.raises(RuntimeError) as failure:
        engine.process_document(doc)
    assert 'private-credential' not in str(failure.value) + caplog.text
    assert doc.text_entity_clusters[0].identity is None
    assert all(m.page_identity is None for m in doc.text_entities)
    if operation != 'create_entity':
        engine.db_api_service.create_entity.assert_not_called()
    else:
        engine.process_document(doc)
        engine.db_api_service.create_entity.assert_called_once()


def test_partial_retry_preserves_success_and_does_not_repeat_creation(engine):
    doc = document()
    other = add_cluster(doc, name='Ada Lovelace', description='mathematician')
    engine.llm_prompter.side_effect = [decision('create'), RuntimeError('private')]
    with pytest.raises(RuntimeError):
        engine.process_document(doc)
    assert doc.text_entity_clusters[0].identity.peoplegator_id == 'created'
    assert other.identity is None
    engine.db_api_service.create_entity.return_value = {'entity_id': 'ada'}
    engine.llm_prompter.side_effect = None
    engine.llm_prompter.return_value = decision('create', name='Ada Lovelace')
    engine.process_document(doc)
    assert other.identity.peoplegator_id == 'ada'
    assert engine.db_api_service.create_entity.call_count == 2


def test_receipt_replays_after_in_memory_propagation_failure(engine, monkeypatch):
    doc = document()
    apply = engine._apply
    monkeypatch.setattr(engine, '_apply', Mock(side_effect=RuntimeError('private')))
    with pytest.raises(RuntimeError):
        engine.process_document(doc)
    assert doc.entity_linking_journal[0]['state'] == 'created'
    monkeypatch.setattr(engine, '_apply', apply)
    engine.process_document(doc)
    assert doc.text_entity_clusters[0].identity.peoplegator_id == 'created'
    engine.db_api_service.create_entity.assert_called_once()


@pytest.mark.parametrize('name', [None, '', '   ', 'unknown', '1234'])
def test_unusable_names_do_not_mutate_app(engine, name):
    doc = face_only(identity(name))
    engine.process_document(doc)
    engine.db_api_service.search_entities.assert_not_called()
    engine.db_api_service.create_entity.assert_not_called()


def test_non_person_source_with_no_candidates_stays_unresolved(engine):
    doc = face_only(identity('A company'))
    engine.llm_prompter.return_value = decision(person=False)
    engine.process_document(doc)
    engine.db_api_service.create_entity.assert_not_called()


def test_empty_and_missing_db(engine):
    from people_gator.core.layout import PeopleGatorDocument
    engine.process_document(PeopleGatorDocument())
    engine.db_api_service.search_entities.assert_not_called()
    engine.db_api_service = None
    doc = document()
    assert engine.process_document(doc) is doc
    assert doc.text_entity_clusters[0].identity is None


@pytest.mark.parametrize('with_db', [False, True])
def test_document_parser_config_omits_optional_face_assignment_stage(engine, monkeypatch, tmp_path, with_db):
    from people_gator.core import document_parser
    prompt = tmp_path / 'prompt.json'
    prompt.write_text(json.dumps({'user': '{{ name }} {{ context }} {{ entities }}'}))
    cfg = ConfigParser()
    cfg.read_dict({'ENGINE_1': {'METHOD': 'ENTITY_MATCHING', 'PROMPT_TEMPLATE_PATH': str(prompt)}})
    if with_db:
        cfg.read_dict({'DB_API': {'API_URL': 'https://example.invalid'}})
    monkeypatch.setattr(document_parser, 'DatabaseApiService', Mock(return_value=engine.db_api_service))
    parser = document_parser.DocumentParser(cfg, 'cpu', str(tmp_path))
    parser.engines[0].llm_prompter = engine.llm_prompter
    doc = document()
    assert parser.process_document(doc) is doc
    assert len(parser.engines) == 1
    assert (doc.text_entity_clusters[0].identity is not None) == with_db


def test_db_helpers_preserve_string_query_and_support_multi_term_metadata():
    from people_gator.core.db import DatabaseApiService
    service = object.__new__(DatabaseApiService)
    service.api_url = 'https://example.invalid/'
    service.connector = Mock()
    service.connector.get.return_value = NS(status_code=200, json=lambda: {'items': []})
    service.search_entities('Karel')
    assert service.connector.get.call_args.kwargs['params'] == {'query.text': 'Karel'}
    service.search_entities(['Karel', ' Karel ', '', 'writer'])
    assert service.connector.get.call_args.kwargs['params'] == {'query.text': ['Karel', 'writer']}
    service.connector.post.return_value = NS(status_code=201, json=lambda: {'entity_id': 'new'})
    assert service.create_entity('Karel', aliases=['K.', 'K.'], description='writer', short_description='author') == {'entity_id': 'new'}
    payload = service.connector.post.call_args.kwargs['json']
    assert payload['entity_type'] == 'person' and payload['aliases'] == ['K.']
    assert payload['description'] == 'writer' and payload['short_description'] == 'author'
    service.create_entity('Karel')
    payload = service.connector.post.call_args.kwargs['json']
    assert payload['aliases'] == [] and payload['description'] == payload['short_description'] == ''


def test_name_only_candidate_is_unresolved_without_descriptive_proof(engine):
    doc = face_only(identity())
    engine.db_api_service.search_entities.return_value = {'items': [candidate(description='')]}
    engine.db_api_service.get_entity_info.return_value = candidate(description='')
    engine.llm_prompter.return_value = decision()
    engine.process_document(doc)
    assert doc.faces[0].face_metadata.page_identity.identity.peoplegator_id is None
    engine.db_api_service.create_entity.assert_not_called()


def test_create_against_candidates_requires_differences_for_every_hit(engine):
    doc = document()
    engine.db_api_service.search_entities.return_value = {'items': [candidate('one'), candidate('two')]}
    engine.db_api_service.get_entity_info.side_effect = lambda i: candidate(i, description='French painter')
    engine.llm_prompter.return_value = decision('create', evidence=[comparison(candidate='French painter')])
    with pytest.raises(RuntimeError):
        engine.process_document(doc)
    engine.db_api_service.create_entity.assert_not_called()
    engine.db_api_service.get_entity_info.side_effect = lambda i: candidate(i)
    engine.llm_prompter.return_value = decision('create', evidence=[comparison(0), comparison(1)])
    with pytest.raises(RuntimeError):
        engine.process_document(doc)
    engine.db_api_service.create_entity.assert_not_called()


def test_no_cluster_descriptions_or_existing_mention_identity_gets_lost(engine):
    doc = document()
    cluster = doc.text_entity_clusters[0]
    cluster.description = cluster.short_description = None
    m = doc.text_entities[0]
    m.page_identity = page_identity(identity('K. Čapek'))
    wrapper, person = m.page_identity, m.page_identity.identity
    engine.process_document(doc)
    assert wrapper is m.page_identity and wrapper.identity is person
    assert person.name == 'K. Čapek' and person.peoplegator_id == 'created'
    assert engine.db_api_service.create_entity.call_args.kwargs['description'] == 'Czech writer'
    assert cluster.identity.peoplegator_id == 'created'


def test_no_source_descriptions_still_supports_reliable_zero_hit_creation(engine):
    doc = document()
    c = doc.text_entity_clusters[0]
    c.description = c.short_description = None
    for m in c.text_entities:
        m.description = None
    engine.process_document(doc)
    assert c.identity.peoplegator_id == 'created'
    assert engine.db_api_service.create_entity.call_args.kwargs['description'] == ''


def test_conflicting_protected_caption_links_are_not_merged(engine):
    doc, cluster, f = caption_document()
    cluster.identity = identity(entity_id='text-manual')
    f.face_metadata.page_identity.identity.peoplegator_id = 'face-manual'
    engine.process_document(doc)
    assert f.face_metadata.page_identity.identity.peoplegator_id == 'face-manual'
    assert cluster.identity.peoplegator_id == 'text-manual'
    engine.db_api_service.search_entities.assert_not_called()


def test_repeated_cluster_and_shared_cluster_identity_resolve_once_in_stable_order(engine):
    doc = document(linked=identity())
    person = doc.text_entity_clusters[0].identity
    second = add_cluster(doc, name='Other alias', description='Czech writer', person=person)
    doc.text_entity_clusters.insert(1, doc.text_entity_clusters[0])
    f = face(doc.page_layouts[0], person)
    engine.process_document(doc)
    assert person.peoplegator_id == second.identity.peoplegator_id == 'created'
    assert f.face_metadata.page_identity.identity is person
    assert engine.llm_prompter.call_args.kwargs['data']['name'] == 'Karel Čapek'
    engine.db_api_service.create_entity.assert_called_once()


def test_local_text_ids_avoid_existing_region_and_face_identity_metadata(engine):
    doc = document()
    page = doc.page_layouts[0]
    page.regions[0].id = 'person_text_001'
    f = face(page, identity(None))
    f.face_metadata.page_identity.mods_id = 'MODS_PERSON_TEXT_0002'
    engine.process_document(doc)
    m = doc.text_entities[0]
    assert m.page_identity.tag_id == 'person_text_003'
    assert m.page_identity.mods_id == 'MODS_PERSON_TEXT_0003'
    assert f.face_metadata.page_identity.identity.peoplegator_id is None


def test_multiline_and_legacy_mentions_keep_provenance_and_original_objects(engine):
    from people_gator.core.layout import PeopleGatorTextEntityMention
    from people_gator.text import SourceLine, SourceSpan
    doc = document()
    c = doc.text_entity_clusters[0]
    page = doc.page_layouts[0]
    region = next(r for r in page.regions if len(r.lines) > 1)
    ri = page.regions.index(region)
    a, b = region.lines[:2]
    a.transcription, b.transcription = 'Karel', 'Čapek'
    spans = (SourceSpan(SourceLine(0, page.id, ri, region.id, 0, a.id), 0, 5),
             SourceSpan(SourceLine(0, page.id, ri, region.id, 1, b.id), 0, 5))
    multiline = PeopleGatorTextEntityMention('Karel\nČapek', 'Karel\nČapek', source_spans=spans)
    legacy = PeopleGatorTextEntityMention('Karel', 'Karel', a, (0, 5))
    page.text_entities.extend([multiline, legacy])
    c.text_entities.extend([multiline, legacy])
    engine.process_document(doc)
    assert multiline.source_spans == spans and multiline.line is multiline.span is None
    assert legacy.line is a and legacy.span == (0, 5)
    assert multiline.name == 'Karel\nČapek' and legacy.name == 'Karel'
    assert all(m.page_identity.identity.peoplegator_id == 'created' for m in c.text_entities)


def test_uncertain_write_also_blocks_other_same_name_sources_on_retry(engine):
    doc = document()
    other = add_cluster(doc)
    engine.db_api_service.create_entity.side_effect = RuntimeError('lost response')
    with pytest.raises(RuntimeError):
        engine.process_document(doc)
    engine.process_document(doc)
    assert other.identity is None
    engine.db_api_service.create_entity.assert_called_once()


def test_page_only_uncertain_write_journal_survives_retry(engine):
    doc = face_only(identity())
    engine.db_api_service.create_entity.return_value = None
    with pytest.raises(RuntimeError):
        engine.process_page(doc.page_layouts[0])
    engine.process_page(doc.page_layouts[0])
    engine.db_api_service.create_entity.assert_called_once()


@pytest.mark.parametrize('invalid', ['foreign', 'overlap', 'empty'])
def test_invalid_cluster_membership_aborts_before_app_mutation(engine, invalid):
    doc = document()
    if invalid == 'empty':
        doc.text_entity_clusters[0].text_entities = []
    elif invalid == 'overlap':
        other = add_cluster(doc)
        other.text_entities.append(doc.text_entities[0])
    else:
        doc.text_entity_clusters[0].text_entities.append(deepcopy(doc.text_entities[0]))
    with pytest.raises(ValueError, match='original cluster members'):
        engine.process_document(doc)
    engine.db_api_service.search_entities.assert_not_called()


def test_strict_schema_and_decision_validation_reject_forged_model_instances(engine):
    from people_gator.engines.entity_matching import EntityMatchingResult
    doc = document()
    engine.llm_prompter.return_value = EntityMatchingResult.model_construct(
        action='create', source_is_person=True, item_id=None, name='Karel Čapek', reason='valid', evidence='bad')
    with pytest.raises(RuntimeError):
        engine.process_document(doc)
    engine.db_api_service.create_entity.assert_not_called()
    schema = EntityMatchingResult.model_json_schema()
    assert schema['additionalProperties'] is False
    assert schema['properties']['action']['enum'] == ['select', 'create', 'unresolved']
    assert all(k in schema['required'] for k in ['evidence', 'reason', 'source_is_person'])


def test_documented_external_prompt_renders_new_context_and_typed_provider_schema(engine, monkeypatch, tmp_path):
    from people_gator.engines import llm
    from people_gator.engines.entity_matching import EntityMatchingResult
    guide = (Path(__file__).parents[1] / 'docs' / 'PROCESSING.md').read_text()
    section = guide.split('### External prompt migration', 1)[1]
    template = json.loads(section.split('```json\n', 1)[1].split('\n```', 1)[0])
    prompt = tmp_path / 'migration.json'
    prompt.write_text(json.dumps(template))
    config = ConfigParser()
    config.read_dict({'ENGINE_1': {'METHOD': 'ENTITY_MATCHING', 'PROMPT_TEMPLATE_PATH': str(prompt),
                                  'API_URL': 'https://example.invalid', 'API_KEY': 'private', 'MODEL_NAME': 'mock'}})
    from people_gator.core.document_parser import engine_factory
    e = engine_factory(config['ENGINE_1'], str(tmp_path), 'cpu', engine.db_api_service)
    payload = decision('create').model_dump()
    create = Mock(return_value=NS(status='completed', output_text=json.dumps(payload)))
    monkeypatch.setattr(llm, 'OpenAI', Mock(return_value=NS(responses=NS(create=create))))
    doc = document()
    e.process_document(doc)
    request = create.call_args.kwargs
    assert request['text']['format']['schema'] == EntityMatchingResult.model_json_schema()
    rendered = request['input'][1]['content'][0]['text']
    assert 'SOURCE EVIDENCE:' in rendered and 'source_spans' in rendered
    assert 'CANDIDATES: []' in rendered
    assert 'unresolved' in request['input'][0]['content'][0]['text']
    assert doc.text_entity_clusters[0].identity.peoplegator_id == 'created'


@pytest.mark.parametrize('quote', ['Karel', 'Karel Čapek,', 'Čapek', ','])
@pytest.mark.parametrize('side', ['source', 'candidate'])
def test_partial_names_and_punctuation_do_not_count_as_contextual_proof(engine, quote, side):
    doc = document()
    engine.db_api_service.search_entities.return_value = {'items': [candidate()]}
    engine.db_api_service.get_entity_info.return_value = candidate(description='Karel Čapek, Czech writer')
    evidence = comparison(source=quote) if side == 'source' else comparison(candidate=quote)
    engine.llm_prompter.return_value = decision('select', 0, evidence=[evidence])
    with pytest.raises(RuntimeError):
        engine.process_document(doc)
    assert doc.text_entity_clusters[0].identity is None
    engine.db_api_service.create_entity.assert_not_called()


@pytest.mark.parametrize('fmt', ['alto', 'page'])
def test_mixed_linking_preserves_ocr_and_face_xml_contract(engine, fmt, tmp_path):
    from lxml import etree
    doc = document(fmt, linked=identity())
    shared = doc.text_entity_clusters[0].identity
    f = face(doc.page_layouts[0], shared)
    original_metadata = deepcopy(f.face_metadata.to_dict())
    original_ocr = [[ln.transcription for r in p.regions for ln in r.lines] for p in doc.page_layouts]
    original_spans = [m.source_spans for m in doc.text_entities]
    source_strings = None
    if fmt == 'alto':
        # Normal ALTO processing enriches the original namespaced source tree.
        source_dir = tmp_path / 'alto-source'
        source_dir.mkdir()
        fixture = Path(__file__).parent / 'resources' / 'text_chunking' / 'input.alto.xml'
        for page in doc.page_layouts:
            source_tree = etree.parse(str(fixture))
            span = page.text_entities[0].source_spans[0]
            line = page.regions[span.source.region_index].lines[span.source.line_index]
            source_tree.xpath('//*[local-name()="TextLine" and @ID="' + line.id + '"]/*[local-name()="String"]')[0].set('CONTENT', line.transcription)
            source_tree.write(str(source_dir / (page.id + '.xml')), encoding='utf-8')
        doc.alto_xmls_dir = str(source_dir)
        source_strings = etree.parse(str(source_dir / 'p0.xml')).xpath('//*[local-name()="String"]/@CONTENT')
    engine.process_document(doc)
    out = tmp_path / 'mixed-output'
    out.mkdir()
    getattr(doc, 'to_altoxml' if fmt == 'alto' else 'to_pagexml')(str(out))
    tree = etree.parse(str(out / 'p0.xml'))
    if fmt == 'alto':
        assert tree.xpath('//*[local-name()="String"]/@CONTENT') == source_strings
        assert tree.xpath('//*[local-name()="nameIdentifier" and @type="peoplegator"]/text()') == ['uuid:created']
        assert tree.xpath('//*[local-name()="nameIdentifier" and @type="wikidata"]/text()') == ['Q155855']
    else:
        region = tree.xpath('//*[local-name()="ImageRegion" and @id="face_1"]')[0]
        payload = json.loads(region.attrib['custom'])['metadata']['page_identity']
        assert payload['identity']['peoplegator_id'] == 'created'
        assert payload['tag_id'] == original_metadata['page_identity']['tag_id']
    assert [[ln.transcription for r in p.regions for ln in r.lines] for p in doc.page_layouts] == original_ocr
    assert [m.source_spans for m in doc.text_entities] == original_spans
    expected = deepcopy(original_metadata)
    expected['page_identity']['identity']['peoplegator_id'] = 'created'
    assert f.face_metadata.to_dict() == expected
    assert len(doc.text_entity_clusters) == 1
