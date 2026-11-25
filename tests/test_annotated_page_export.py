"""Replay annotated PAGE files through the CLI and authenticated app client."""

from html import escape
import json
import logging
import sys
from unittest.mock import Mock, call

import pytest


API = 'https://example.invalid/api/v1'
PERSON_ID = 'ed8bae46-adff-4c10-81d7-2b03c210cc3e'
EXISTING_ID = '4812610d-85c3-4400-af58-dce19d9e8a5f'
SOURCE_IDS = {'p1': 'e41b380b-e1f9-457b-a4c8-50db3a06328b',
              'p2': '18c5737b-8815-4ae5-9fef-e6571e0b667d'}
POINTS = [(5, 5), (10, 5), (7, 8), (5, 11), (9, 11)]
POINT_NAMES = ['left_eye', 'right_eye', 'nose', 'left_mouth_corner', 'right_mouth_corner']


@pytest.fixture(autouse=True)
def processing_only(runtime_mode):
    if runtime_mode == 'client':
        pytest.skip('PAGE export requires processing extras')


def face_xml(face_id, person_id, name, other_ids=None):
    metadata = {
        'tag_id': face_id,
        'mods_id': 'MODS_' + face_id,
        'page_identity': {
            'tag_id': 'person_' + face_id,
            'mods_id': 'MODS_person_' + face_id,
            'identity': {'peoplegator_id': person_id, 'name': name, 'other_ids': other_ids},
        },
    }
    metadata.update({key + '_position': {'x': x, 'y': y}
                     for key, (x, y) in zip(POINT_NAMES, POINTS)})
    custom = escape(json.dumps({'category': 'face', 'metadata': metadata,
                                'source_region': 'photo'}), quote=True)
    return (f'<ImageRegion id="{face_id}" custom="{custom}">'
            '<Coords points="3,3 13,3 13,14 3,14"/></ImageRegion>')


@pytest.fixture
def run_cli(tmp_path, monkeypatch):
    import cv2
    import numpy as np
    from people_gator.core import db, document_parser
    from user_scripts import parse_folder

    config = tmp_path / 'export.ini'
    config.write_text('[DB_API]\napi_url = https://example.invalid\n'
                      'username = test\npassword = test\n', encoding='utf-8')
    metadata = tmp_path / 'metadata.json'
    metadata.write_text(json.dumps({'document': {'id': 'doc', 'name': 'Test book',
                                                  'library': 'library'}}), encoding='utf-8')
    images, pages = tmp_path / 'images', tmp_path / 'pages'
    images.mkdir()
    pages.mkdir()
    monkeypatch.setattr(sys, 'argv', [
        'peoplegator', '--config', str(config), '--input-image-path', str(images),
        '--input-xml-path', str(pages), '--input-metadata-path', str(metadata), '--export-to-app',
    ])
    connector = Mock()
    monkeypatch.setattr(db, 'Connector', Mock(return_value=connector))
    engine_factory = Mock(side_effect=AssertionError('unexpected processing engine'))
    app_import = Mock(side_effect=AssertionError('unexpected app import'))
    monkeypatch.setattr(document_parser, 'engine_factory', engine_factory)
    monkeypatch.setattr(document_parser, 'import_document', app_import)
    monkeypatch.setattr(parse_folder, 'setup_logging', Mock())
    export_document = document_parser.export_document

    def checked_export(document, *args, **kwargs):
        def identities():
            return [(face.id, face.face_metadata.page_identity.identity.to_dict())
                    for face in document.faces]

        before = identities()
        assert all(face.source_region.id == 'photo' for face in document.faces)
        export_document(document, *args, **kwargs)
        assert identities() == before

    exported = Mock(side_effect=checked_export)
    monkeypatch.setattr(document_parser, 'export_document', exported)

    def run(faces):
        for page, regions in faces.items():
            assert cv2.imwrite(str(images / f'{page}.jpg'), np.zeros((32, 32, 3), dtype=np.uint8))
            (pages / f'{page}.xml').write_text(
                f'<PcGts xmlns="http://schema.primaresearch.org/PAGE/gts/pagecontent/2019-07-15">'
                f'<Page imageFilename="{page}.jpg" imageWidth="32" imageHeight="32">'
                '<ImageRegion id="photo"><Coords points="0,0 31,0 31,31 0,31"/></ImageRegion>'
                + ''.join(regions) + '</Page></PcGts>',
                encoding='utf-8')
        original_xml = {p: p.read_bytes() for p in pages.glob('*.xml')}

        assert parse_folder.main() == 0
        engine_factory.assert_not_called()
        app_import.assert_not_called()
        assert original_xml == {p: p.read_bytes() for p in original_xml}
        return exported.call_args.args[0]

    return connector, run


def response(status, data=None):
    result = Mock(status_code=status)
    result.json.return_value = data
    return result


def person(entity_id, name):
    return {'entity_id': entity_id, 'entity_type': 'person', 'name': name}


@pytest.mark.parametrize('name, put_status', [(' Karel Čapek ', 201), (None, 201), ('', 201), ('Recorded', 200)])
def test_replay_creates_missing_uuid_and_reuses_it_within_and_across_exports(run_cli, caplog, name, put_status):
    connector, run = run_cli
    existing = person(EXISTING_ID, 'Stored name')
    people = {EXISTING_ID: existing}
    doc = {'source_id': 'app-document'}
    registered_pages = {}

    def get(url, params=None):
        if url == API + '/documents/lookup':
            return response(200, doc) if registered_pages else response(404)
        if url == API + '/pages/lookup':
            page = registered_pages.get(params['page_id'])
            return response(200, page) if page else response(404)
        assert url in {f'{API}/entities/{entity_id}' for entity_id in (PERSON_ID, EXISTING_ID)}
        entity = people.get(url.rsplit('/', 1)[1])
        return response(200, entity) if entity else response(404)

    def post(url, json):
        if url == API + '/documents':
            assert json == {'library': 'library', 'document_id': 'doc', 'name': 'Test book'}
            return response(201, doc)
        if url == API + '/pages':
            assert json['library'] == 'library' and json['document_id'] == 'doc'
            page = json['page_id']
            registered_pages[page] = {'source_id': SOURCE_IDS[page]}
            return response(201, registered_pages[page])
        assert url == API + '/faces'
        assert json['entity_id'] in people
        return response(201, {'detection_id': 'created'})

    def put(url, **kwargs):
        if url.endswith(('/image', '/page-layout')):
            return response(200, {'uploaded': True})
        assert url == f'{API}/entities/{PERSON_ID}'
        people[PERSON_ID] = person(PERSON_ID, kwargs['json']['name'])
        return response(put_status, people[PERSON_ID])

    connector.get.side_effect = get
    connector.post.side_effect = post
    connector.put.side_effect = put
    other_ids = {'wikidata': 'Q155855', 'unknown': 'ignore'}
    faces = {
        'p1': [face_xml('first', PERSON_ID, name, other_ids),
               face_xml('second', PERSON_ID, 'Different recorded name'),
               face_xml('existing', EXISTING_ID, 'Different from database')],
        'p2': [face_xml('third', PERSON_ID, name, other_ids)],
    }
    for first_run in (True, False):
        connector.reset_mock()
        document = run(faces)
        assert next(f for f in document.faces if f.id == 'first').face_metadata.page_identity.identity.name == name
        entity_calls = [c for c in connector.method_calls if '/entities' in c.args[0]]
        lookup = call.get(f'{API}/entities/{PERSON_ID}')
        creation = call.put(f'{API}/entities/{PERSON_ID}', json={
            'entity_type': 'person', 'name': '' if name is None else name, 'wikidata_id': 'Q155855'})
        assert entity_calls.count(lookup) == 1
        assert entity_calls.count(call.get(f'{API}/entities/{EXISTING_ID}')) == 1
        assert len(entity_calls) == (3 if first_run else 2)
        face_calls = [c for c in connector.post.call_args_list if c.args[0] == API + '/faces']
        payloads = {c.kwargs['json']['identifier']: c.kwargs['json'] for c in face_calls}
        assert len(face_calls) == 4
        for face_id, source, entity_id in [
            ('first', 'p1', PERSON_ID), ('second', 'p1', PERSON_ID),
            ('third', 'p2', PERSON_ID), ('existing', 'p1', EXISTING_ID),
        ]:
            payload = payloads[face_id]
            assert payload['entity_id'] == entity_id
            assert payload['entity_link_state'] == 'automatic'
            assert payload['source_id'] == SOURCE_IDS[source]
            assert payload['bounding_box'] == {'x': 3, 'y': 3, 'width': 10, 'height': 11}
            assert payload['keypoints'] == [{'type': key, 'x': x, 'y': y}
                                            for key, (x, y) in zip(POINT_NAMES, POINTS)]
        first_link = next(i for i, c in enumerate(connector.method_calls)
                          if c.args[0] == API + '/faces' and c.kwargs['json']['entity_id'] == PERSON_ID)
        writes = connector.method_calls
        assert writes.index(lookup) < first_link
        if first_run:
            assert writes.index(lookup) < writes.index(creation) < first_link
        uploads = [c.args[0] for c in connector.put.call_args_list if '/pages/' in c.args[0]]
        assert sorted(uploads) == sorted(f'{API}/pages/{source}/{suffix}'
                                        for source in SOURCE_IDS.values() for suffix in ('image', 'page-layout'))
        assert people[EXISTING_ID] == person(EXISTING_ID, 'Stored name')
    assert ('replaced' in caplog.text) == (put_status == 200)


@pytest.mark.parametrize('step, failure', [
    ('get', 401), ('get', 403), ('get', 503), ('get', 'authentication'),
    ('get', 'network'), ('get', 'json'), ('get', 'wrong-id'),
    ('put', 409), ('put', 503), ('put', 'network'), ('put', 'json'), ('put', 'wrong-id'),
])
def test_unresolved_face_is_skipped_and_other_faces_and_artifacts_continue(run_cli, caplog, step, failure):
    from requests import ConnectionError
    from people_gator.core.connector import AuthenticationError

    connector, run = run_cli
    private = 'private credentials'
    if isinstance(failure, int):
        failed = response(failure)
    elif failure == 'authentication':
        failed = AuthenticationError(private)
    elif failure == 'network':
        failed = ConnectionError(private)
    elif failure == 'json':
        failed = response(200 if step == 'get' else 201)
        failed.json.side_effect = ValueError(private)
    else:
        failed = response(200 if step == 'get' else 201, person(EXISTING_ID, 'Wrong entity'))

    def get(url, params=None):
        if url == API + '/documents/lookup':
            return response(200, {'source_id': 'doc'})
        if url == API + '/pages/lookup':
            return response(200, {'source_id': SOURCE_IDS[params['page_id']]})
        if url == f'{API}/entities/{EXISTING_ID}':
            return response(200, person(EXISTING_ID, 'Already stored'))
        assert url == f'{API}/entities/{PERSON_ID}'
        if step == 'get' and isinstance(failed, Exception):
            raise failed
        return failed if step == 'get' else response(404)

    connector.get.side_effect = get
    connector.put.side_effect = ([failed] if step == 'put' else []) + [response(200, {'uploaded': True})] * 2
    connector.post.return_value = response(201, {'detection_id': 'created'})
    with caplog.at_level(logging.DEBUG):
        run({'p1': [face_xml('skipped', PERSON_ID, 'Recorded'),
                    face_xml('linked', EXISTING_ID, 'Recorded'),
                    face_xml('unlinked', None, 'Recorded'),
                    face_xml('legacy', 'invalid-uuid', 'Recorded')]})
    assert [c.args[0] for c in connector.put.call_args_list] == (
        [f'{API}/entities/{PERSON_ID}'] * (step == 'put')
        + [f'{API}/pages/{SOURCE_IDS["p1"]}/{suffix}' for suffix in ('image', 'page-layout')])
    assert [c.args[0] for c in connector.post.call_args_list] == [API + '/faces'] * 3
    payloads = [c.kwargs['json'] for c in connector.post.call_args_list]
    assert [(p['identifier'], p.get('entity_id')) for p in payloads] == [
        ('linked', EXISTING_ID), ('unlinked', None), ('legacy', 'invalid-uuid')]
    assert 'Failed to resolve entity' in caplog.text
    assert 'Created face skipped' not in caplog.text
    assert private not in caplog.text
