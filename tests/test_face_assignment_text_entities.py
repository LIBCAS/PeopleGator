"""Image-local text evidence, external prompts and face request correspondence."""

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
        pytest.skip('Face assignment requires processing extras')


def polygon(x=0, y=0, width=40, height=10):
    return [(x, y), (x + width, y), (x + width, y + height), (x, y + height)]


def line(text, x=0, y=0):
    return NS(id='repeated-line', transcription=text, polygon=polygon(x, y), heights=(5, 5))


def page(*lines):
    return NS(id='repeated-page', regions=[NS(id='repeated-region', category='text', lines=list(lines))],
              text_entities=[], reading_order={}, lines_iterator=lambda: iter(lines))


def mention(page, pi, li=0, name=None, context=None, legacy=False, spans=None):
    from people_gator.core.layout import PeopleGatorTextEntityMention
    from people_gator.text import SourceLine, SourceSpan
    ln = page.regions[0].lines[li]
    name = name or ln.transcription
    start = ln.transcription.index(name)
    source = SourceLine(pi, page.id, 0, page.regions[0].id, li, ln.id)
    m = PeopleGatorTextEntityMention(name, context or ln.transcription,
                                   ln if legacy else None, (start, start + len(name)) if legacy else None,
                                   source_spans=spans if spans is not None else (() if legacy else (SourceSpan(source, start, start + len(name)),)),
                                   proposed_name='Proposed ' + name, description='source description')
    page.text_entities.append(m)
    return m


def source(title=None, caption_lines=None):
    metadata = NS(title=title, caption_lines_metadata=NS(lines=caption_lines) if caption_lines is not None else None)
    return NS(graphical_metadata=metadata)


def select(pages, src=None, clusters=(), bbox=(0, 0, 50, 50)):
    from people_gator.engines.face_entity_context import FaceEntityContext, assigned_caption
    src = src or source()
    doc = NS(page_layouts=pages, text_entity_clusters=list(clusters))
    return FaceEntityContext(doc).select(pages[0], src, bbox, assigned_caption(src))


def names(records):
    return [record['name'] for record in records]


def test_caption_source_objects_override_same_names_and_titles():
    from people_gator.core.layout import PeopleGatorTextEntityCluster
    p = page(line('Karel Čapek'), line('Karel Čapek', y=80), line('Ada Lovelace', y=100))
    a, b, c = [mention(p, 0, i) for i in range(3)]
    off = page(line('Off page'))
    mention(off, 1)
    cluster = PeopleGatorTextEntityCluster([a], name='Karel', short_description='writer')
    result = select([p, off], source('Karel Čapek', [p.regions[0].lines[0]]), [cluster])
    assert names(result['caption_entities']) == ['Karel Čapek']
    record = result['caption_entities'][0]
    assert record == {
        'provenance': 'caption', 'page_index': 0, 'page_id': p.id,
        'name': a.name, 'context': a.text, 'proposed_name': a.proposed_name, 'description': a.description,
        'source_spans': [{'page_index': 0, 'page_id': p.id, 'region_index': 0,
                          'region_id': 'repeated-region', 'line_index': 0, 'line_id': 'repeated-line', 'start': 0, 'end': 11}],
        'cluster': {'name': 'Karel', 'short_description': 'writer', 'description': None, 'provisional': True}}
    assert all(result[k] == [] for k in ['surrounding_entities', 'page_entities', 'document_entities'])
    assert names(select([p], source('Ada Lovelace', [p.regions[0].lines[2]]))['caption_entities']) == [c.name]
    # A foreign line with a reused XML ID has no association.
    assert select([p], source('Karel Čapek', [line('Karel Čapek')]))['caption_entities'] == []


@pytest.mark.parametrize('title', [None, '', 'An unnamed photograph'])
def test_fallback_keeps_surrounding_whole_page_and_off_page_separate(title):
    p = page(line('Local'), line('Other on page', y=80))
    local, other = mention(p, 0), mention(p, 0, 1, legacy=True)
    off = page(line('Off page'))
    background = mention(off, 1)
    result = select([p, off], source(title))
    assert result['caption_entities'] == []
    assert names(result['surrounding_entities']) == [local.name]
    assert names(result['page_entities']) == [local.name, other.name]
    assert names(result['document_entities']) == [background.name]
    assert result['document_entities'][0]['source_spans'][0]['page_index'] == 1
    assert result['page_entities'][1]['source_spans'][0]['line_index'] == 1
    assert result['surrounding_entities'][0]['provenance'] == 'surrounding'
    assert result['page_entities'][0]['provenance'] == 'page'
    json.dumps(result, ensure_ascii=False)


def test_text_only_caption_uses_complete_context_not_proposed_names():
    p = page(line('Left: Karel Čapek.'), line('Elsewhere Karel Čapek.', y=80), line('Ann', y=100))
    mention(p, 0, name='Karel Čapek')
    mention(p, 0, 1, name='Karel Čapek')
    mention(p, 0, 2)
    result = select([p], source('Left: Karel Čapek.'))
    assert names(result['caption_entities']) == ['Karel Čapek']
    assert result['caption_entities'][0]['source_spans'][0]['line_index'] == 0
    for title in ['Proposed Karel Čapek', 'JoAnn', 'Karel Čapek']:
        assert select([p], source(title))['caption_entities'] == []
    p.regions[0].lines.append(line('Left: Karel Čapek.', y=120))
    mention(p, 0, 3, name='Karel Čapek')
    assert select([p], source('Left: Karel Čapek.'))['caption_entities'] == []


def test_multiline_unicode_hyphenation_and_repeated_ids():
    from people_gator.text import SourceLine, SourceSpan
    p = page(line('Karel Ča-'), line('pek 😀', y=10))
    spans = (SourceSpan(SourceLine(0, p.id, 0, 'repeated-region', 0, 'repeated-line'), 0, 9),
             SourceSpan(SourceLine(0, p.id, 0, 'repeated-region', 1, 'repeated-line'), 0, 3))
    from people_gator.core.layout import PeopleGatorTextEntityMention
    m = PeopleGatorTextEntityMention('Karel Ča-\npek', 'Karel Ča-\npek 😀', source_spans=spans)
    p.text_entities = [m]
    result = select([p], source('Karel Čapek 😀'))
    assert names(result['caption_entities']) == [m.name]
    assert result['caption_entities'][0]['source_spans'][1]['line_index'] == 1
    assert names(select([p], bbox=(0, 12, 20, 17))['surrounding_entities']) == [m.name]
    # Wrong page indices are never resolved by matching reused IDs.
    m.source_spans = (SourceSpan(SourceLine(1, p.id, 0, 'repeated-region', 0, 'repeated-line'), 0, 5),)
    assert select([p])['surrounding_entities'] == []
    assert select([p], source('Karel Čapek 😀'))['caption_entities'] == []


def test_cluster_filtering_membership_deduplication_and_unclustered_homonyms():
    from people_gator.core.layout import PeopleGatorTextEntityCluster
    p, q, r = page(line('Local')), page(line('Alias'), line('Off'), line('Off')), page(line('Other alias'))
    a = mention(p, 0)
    b, c, d = [mention(q, 1, i) for i in range(3)]
    e = mention(r, 2)
    on_page = PeopleGatorTextEntityCluster([a, b], name='Person')
    off_page = PeopleGatorTextEntityCluster([c, e], name='Person', short_description='provisional')
    q.text_entities.append(c)  # Repeated object reference is not another occurrence.
    records = select([p, q, r], clusters=[on_page, off_page])['document_entities']
    assert len(records) == 2
    assert records[0]['name'] == 'Person' and records[0]['aliases'] == ['Off', 'Other alias']
    assert [s['page_index'] for s in records[0]['sources']] == [1, 2]
    assert records[1]['name'] == d.name and 'sources' not in records[1]
    assert 'identity' not in json.dumps(records)
    unclustered = select([p, q, r])['document_entities']
    assert names(unclustered) == ['Alias', 'Off', 'Off', 'Other alias']


@pytest.mark.parametrize('case', ['page', 'document', 'empty', 'missing'])
def test_empty_locality_and_absent_stages(case):
    p, q = page(line('Page', y=90)), page(line('Background'))
    if case == 'page':
        mention(p, 0)
    if case == 'document':
        mention(q, 1)
    if case == 'missing':
        del p.text_entities
    result = select([p, q])
    assert result['surrounding_entities'] == []
    assert names(result['page_entities']) == (['Page'] if case == 'page' else [])
    assert names(result['document_entities']) == (['Background'] if case == 'document' else [])


def make_engine(tmp_path, mode='single'):
    from people_gator.engines.face_assignment import LLMFaceAssignmentEngine, LLMBatchFaceAssignmentEngine
    prompt = tmp_path / 'prompt.json'
    prompt.write_text(json.dumps({'system': 'Use source evidence.', 'user': '{{ caption_entities }}'}))
    config = ConfigParser()
    config.read_dict({'engine': {'PROMPT_TEMPLATE_PATH': str(prompt), 'PROCESSING_MODE': mode if mode != 'single' else 'sequential'}})
    cls = LLMFaceAssignmentEngine if mode == 'single' else LLMBatchFaceAssignmentEngine
    return cls(config['engine'], 'cpu', str(tmp_path))


def engine_document():
    import numpy as np
    from people_gator.core.layout import PeopleGatorFaceRegionLayout
    p = page(line('Caption A'), line('Caption B', x=70), line('Article', y=90))
    q = page(line('Background'))
    for i in range(3):
        mention(p, 0, i)
    mention(q, 1)
    regions = []
    for index, title in enumerate(['Caption A', 'Caption B']):
        src = source(title)
        src.get_polygon_bounding_box = lambda index=index: (index * 60, 0, index * 60 + 50, 70)
        # NS is not hashable; source regions are dictionary keys in batch mode.
        class Region:
            pass
        region = Region()
        region.graphical_metadata = src.graphical_metadata
        region.get_polygon_bounding_box = src.get_polygon_bounding_box
        regions.append(region)
        for j in range(2):
            face = PeopleGatorFaceRegionLayout(id=f'f{index}{j}', polygon=np.array(polygon(index * 60 + j * 15, 20, 10, 10)), category='face',
                                              source_region=region, face_metadata=NS(page_identity=NS(identity=NS(name=None))))
            p.regions.append(face)
    image = np.zeros((120, 120, 3), dtype=np.uint8)
    return NS(id='document', page_layouts=[p, q], text_entity_clusters=[], pages_iterator=lambda: iter([(image, p), (image, q)])), regions


@pytest.mark.parametrize('mode', ['single', 'sequential', 'page_parallel', 'document_parallel'])
@pytest.mark.parametrize('caption', [True, False])
def test_all_engine_modes_exact_requests_and_null_preservation(tmp_path, mode, caption):
    from people_gator.engines.face_assignment import FaceAssignmentResult, BatchFaceAssignmentResult
    doc, sources = engine_document()
    p = doc.page_layouts[0]
    if not caption:
        for src in sources:
            src.graphical_metadata.title = 'Unnamed'
    engine = make_engine(tmp_path, mode)
    requests = []
    before = deepcopy([m.__dict__ for page_ in doc.page_layouts for m in page_.text_entities])
    original_lines = [(ln, ln.transcription) for pg in doc.page_layouts for ln in pg.lines_iterator()]

    def respond(data, images, response_model):
        requests.append((deepcopy(data), images, response_model))
        if mode == 'single':
            assert response_model is FaceAssignmentResult
            return FaceAssignmentResult(name_in_text=None, name_normalized=None)
        assert response_model is BatchFaceAssignmentResult
        return BatchFaceAssignmentResult(faces=[dict(id=f['id'], coordinates=f['coordinates'], name_in_text=None, name_normalized=None) for f in data['faces']])

    def parallel(data_list, images_list, response_model):
        return [respond(d, i, response_model) for d, i in zip(data_list, images_list)]

    engine.llm_prompter = Mock(side_effect=respond)
    engine.llm_prompter.process.side_effect = respond
    engine.llm_prompter.process_parallel.side_effect = parallel
    assert engine.process_document(doc) is doc
    assert len(requests) == (4 if mode == 'single' else 2)
    for index, (data, images, model) in enumerate(requests):
        source_index = index // 2 if mode == 'single' else index
        if caption:
            assert data['caption_text'] == f'Caption {"AB"[source_index]}'
            assert names(data['caption_entities']) == [data['caption_text']]
            assert data['document_entities'] == data['page_entities'] == data['surrounding_entities'] == []
        else:
            assert data['caption_entities'] == []
            assert names(data['surrounding_entities']) == [f'Caption {"AB"[source_index]}']
            assert names(data['page_entities']) == ['Caption A', 'Caption B', 'Article']
            assert names(data['document_entities']) == ['Background']
            assert data['document_entities'][0]['page_index'] == 1
        assert len(images) == (2 if mode == 'single' else 1)
        assert images[-1].shape == (70, 50, 3)
        if mode == 'single':
            assert data['face_coordinates'] == ((10 if index % 2 == 0 else 40), 36)
        else:
            assert [(f['id'], f['coordinates'], f['color_name']) for f in data['faces']] == [(0, (10, 36), 'red'), (1, (40, 36), 'green')]
    assert [m.__dict__ for page_ in doc.page_layouts for m in page_.text_entities] == before
    assert all(ln.transcription == text for ln, text in original_lines)
    assert all(face.face_metadata.page_identity.identity.name is None for face in p.regions[1:])


@pytest.mark.parametrize('mode', ['single', 'sequential', 'page_parallel', 'document_parallel'])
def test_missing_ocr_and_earlier_engines_still_make_image_requests(tmp_path, mode):
    from people_gator.engines.face_assignment import FaceAssignmentResult, BatchFaceAssignmentResult
    doc, _ = engine_document()
    for p in doc.page_layouts:
        p.text_entities = []
        p.regions[0].lines = []
        p.lines_iterator = lambda: iter(())
    engine = make_engine(tmp_path, mode)
    result = FaceAssignmentResult(name_in_text=None, name_normalized=None) if mode == 'single' else BatchFaceAssignmentResult(faces=[])
    engine.llm_prompter = Mock(return_value=result)
    engine.llm_prompter.process.return_value = result
    engine.llm_prompter.process_parallel.side_effect = lambda data_list, **kwargs: [result] * len(data_list)
    assert engine.process_document(doc) is doc
    prepared = engine.prepare_face_data(__import__('numpy').zeros((120, 120, 3), dtype='uint8'), doc.page_layouts[0], doc)
    assert all(all(v == [] for v in item.entity_context.values()) for item in prepared)


@pytest.mark.parametrize('mode', ['single', 'sequential', 'page_parallel', 'document_parallel'])
def test_result_correspondence_images_and_partial_predictions(tmp_path, mode):
    import numpy as np
    from people_gator.engines.face_assignment import FaceAssignmentResult, BatchFaceAssignmentResult
    doc, _ = engine_document()
    p = doc.page_layouts[0]
    image = next(doc.pages_iterator())[0]
    doc.pages_iterator = lambda: iter([(image, p)])
    engine = make_engine(tmp_path, mode)
    requests = []

    def respond(data, images, response_model):
        requests.append(data)
        if mode == 'single':
            # Independent per-face decisions in the original face order.
            name = data['caption_text'] if len(requests) % 2 == 0 else None
            return FaceAssignmentResult(name_in_text=name, name_normalized=name)
        # Provider output order differs, only one prediction is positive.
        faces = [dict(id=f['id'], coordinates=f['coordinates'], name_in_text=data['caption_text'] if f['id'] else None,
                      name_normalized=data['caption_text'] if f['id'] else None) for f in reversed(data['faces'])]
        faces += [dict(id=999, coordinates=[10, 36], name_in_text='wrong', name_normalized='wrong'),
                  dict(id=0, coordinates=[10], name_in_text='partial', name_normalized='partial')]
        return BatchFaceAssignmentResult(faces=faces)

    engine.llm_prompter = Mock(side_effect=respond)
    engine.llm_prompter.process.side_effect = respond
    engine.llm_prompter.process_parallel.side_effect = lambda data_list, images_list, response_model: [respond(d, i, response_model) for d, i in zip(data_list, images_list)]
    engine.process_document(doc)
    assert [f.face_metadata.page_identity.identity.name for f in p.regions[1:]] == [None, 'Caption A', None, 'Caption B']
    assert np.count_nonzero(image) == 0  # Markers only modify copied crops.
    data = engine.prepare_face_data(image, p, doc)
    if mode == 'single':
        assert tuple(data[0].context_image[20, 0]) == (0, 255, 0)
    else:
        assert tuple(data[0].context_image[20, 0]) == (0, 0, 255)
        assert tuple(data[0].context_image[20, 15]) == (0, 255, 0)


@pytest.mark.parametrize('mode', ['single', 'sequential'])
def test_missing_transcription_is_not_joined_or_rewritten(tmp_path, mode):
    import numpy as np
    doc, _ = engine_document()
    p = doc.page_layouts[0]
    p.regions[0].lines[0].transcription = None
    p.text_entities = []
    engine = make_engine(tmp_path, mode)
    data = engine.prepare_face_data(np.zeros((120, 120, 3), dtype='uint8'), p, doc)
    assert data[0].context_text is None
    assert p.regions[0].lines[0].transcription is None


@pytest.mark.parametrize('key', ['czech', 'english', 'other', 'empty'])
def test_caption_language_dictionaries_shared_between_engines(key):
    from anno_page.enums.language import Language
    from people_gator.engines.face_entity_context import assigned_caption
    values = {'czech': {Language.ENGLISH: 'English', Language.CZECH: 'Česky'},
              'english': {Language.ENGLISH: 'English'}, 'other': {None: 'Other'}, 'empty': {}}
    assert assigned_caption(source(values[key])) == {'czech': 'Česky', 'english': 'English', 'other': 'Other', 'empty': None}[key]


def migration_prompt():
    # Historical incomplete fragment: a test fixture, never a deployable prompt.
    path = Path(__file__).parent / 'resources' / 'face_assignment' / 'migration_fragment.json'
    return json.loads(path.read_text(encoding='utf-8'))


@pytest.mark.parametrize('branch', ['caption', 'fallback', 'empty'])
@pytest.mark.parametrize('mode', ['single', 'sequential'])
def test_external_prompt_migration_rendering_schema_and_warnings(tmp_path, caplog, branch, mode):
    from people_gator.engines.face_assignment import FaceAssignmentResult, BatchFaceAssignmentResult
    engine = make_engine(tmp_path, mode)
    prompt = migration_prompt()
    if mode == 'single':
        prompt['user'] = prompt['user'].replace('FACES: {{ faces | tojson }}', 'FACE_COORDINATES: {{ face_coordinates | tojson }}')
    path = tmp_path / 'prompt.json'
    path.write_text(json.dumps(prompt))
    engine = make_engine_from_prompt(path, mode)
    data = {'caption_text': 'Source', 'context_text': 'OCR',
            'caption_entities': [], 'surrounding_entities': [], 'page_entities': [], 'document_entities': []}
    if mode == 'single':
        data['face_coordinates'] = (10, 36)
        model = FaceAssignmentResult
    else:
        data['faces'] = [{'id': 0, 'coordinates': (10, 36), 'color_name': 'red'}]
        model = BatchFaceAssignmentResult
    if branch == 'caption':
        data['caption_entities'] = [{'name': 'Čapek', 'provenance': 'caption'}]
    elif branch == 'fallback':
        data['page_entities'] = [{'name': 'Local', 'provenance': 'page'}]
        data['document_entities'] = [{'name': 'Background', 'provenance': 'document', 'provisional': True}]
    request = engine.llm_prompter._prepare_request_args(data, response_model=model)
    messages = request['input']
    rendered = json.dumps(messages, ensure_ascii=False)
    assert 'CAPTION_TEXT:' in rendered and 'SURROUNDING_TEXT:' in rendered
    if branch == 'caption':
        assert 'CAPTION_ENTITIES:' in rendered and 'DOCUMENT_ENTITIES' not in rendered
        assert 'PAGE_ENTITIES:' not in rendered and 'SURROUNDING_ENTITIES:' not in rendered
    else:
        assert all(label in rendered for label in ['SURROUNDING_ENTITIES:', 'PAGE_ENTITIES:', 'DOCUMENT_ENTITIES'])
        assert 'CAPTION_ENTITIES:' not in rendered
    assert request['text']['format']['schema'] == model.model_json_schema()
    assert not caplog.records
    policy = prompt['system']
    for required in ['highest priority', 'weaker local candidates', 'weakest background candidates',
                     'never guess', 'only candidate', 'occurs frequently', 'null', 'independently', 'normalization']:
        assert required in policy
    # Ordinary shared diagnostics still identify an unmigrated external prompt.
    engine.llm_prompter._template_variables = {'caption_text'}
    engine.llm_prompter._prepare_request_args(data, response_model=model)
    assert 'document_entities is unused' in caplog.text
    assert not any(value in caplog.text for value in ['Čapek', 'Background', 'Source'])


def make_engine_from_prompt(path, mode):
    from people_gator.engines.face_assignment import LLMFaceAssignmentEngine, LLMBatchFaceAssignmentEngine
    config = ConfigParser()
    config.read_dict({'engine': {'PROMPT_TEMPLATE_PATH': str(path)}})
    cls = LLMFaceAssignmentEngine if mode == 'single' else LLMBatchFaceAssignmentEngine
    return cls(config['engine'], 'cpu', str(path.parent))


def test_text_only_caption_is_bound_to_original_character_occurrence():
    from people_gator.core.layout import PeopleGatorTextEntityMention
    from people_gator.text import SourceLine, SourceSpan
    p = page(line('Article Karel; caption: Karel and Ada.'))
    ln = p.regions[0].lines[0]
    address = SourceLine(0, p.id, 0, 'repeated-region', 0, ln.id)
    for spelling, start in [('Karel', 8), ('Karel', 24), ('Ada', 34)]:
        # Detection context can be wider than the title; exact source positions
        # still distinguish identical names on the same original OCR line.
        p.text_entities.append(PeopleGatorTextEntityMention(spelling, ln.transcription,
            source_spans=(SourceSpan(address, start, start + len(spelling)),)))
    title = 'caption: Karel and Ada.'
    result = select([p], source(title))
    assert names(result['caption_entities']) == ['Karel', 'Ada']
    assert [r['source_spans'][0]['start'] for r in result['caption_entities']] == [24, 34]
    # If only the unrelated article occurrence was detected, do not borrow it.
    p.text_entities = p.text_entities[:1]
    assert select([p], source(title))['caption_entities'] == []


@pytest.mark.parametrize('format', ['alto', 'page'])
def test_real_document_parser_detection_clustering_then_face_context(tmp_path, monkeypatch, format):
    import numpy as np
    from anno_page.core.layout import AnnoPageRegionLayout
    from anno_page.core.metadata import GraphicalObjectMetadata
    from people_gator.core.document_parser import DocumentParser
    from people_gator.core.layout import PeopleGatorDocument, PeopleGatorFaceRegionLayout
    from people_gator.engines.face_assignment import FaceAssignmentResult
    from people_gator.engines.llm import LLMPrompter
    from people_gator.engines.text_entity_detection import TextEntityDetectionResult
    from people_gator.engines.text_entity_clustering import TextEntityClusteringResult
    fixtures = Path(__file__).parent / 'resources' / 'text_chunking'
    xml_dir = tmp_path / 'xml'
    xml_dir.mkdir()
    for i in range(2):
        (xml_dir / f'p{i}.xml').write_text((fixtures / f'input.{format}.xml').read_text())
    doc = PeopleGatorDocument(**{'alto_xmls_dir' if format == 'alto' else 'page_xmls_dir': str(xml_dir)})
    for p in doc.page_layouts:
        image = np.zeros((100, 100, 3), dtype=np.uint8)
        doc.page_images[p.id] = image
        src = AnnoPageRegionLayout('photo', np.array(polygon(0, 0, 60, 60)), category='image',
                                   graphical_metadata=GraphicalObjectMetadata('tag', 'mods', title='Čapek 😀'))
        face = PeopleGatorFaceRegionLayout('face', np.array(polygon(10, 20, 10, 10)), category='face',
                                          source_region=src, face_metadata=NS(page_identity=NS(identity=NS(name=None))))
        p.regions.extend([src, face])
    original_regions = [region for p in doc.page_layouts for region in p.regions]
    ocr = [(ln, ln.transcription) for p in doc.page_layouts for ln in p.lines_iterator()]
    prompt = tmp_path / 'external.json'
    prompt.write_text(json.dumps({'system': 'Externally supplied', 'user': '{{ text }}'}))
    config = ConfigParser()
    config.read_dict({f'ENGINE_{i}': {'METHOD': method, 'PROMPT_TEMPLATE_PATH': str(prompt)}
                      for i, method in enumerate(['TEXT_ENTITY_DETECTION', 'TEXT_ENTITY_CLUSTERING', 'LLM_FACE_ASSIGNMENT'])})
    seen = []
    face_requests = []

    def predict(self, data, response_model, images=None):
        seen.append(response_model)
        if response_model is TextEntityDetectionResult:
            return {'entities': [{'name': 'Karel Čapek', 'type': 'being', 'info': 'writer',
                                  'mentions': [{'name': 'Čapek', 'context': 'Čapek 😀'}]}]}
        if response_model is TextEntityClusteringResult:
            return {'clusters': [{'name': 'Karel Čapek', 'short_description': 'writer', 'long_description': None, 'entity_indices': [1, 2]}]}
        face_requests.append(data)
        return FaceAssignmentResult(name_in_text=None, name_normalized=None)

    monkeypatch.setattr(LLMPrompter, '__call__', predict)
    parser = DocumentParser(config, 'cpu', str(tmp_path))
    for engine in parser.engines:
        engine.process_document = Mock(wraps=engine.process_document)
    assert parser.process_document(doc) is doc
    assert seen == [TextEntityDetectionResult] * 2 + [TextEntityClusteringResult] + [FaceAssignmentResult] * 2
    assert all(engine.process_document.call_args.args[0] is doc for engine in parser.engines)
    assert len(face_requests) == 2
    for index, data in enumerate(face_requests):
        record = data['caption_entities'][0]
        assert record['name'] == 'Čapek' and record['cluster']['name'] == 'Karel Čapek'
        assert record['page_index'] == record['source_spans'][0]['page_index'] == index
        assert data['document_entities'] == []
    assert [region for p in doc.page_layouts for region in p.regions] == original_regions
    assert all(ln.transcription == text for ln, text in ocr)
    assert all(np.count_nonzero(image) == 0 for image in doc.page_images.values())


def test_text_only_metadata_evidence_fallback_and_page_only_caller():
    from people_gator.engines.face_entity_context import FaceEntityContext
    p = page(line('Karel\nČapek'))
    mention(p, 0)
    # Metadata may add wording absent from OCR; use complete source evidence,
    # never a canonical proposal, while retaining the original source spelling.
    src = source('Portrait of Karel Čapek.')
    record = FaceEntityContext().select(p, src, (0, 0, 50, 50), src.graphical_metadata.title)['caption_entities'][0]
    assert record['name'] == 'Karel\nČapek' and record['page_index'] == 0


@pytest.mark.parametrize('mode', ['single', 'sequential', 'page_parallel', 'document_parallel'])
@pytest.mark.parametrize('unresolved_name', [None, '', '   ', '\t\r\n', '\u00a0\u2003'])
def test_unresolved_predictions_preserve_existing_face_identities(tmp_path, mode, unresolved_name):
    from people_gator.engines.face_assignment import FaceAssignmentResult, BatchFaceAssignmentResult
    doc, _ = engine_document()
    faces = doc.page_layouts[0].regions[1:]
    identities = [f.face_metadata.page_identity.identity for f in faces]
    for i, identity in enumerate(identities):
        identity.name = f'Existing {i}' if i % 2 == 0 else None
        identity.peoplegator_id = f'app-{i}'
        identity.other_ids = {'authority': str(i)}
    before = [deepcopy(identity.__dict__) for identity in identities]
    engine = make_engine(tmp_path, mode)

    def predict(data, images, response_model):
        if mode == 'single':
            positive = data['face_coordinates'][0] == 40
            name = f" {data['caption_text']} " if positive else unresolved_name
            return FaceAssignmentResult(name_in_text=data['caption_text'] if positive else None, name_normalized=name)
        return BatchFaceAssignmentResult(faces=[dict(id=f['id'], coordinates=f['coordinates'],
            name_in_text=data['caption_text'] if f['id'] else None,
            name_normalized=f" {data['caption_text']} " if f['id'] else unresolved_name) for f in reversed(data['faces'])])

    engine.llm_prompter = Mock(side_effect=predict)
    engine.llm_prompter.process.side_effect = predict
    engine.llm_prompter.process_parallel.side_effect = lambda data_list, images_list, response_model: [
        predict(d, i, response_model) for d, i in zip(data_list, images_list)]
    assert engine.process_document(doc) is doc
    assert [identity.name for identity in identities] == ['Existing 0', ' Caption A ', 'Existing 2', ' Caption B ']
    for i, (face, identity) in enumerate(zip(faces, identities)):
        assert face.face_metadata.page_identity.identity is identity
        if i % 2 == 0:
            assert identity.__dict__ == before[i]
        else:
            assert identity.peoplegator_id == before[i]['peoplegator_id']
            assert identity.other_ids == before[i]['other_ids']


@pytest.mark.parametrize('legacy', [False, True])
def test_assigned_captions_sharing_one_ocr_line_select_only_their_characters(legacy):
    text = 'Image A: Alice Smith. Image B: Bob Jones.'
    p = page(line(text))
    mention(p, 0, name='Alice Smith', legacy=legacy)
    mention(p, 0, name='Bob Jones', legacy=legacy)
    for title, name in [('Image A: Alice Smith.', 'Alice Smith'), ('Image B: Bob Jones.', 'Bob Jones')]:
        result = select([p], source(title, [p.regions[0].lines[0]]))
        assert names(result['caption_entities']) == [name]
        assert result['caption_entities'][0]['source_spans'][0]['start'] == text.index(name)
        assert all(result[key] == [] for key in ['surrounding_entities', 'page_entities', 'document_entities'])


@pytest.mark.parametrize('title', [None, 'A paraphrased caption', 'Portrait: Alice.'])
def test_caption_lines_without_unique_character_association_use_fallback(title):
    from people_gator.text import SourceSpan
    p = page(line('Portrait: Alice. Portrait: Alice.'))
    first = mention(p, 0, name='Alice')
    second = mention(p, 0, name='Alice')
    start = p.regions[0].lines[0].transcription.rindex('Alice')
    second.source_spans = (SourceSpan(first.source_spans[0].source, start, start + len('Alice')),)
    result = select([p], source(title, [p.regions[0].lines[0]]))
    assert result['caption_entities'] == []
    assert names(result['surrounding_entities']) == ['Alice', 'Alice']
    assert names(result['page_entities']) == ['Alice', 'Alice']


@pytest.mark.parametrize('kind', ['empty', 'foreign', 'stale', 'untranscribed', 'none'])
@pytest.mark.parametrize('repeated', [False, True])
def test_unusable_caption_lines_try_title_mapping_without_weakening_ambiguity(kind, repeated):
    p = page(line('Image A: Alice Smith.'), line('Image B: Bob Jones.', y=90))
    mention(p, 0, name='Alice Smith')
    mention(p, 0, 1, name='Bob Jones')
    if repeated:
        p.regions[0].lines.append(line('Image A: Alice Smith.', y=100))
        mention(p, 0, 2, name='Alice Smith')
    refs = []
    if kind == 'foreign':
        refs = [line('Image A: Alice Smith.')]
    elif kind == 'stale':
        old = p.regions[0].lines[0]
        p.regions[0].lines[0] = line(old.transcription)
        refs = [old]
    elif kind == 'untranscribed':
        empty = line(None)
        p.regions[0].lines.append(empty)
        refs = [empty]
    src = source('Image A: Alice Smith.', refs)
    if kind == 'none':
        src.graphical_metadata.caption_lines_metadata.lines = None
    result = select([p], src)
    assert names(result['caption_entities']) == ([] if repeated else ['Alice Smith'])
    if repeated:
        assert names(result['page_entities']) == ['Alice Smith', 'Bob Jones', 'Alice Smith']


def test_unusable_caption_lines_allow_safe_text_evidence_fallback():
    p = page(line('Alice Smith'))
    mention(p, 0)
    assert names(select([p], source('Portrait of Alice Smith.', []))['caption_entities']) == ['Alice Smith']


def test_usable_caption_references_do_not_borrow_another_lines_title():
    p = page(line('Image A: Alice Smith.'), line('Image B: Bob Jones.', y=90))
    mention(p, 0, name='Alice Smith')
    mention(p, 0, 1, name='Bob Jones')
    result = select([p], source('Image B: Bob Jones.', [p.regions[0].lines[0]]))
    assert result['caption_entities'] == []
    assert names(result['page_entities']) == ['Alice Smith', 'Bob Jones']


@pytest.mark.parametrize('mode', ['single', 'sequential', 'page_parallel', 'document_parallel'])
@pytest.mark.parametrize('with_document', [False, True])
@pytest.mark.parametrize('caption', [False, True])
def test_later_page_direct_preparation_and_processing_preserve_original_indices(tmp_path, mode, with_document, caption):
    from dataclasses import replace
    from people_gator.engines.face_assignment import FaceAssignmentResult, BatchFaceAssignmentResult
    doc, sources = engine_document()
    p, other = doc.page_layouts
    doc.page_layouts = [other, p]
    for pi, pg in enumerate(doc.page_layouts):
        for m in pg.text_entities:
            m.source_spans = tuple(replace(span, source=replace(span.source, page_index=pi)) for span in m.source_spans)
    if not caption:
        for src in sources:
            src.graphical_metadata.title = 'Unnamed'
    document = doc if with_document else None
    image = next(doc.pages_iterator())[0]
    engine = make_engine(tmp_path, mode)
    before = [m.__dict__.copy() for m in p.text_entities]
    prepared = engine.prepare_face_data(image, p, document=document)
    requests = []

    def predict(data, images, response_model):
        requests.append(data)
        return FaceAssignmentResult(name_in_text=None, name_normalized=None) if mode == 'single' else BatchFaceAssignmentResult(faces=[])

    engine.llm_prompter = Mock(side_effect=predict)
    engine.llm_prompter.process.side_effect = predict
    engine.llm_prompter.process_parallel.side_effect = lambda data_list, images_list, response_model: [
        predict(d, i, response_model) for d, i in zip(data_list, images_list)]
    assert engine.process_page(image, p, document=document) is p
    assert len(requests) == len(prepared) == (4 if mode == 'single' else 2)
    for i, (item, data) in enumerate(zip(prepared, requests)):
        key = 'caption_entities' if caption else 'surrounding_entities'
        assert names(data[key]) == [f'Caption {"AB"[i // 2 if mode == "single" else i]}']
        assert data[key] == item.entity_context[key]
        assert all(record['page_index'] == 1 and record['source_spans'][0]['page_index'] == 1 for record in data[key])
        if not caption:
            assert all(record['page_index'] == 1 for record in data['page_entities'])
            assert names(data['document_entities']) == (['Background'] if with_document else [])
    assert [m.__dict__ for m in p.text_entities] == before


@pytest.mark.parametrize('mode', ['single', 'sequential', 'page_parallel', 'document_parallel'])
@pytest.mark.parametrize('legacy', [False, True])
def test_noncontiguous_caption_lines_in_all_engine_modes(tmp_path, mode, legacy):
    from dataclasses import replace
    from people_gator.core.layout import PeopleGatorTextEntityMention
    from people_gator.engines.face_assignment import FaceAssignmentResult, BatchFaceAssignmentResult
    doc, sources = engine_document()
    p = doc.page_layouts[0]
    first, last, article = p.regions[0].lines
    p.regions[0].lines = [first, article, last]
    p.lines_iterator = lambda: iter(p.regions[0].lines)
    for m in p.text_entities:
        m.source_spans = tuple(replace(span, source=replace(span.source, line_index={0: 0, 1: 2, 2: 1}[span.source.line_index])) for span in m.source_spans)
    multiline = PeopleGatorTextEntityMention('Caption A\nCaption B', 'Caption A\nCaption B',
                                             source_spans=p.text_entities[0].source_spans + p.text_entities[1].source_spans)
    p.text_entities.append(multiline)
    if legacy:
        p.text_entities[1].source_spans = ()
        p.text_entities[1].line = last
        p.text_entities[1].span = (0, len(last.transcription))
    for src in sources:
        src.graphical_metadata.title = 'Caption A Caption B'
        # Reference-list order/duplicates and foreign references cannot override OCR order.
        src.graphical_metadata.caption_lines_metadata = NS(lines=[last, first, first, line('Article')])
    before = [m.__dict__.copy() for m in p.text_entities]
    requests = []
    engine = make_engine(tmp_path, mode)

    def predict(data, images, response_model):
        requests.append(data)
        return FaceAssignmentResult(name_in_text=None, name_normalized=None) if mode == 'single' else BatchFaceAssignmentResult(faces=[])

    engine.llm_prompter = Mock(side_effect=predict)
    engine.llm_prompter.process.side_effect = predict
    engine.llm_prompter.process_parallel.side_effect = lambda data_list, images_list, response_model: [
        predict(d, i, response_model) for d, i in zip(data_list, images_list)]
    assert engine.process_document(doc) is doc
    assert len(requests) == (4 if mode == 'single' else 2)
    for data in requests:
        assert names(data['caption_entities']) == ['Caption A', 'Caption B', 'Caption A\nCaption B']
        assert [span['line_index'] for span in data['caption_entities'][-1]['source_spans']] == [0, 2]
        assert data['surrounding_entities'] == data['page_entities'] == data['document_entities'] == []
    assert [m.__dict__ for m in p.text_entities] == before
    assert [ln.transcription for ln in p.regions[0].lines] == ['Caption A', 'Article', 'Caption B']


def test_noncontiguous_caption_reconstruction_keeps_repeated_title_ambiguous():
    p = page(line('Alice'), line('Article'), line('Bob'), line('Alice'), line('Bob'))
    for i in [0, 2, 3, 4]:
        mention(p, 0, i)
    refs = [p.regions[0].lines[i] for i in [0, 2, 3, 4]]
    result = select([p], source('Alice Bob', refs))
    assert result['caption_entities'] == []
    assert names(result['page_entities']) == ['Alice', 'Bob', 'Alice', 'Bob']


def test_standalone_page_infers_index_for_legacy_mentions_from_mapped_mentions():
    from people_gator.engines.face_entity_context import FaceEntityContext
    p = page(line('Alice Smith'), line('Bob Jones'))
    mapped = mention(p, 7)
    legacy = mention(p, 7, 1, legacy=True)
    result = FaceEntityContext().select(p, source(), (0, 0, 50, 50), None)
    assert names(result['surrounding_entities']) == [mapped.name, legacy.name]
    assert [record['page_index'] for record in result['surrounding_entities']] == [7, 7]
    assert result['surrounding_entities'][1]['source_spans'][0]['page_index'] == 7


def test_standalone_legacy_only_page_reports_unknown_index_without_fabricating_zero():
    from people_gator.engines.face_entity_context import FaceEntityContext
    p = page(line('Alice Smith'))
    mention(p, 9, legacy=True)
    record = FaceEntityContext().select(p, source(), (0, 0, 50, 50), None)['surrounding_entities'][0]
    assert record['page_index'] is None
    assert record['source_spans'][0]['page_index'] is None
    assert record['source_spans'][0]['line_index'] == 0


def test_standalone_conflicting_page_indices_remain_page_evidence():
    from people_gator.engines.face_entity_context import FaceEntityContext
    p = page(line('Alice Smith'), line('Bob Jones'))
    mention(p, 1)
    mention(p, 2, 1)
    result = FaceEntityContext().select(p, source(), (0, 0, 50, 50), None)
    assert result['surrounding_entities'] == []
    assert names(result['page_entities']) == ['Alice Smith', 'Bob Jones']
    assert all(record['page_index'] is None and record['source_spans'] == [] for record in result['page_entities'])


def test_caption_view_retains_region_reading_order_offsets_and_dehyphenation():
    from people_gator.core.layout import PeopleGatorTextEntityMention
    from people_gator.text import SourceLine, SourceSpan
    first = line('Left: Karel Ča-')
    last = line('pek. Image B: Bob Jones.')
    article = line('Ada Lovelace')
    p = page()
    # Original region indices differ from their OCR reading order.
    p.regions = [NS(id='end', category='text', lines=[last]),
                 NS(id='article', category='text', lines=[article]),
                 NS(id='start', category='text', lines=[first])]
    p.reading_order = {'start': 0, 'article': 1, 'end': 2}
    spans = (SourceSpan(SourceLine(0, p.id, 2, 'start', 0, first.id), 6, len(first.transcription)),
             SourceSpan(SourceLine(0, p.id, 0, 'end', 0, last.id), 0, 3))
    m = PeopleGatorTextEntityMention('Karel Ča-\npek', 'Karel Ča-\npek', source_spans=spans)
    bob_start = last.transcription.index('Bob Jones')
    bob = PeopleGatorTextEntityMention('Bob Jones', last.transcription, source_spans=(
        SourceSpan(spans[1].source, bob_start, bob_start + len('Bob Jones')),))
    p.text_entities = [m, bob]
    result = select([p], source('Karel Čapek.', [last, first, line(article.transcription)]))
    assert names(result['caption_entities']) == [m.name]
    records = result['caption_entities'][0]['source_spans']
    assert [record['region_index'] for record in records] == [2, 0]
    assert [(record['start'], record['end']) for record in records] == [(6, len(first.transcription)), (0, 3)]
    assert m.source_spans is spans
    assert [r.lines[0].transcription for r in p.regions] == [last.transcription, article.transcription, first.transcription]
