"""Per-occurrence app export through the real document model and mocked HTTP."""

from configparser import ConfigParser
from copy import deepcopy
import logging
from unittest.mock import Mock, call
from uuid import UUID

import pytest


ENTITY = 'ed8bae46-adff-4c10-81d7-2b03c210cc3e'
SOURCES = ['4812610d-85c3-4400-af58-dce19d9e8a5f', 'e41b380b-e1f9-457b-a4c8-50db3a06328b']
MENTION = '18c5737b-8815-4ae5-9fef-e6571e0b667d'
PRIVATE = 'private-credential-and-ocr'


@pytest.fixture(autouse=True)
def processing_only(runtime_mode):
    if runtime_mode == 'client':
        pytest.skip('Text mention export requires processing extras')


@pytest.fixture
def document():
    import numpy as np
    from people_gator.core.layout import PeopleGatorDocument, PeopleGatorPageLayout
    pages = [PeopleGatorPageLayout('archive-page-' + str(i), (30, 30)) for i in range(2)]
    return PeopleGatorDocument(id='archive-doc', name='Test document', library='test-library',
        page_layouts=pages, page_images={p.id: np.zeros((30, 30, 3), dtype=np.uint8) for p in pages})


def mention(name=' K. Čapek ', context='K. Čapek\npíše.', entity_id=ENTITY, index=0):
    from people_gator.core.layout import PeopleGatorIdentity, PeopleGatorPageIdentity, PeopleGatorTextEntityMention
    from people_gator.text import SourceLine, SourceSpan
    identity = PeopleGatorPageIdentity('person', 'MODS_PERSON', PeopleGatorIdentity('Canonical name', entity_id))
    return PeopleGatorTextEntityMention(name, context, page_identity=identity,
        source_spans=(SourceSpan(SourceLine('page', 'region', 'line', index, 0, 0), 2, 12),),
        proposed_name='Normalized name', description=PRIVATE)


@pytest.fixture
def service():
    from people_gator.core.db import DatabaseApiService
    result = Mock(spec=DatabaseApiService)
    result.get_document_info.return_value = {'source_id': 'document-source'}
    result.get_page_info.side_effect = lambda doc, page, library: {'source_id': SOURCES[int(page[-1])]}
    result.create_text_mention.return_value = response_payload()
    return result


def response_payload(**changes):
    return dict(mention_id=MENTION, name=' K. Čapek ', context='K. Čapek\npíše.',
                entity_id=ENTITY, source_id=SOURCES[0]) | changes


@pytest.fixture
def api():
    from people_gator.core.db import DatabaseApiService
    result = object.__new__(DatabaseApiService)
    result.api_url = 'https://example.invalid/'
    result.connector = Mock()
    result.connector.post.return_value = Mock(status_code=201)
    result.connector.post.return_value.json.return_value = response_payload()
    return result


def test_every_occurrence_uses_page_source_and_preserves_data(document, service):
    from people_gator.core.document_parser import export_document
    from people_gator.core.layout import PeopleGatorTextEntityCluster
    first, second, third = mention(), mention(), mention(context=None, index=1)
    document.page_layouts[0].text_entities = [first, second]
    document.page_layouts[1].text_entities = [third]
    document.text_entity_clusters = [PeopleGatorTextEntityCluster([first, second, third], name='Canonical name')]
    members = [first, second, third]
    before = deepcopy([vars(m) for m in members])
    spans = [m.source_spans for m in members]
    wrappers = [m.page_identity for m in members]
    clusters = document.text_entity_clusters

    assert export_document(document, service) is None
    assert service.create_text_mention.call_args_list == [
        call(name=m.name, context=m.text, entity_id=ENTITY, source_id=source)
        for m, source in zip(members, [SOURCES[0], SOURCES[0], SOURCES[1]])]
    for m, saved, span, wrapper in zip(members, before, spans, wrappers):
        assert m.source_spans is span
        assert m.page_identity is wrapper
        assert {k: v for k, v in vars(m).items() if k != 'page_identity'} == {
            k: v for k, v in saved.items() if k != 'page_identity'}
        assert vars(m.page_identity.identity) == vars(saved['page_identity'].identity)
    assert document.text_entity_clusters is clusters
    service.create_entity.assert_not_called()
    service.create_face.assert_not_called()
    assert service.put_page_image.call_count == service.put_page_layout.call_count == 2


def test_distinct_mentions_in_one_page_keep_their_own_names_and_links(document, service):
    from people_gator.core.document_parser import export_document
    document.page_layouts.pop()
    second_id = '2157f6c9-cb6e-4864-a91e-a26ac08327d5'
    items = [mention(), mention(name='Josef Čapek', context='Josef maluje.', entity_id=second_id)]
    document.page_layouts[0].text_entities = items
    export_document(document, service)
    assert service.create_text_mention.call_args_list == [
        call(name=m.name, context=m.text, entity_id=m.page_identity.identity.peoplegator_id,
             source_id=SOURCES[0]) for m in items]
    service.create_entity.assert_not_called()


@pytest.mark.parametrize('bad', ['wrapper', 'identity', None, '', ' ', 'not-a-uuid', 123, True])
def test_unresolved_and_invalid_ids_are_skipped(document, service, caplog, bad):
    from people_gator.core.document_parser import export_document
    item = mention(entity_id=bad)
    if bad == 'wrapper':
        item.page_identity = None
    elif bad == 'identity':
        item.page_identity.identity = None
    document.page_layouts[0].text_entities = [item]
    with caplog.at_level(logging.DEBUG):
        export_document(document, service)
    service.create_text_mention.assert_not_called()
    service.create_entity.assert_not_called()
    assert 'skipped 1 unresolved/invalid text mentions' in caplog.text
    assert PRIVATE not in caplog.text
    assert service.put_page_layout.call_count == 2


@pytest.mark.parametrize('name', [None, '', '  \n\t', '\u2003', 123])
def test_unusable_names_are_skipped(document, service, caplog, name):
    from people_gator.core.document_parser import export_document
    item = mention(name=name)
    document.page_layouts[0].text_entities = [item]
    export_document(document, service)
    service.create_text_mention.assert_not_called()
    service.create_entity.assert_not_called()
    assert item.name == name
    assert 'skipped 1 unresolved/invalid text mentions' in caplog.text


@pytest.mark.parametrize('with_text', [True, False])
def test_mixed_and_face_only_keep_faces_and_artifacts(document, service, with_text):
    import numpy as np
    from people_gator.core.document_parser import export_document
    from people_gator.core.layout import PeopleGatorFaceRegionLayout
    face = PeopleGatorFaceRegionLayout('face', np.array([(0, 0), (10, 0), (10, 10)]), None, None)
    page = document.page_layouts[0]
    page.regions.append(face)
    if with_text:
        page.text_entities.append(mention())
    export_document(document, service)
    service.create_face.assert_called_once_with(face, SOURCES[0])
    assert service.create_text_mention.call_count == int(with_text)
    assert service.put_page_image.call_args_list == [call(document.page_images[p.id], source)
                                                    for p, source in zip(document.page_layouts, SOURCES)]
    assert service.put_page_layout.call_args_list == [call(p.to_app_dict(), source)
                                                     for p, source in zip(document.page_layouts, SOURCES)]


def test_page_and_document_creation_and_missing_page(document, service):
    from people_gator.core.document_parser import export_document
    for page in document.page_layouts:
        page.text_entities.append(mention())
    service.get_document_info.return_value = None
    service.create_document.return_value = {'source_id': 'document-source'}
    service.get_page_info.side_effect = [None, None]
    service.create_page.side_effect = [None, {'source_id': SOURCES[1]}]
    export_document(document, service)
    service.create_document.assert_called_once_with('archive-doc', 'Test document', library='test-library')
    assert service.create_page.call_args_list == [call(p.id, document.id, library=document.library) for p in document.page_layouts]
    service.create_text_mention.assert_called_once_with(name=' K. Čapek ', context='K. Čapek\npíše.', entity_id=ENTITY, source_id=SOURCES[1])
    service.put_page_layout.assert_called_once_with(document.page_layouts[1].to_app_dict(), SOURCES[1])
    assert [c[0] for c in service.method_calls] == ['get_document_info', 'create_document',
        'get_page_info', 'create_page', 'get_page_info', 'create_page', 'create_text_mention',
        'put_page_image', 'put_page_layout']


def test_parser_entry_point_and_reexport_keeps_every_occurrence(document, service, monkeypatch):
    from people_gator.core import document_parser
    document.page_layouts[0].text_entities = [mention(), mention()]
    monkeypatch.setattr(document_parser, 'DatabaseApiService', Mock(return_value=service))
    config = ConfigParser()
    config.read_dict({'DB_API': {}})
    parser = document_parser.DocumentParser(config, 'cpu', '.')
    for _ in range(2):
        assert parser.process_document(document, export_to_app=True, drop_existing_annotations=True) is document
    assert service.create_text_mention.call_count == 4
    assert service.delete_document_annotations.call_args_list == [call(document.id, library=document.library)] * 2
    service.get_text_mentions_for_page.assert_not_called()
    service.get_text_mentions_for_document.assert_not_called()


@pytest.mark.parametrize('context', [None, ''])
def test_absent_context_and_skips_do_not_block_valid_occurrence(document, service, context):
    from people_gator.core.document_parser import export_document
    document.page_layouts[0].text_entities = [mention(entity_id=None), mention(name=' '), mention(context=context)]
    export_document(document, service)
    service.create_text_mention.assert_called_once_with(name=' K. Čapek ', context=None,
                                                       entity_id=ENTITY, source_id=SOURCES[0])
    assert document.page_layouts[0].text_entities[-1].text == context


def test_empty_document_preserves_existing_flow(document, service):
    from people_gator.core.document_parser import export_document
    document.page_layouts.clear()
    export_document(document, service)
    service.get_page_info.assert_not_called()
    service.create_text_mention.assert_not_called()
    service.put_page_image.assert_not_called()


def test_deletion_helper_still_removes_faces_only(api):
    pages, faces = Mock(status_code=200), Mock(status_code=200)
    pages.json.return_value = {'items': [{'page_id': 'archive-page', 'source_id': SOURCES[0]}]}
    faces.json.return_value = {'items': [{'detection_id': 'face'}]}
    api.connector.get.side_effect = [pages, faces]
    api.connector.delete.return_value = Mock(status_code=204)
    assert api.delete_document_annotations('document', 'library') is True
    api.connector.delete.assert_called_once_with('https://example.invalid/api/v1/faces/face')
    assert len(api.connector.get.call_args_list) == 2
    assert all('text-mentions' not in c.args[0] for c in api.connector.get.call_args_list)


def test_sending_payload_and_optional_model(api):
    from pydantic import BaseModel
    class Response(BaseModel):
        mention_id: UUID
    result = api.create_text_mention(' K. Čapek ', ENTITY, SOURCES[0], context='K. Čapek\npíše.')
    assert result == response_payload()
    api.connector.post.assert_called_once_with('https://example.invalid/api/v1/text-mentions', json={
        'name': ' K. Čapek ', 'entity_id': ENTITY, 'source_id': SOURCES[0],
        'context': 'K. Čapek\npíše.', 'entity_link_state': 'automatic'})
    assert isinstance(api.create_text_mention(' K. Čapek ', ENTITY, SOURCES[0], response_model=Response), Response)


@pytest.mark.parametrize('status', [200, 400, 401, 422, 500, 503])
def test_only_http_201_is_success(api, status):
    api.connector.post.return_value.status_code = status
    assert api.create_text_mention(' K. Čapek ', ENTITY, SOURCES[0]) is None
    api.connector.post.return_value.json.assert_not_called()


@pytest.mark.parametrize('failure', ['http', 'json', 'model', 'connector', 'empty', 'array', 'missing', 'invalid-id',
                                      'invalid-source', 'invalid-entity', 'invalid-name', 'invalid-context'])
def test_service_failure_conventions(api, caplog, failure):
    import requests
    response = api.connector.post.return_value
    options = {}
    raises = None
    if failure == 'http':
        response.status_code = 422
    elif failure == 'json':
        response.json.side_effect = ValueError(PRIVATE)
        raises = ValueError
    elif failure == 'model':
        options['response_model'] = Mock(side_effect=ValueError(PRIVATE))
    elif failure == 'connector':
        api.connector.post.side_effect = requests.ConnectionError(PRIVATE)
        raises = requests.ConnectionError
    else:
        response.json.return_value = {'empty': None, 'array': [], 'missing': {'error': PRIVATE},
            'invalid-id': response_payload(mention_id=PRIVATE),
            'invalid-source': response_payload(source_id=PRIVATE),
            'invalid-entity': response_payload(entity_id=None),
            'invalid-name': response_payload(name=' '),
            'invalid-context': response_payload(context={})}[failure]
    with caplog.at_level(logging.DEBUG):
        if raises:
            with pytest.raises(raises):
                api.create_text_mention(' K. Čapek ', ENTITY, SOURCES[0], **options)
        else:
            assert api.create_text_mention(' K. Čapek ', ENTITY, SOURCES[0], **options) is None
    assert PRIVATE not in caplog.text
    if failure == 'http':
        response.json.assert_not_called()


@pytest.mark.parametrize('failure', ['http', 'json', 'invalid', 'connector'])
def test_failed_mention_does_not_stop_other_mentions_faces_or_uploads(document, service, api, caplog, failure):
    import requests
    import numpy as np
    from people_gator.core.document_parser import export_document
    from people_gator.core.layout import PeopleGatorFaceRegionLayout
    first = Mock(status_code=503 if failure == 'http' else 201)
    first.json.return_value = []
    if failure == 'json':
        first.json.side_effect = ValueError(PRIVATE)
    second = api.connector.post.return_value
    api.connector.post.side_effect = [requests.ConnectionError(PRIVATE) if failure == 'connector' else first, second]
    service.create_text_mention.side_effect = api.create_text_mention
    document.page_layouts[0].text_entities = [mention(), mention()]
    face = PeopleGatorFaceRegionLayout('face', np.array([(0, 0), (10, 0), (10, 10)]), None, None)
    document.page_layouts[1].regions.append(face)
    with caplog.at_level(logging.DEBUG):
        export_document(document, service)
    assert api.connector.post.call_count == 2
    assert 'exported 1 text mentions; 1 failed' in caplog.text
    assert PRIVATE not in caplog.text
    service.create_face.assert_called_once_with(face, SOURCES[1])
    assert service.put_page_image.call_count == service.put_page_layout.call_count == 2
