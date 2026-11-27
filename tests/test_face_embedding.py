"""Face embeddings through the configured pipeline and native checkpoints."""

from configparser import ConfigParser
from datetime import datetime
from unittest.mock import Mock

import pytest


MODEL = 'gaunernst/vit_small_patch8_gap_112.cosface_ms1mv3'
REFERENCE = [(38.2946, 51.6963), (73.5318, 51.5014), (56.0252, 71.7366),
             (41.5493, 92.3655), (70.7299, 92.2041)]


@pytest.fixture(autouse=True)
def processing_only(runtime_mode):
    if runtime_mode == 'client':
        pytest.skip('Face embeddings require the processing extras')


@pytest.fixture
def inference(monkeypatch):
    import timm
    import torch

    model = torch.nn.Linear(3, 512)

    def forward(pixels):
        assert not torch.is_grad_enabled()
        assert not model.training
        assert model.weight.device == pixels.device == torch.device('cpu')
        assert model.weight.dtype == pixels.dtype
        assert pixels.shape == (1, 3, 112, 112)
        features = pixels.new_zeros((1, 512))
        features[0, 0] = 1
        features[0, 1] = 3 if pixels[0, 0, 50, 50] > 0 else -3
        return features

    model.forward = Mock(side_effect=forward)
    load = Mock(return_value=model)
    monkeypatch.setattr(timm, 'create_model', load)
    return load, model.forward


def config(**settings):
    ini = ConfigParser()
    ini['ENGINE_FACE_EMBEDDING'] = {'METHOD': 'FACE_EMBEDDING', 'MODEL': MODEL, **settings}
    return ini


def add_face(page, source, face_id, polygon, landmarks, name=None):
    from people_gator.core.layout import (
        PeopleGatorFaceMetadata, PeopleGatorFaceRegionLayout,
        PeopleGatorIdentity, PeopleGatorPageIdentity,
    )

    identity = PeopleGatorPageIdentity(f'person-{face_id}', f'mods-person-{face_id}',
                                       PeopleGatorIdentity(name, peoplegator_id=None))
    metadata = PeopleGatorFaceMetadata(face_id, f'mods-{face_id}', identity, *landmarks)
    face = PeopleGatorFaceRegionLayout(face_id, polygon, metadata, source, category='face')
    page.regions.append(face)
    return face


def test_configured_order_embeddings_and_checkpoint(tmp_path, monkeypatch, inference):
    import numpy as np
    from anno_page.core.embedding import ObjectEmbedding, ProcessingInfo
    from pero_ocr.core.layout import RegionLayout
    from people_gator import globals
    from people_gator.core import document_parser
    from people_gator.core.checkpoints import load_checkpoint
    from people_gator.core.layout import PeopleGatorDocument, PeopleGatorPageLayout, Position

    load, forward = inference
    polygon = np.array([(35, 45), (95, 45), (95, 115), (35, 115)])
    landmarks = [Position(x + 10, y + 15) for x, y in REFERENCE]
    first, second, no_faces = (PeopleGatorPageLayout(f'page-{i}', (150, 150)) for i in range(3))
    illustration = RegionLayout(id='source', polygon=polygon, category='illustration')
    first.regions.append(illustration)
    face = add_face(first, illustration, 'face-1', polygon, landmarks)
    other_face = add_face(second, None, 'face-2', polygon, [None] * 5, name='Named face')
    identity = other_face.face_metadata.page_identity.identity
    face.face_metadata.prompts.append({'prompt': 'original'})
    original_embeddings = face.embeddings
    existing = ObjectEmbedding(
        id='prior', tag_id=face.id, page_uuid=first.id, category='face', embedding=[1.0],
        processing_info=ProcessingInfo(datetime='2026-01-01T00:00:00Z', model='prior',
                                       decimal_places=None, precision='torch.float32'),
    )
    original_embeddings.append(existing)

    # The small patch lands at (50, 50) only after shifting by the landmarks.
    first_pixels = np.zeros((150, 150, 3), dtype=np.uint8)
    first_pixels[63:68, 58:63] = (0, 128, 255)
    second_pixels = np.zeros_like(first_pixels)
    doc = PeopleGatorDocument(id='doc', page_layouts=[first, second, no_faces],
                              page_images={first.id: first_pixels, second.id: second_pixels})
    without_embedding = document_parser.DocumentParser(ConfigParser(), 'cpu', tmp_path)
    assert without_embedding.process_document(doc) is doc
    load.assert_not_called()

    ini = ConfigParser()
    ini['ENGINE_Z_FIRST'] = {'METHOD': 'FACE_DETECTION_YOLO'}
    ini.read_dict(config())
    ini['ENGINE_A_LAST'] = {'METHOD': 'FACE_DETECTION_YOLO'}
    ini['PARSE_FOLDER'] = {'PROCESSING_CHECKPOINTS': str(tmp_path / 'checkpoints')}

    def check_stage(expected_calls):
        assert forward.call_count == expected_calls
        return doc

    before = Mock(side_effect=lambda _: check_stage(0))
    after = Mock(side_effect=lambda _: check_stage(2))
    monkeypatch.setattr(document_parser, 'FaceDetectionYoloEngine', Mock(side_effect=[
        Mock(process_document=before), Mock(process_document=after),
    ]))
    parser = document_parser.DocumentParser(ini, 'cpu', tmp_path)
    assert parser.process_document(doc) is doc
    before.assert_called_once_with(doc)
    after.assert_called_once_with(doc)
    load.assert_called_once_with(f'hf-hub:{MODEL}', pretrained=True)

    pixels = forward.call_args_list[0].args[0]
    assert str(pixels.dtype) == 'torch.float32'
    assert pixels[0, :, 50, 50].tolist() == pytest.approx([1, 128 / 127.5 - 1, -1], abs=1e-7)
    assert face.embeddings is original_embeddings
    assert face.embeddings[0] is existing
    assert face.source_region is illustration and not illustration.embeddings
    assert face.face_metadata.left_eye_position is landmarks[0]
    assert face.face_metadata.prompts == [{'prompt': 'original'}]
    assert other_face.face_metadata.page_identity.identity is identity
    assert first.faces[0] is face and second.faces[0] is other_face

    for index, (page, region) in enumerate(((first, face), (second, other_face))):
        result = region.embeddings[-1]
        assert isinstance(result, ObjectEmbedding)
        assert result.id == f'uuid:{region.face_metadata.mods_uuid}'
        assert (result.tag_id, result.page_uuid, result.category, result.source) == (
            region.id, page.id, 'face', None,
        )
        assert len(result.embedding) == 512
        assert all(type(value) is float for value in result.embedding)
        assert np.linalg.norm(result.embedding) == pytest.approx(1)
        assert result.embedding[:2] == pytest.approx([1 / np.sqrt(10), (-1)**index * 3 / np.sqrt(10)])
        info = result.processing_info
        assert isinstance(info, ProcessingInfo)
        assert (info.system, info.version) == (globals.software_name, globals.software_version)
        assert (info.model, info.precision, info.decimal_places) == (MODEL, 'torch.float32', None)
        assert datetime.fromisoformat(info.datetime).utcoffset() is not None

    stage, = (tmp_path / 'checkpoints').glob('*/0002-FaceEmbeddingEngine')
    restored, info = load_checkpoint(stage)
    assert info['next_step'] == 2
    assert restored.page_layouts[0].faces[0].source_region is restored.page_layouts[0].regions[0]
    for original, reloaded in zip(doc.faces, restored.faces, strict=True):
        assert isinstance(reloaded.embeddings[-1], ObjectEmbedding)
        assert reloaded.embeddings == original.embeddings

    parser.engines[1].process_document(doc)
    assert len(face.embeddings) == 3 and face.embeddings[0] is existing
    load.assert_called_once()


@pytest.mark.parametrize('failure', ['missing', 'nonfinite', 'coincident', 'no-transform', 'opencv-error'])
def test_bbox_fallback_skips_empty_crop_and_honors_precision(tmp_path, monkeypatch, inference, failure):
    import cv2
    import numpy as np
    import torch
    from people_gator.core.document_parser import DocumentParser
    from people_gator.core.layout import PeopleGatorDocument, PeopleGatorPageLayout, Position

    _, forward = inference
    landmarks = [Position(x, y) for x, y in REFERENCE]
    if failure == 'missing':
        landmarks[0] = None
    elif failure == 'nonfinite':
        landmarks[0] = Position(float('nan'), 0)
    elif failure == 'coincident':
        landmarks = [Position(10, 10)] * 5
    elif failure == 'no-transform':
        monkeypatch.setattr(cv2, 'estimateAffinePartial2D', Mock(return_value=(None, None)))
    else:
        monkeypatch.setattr(cv2, 'estimateAffinePartial2D', Mock(side_effect=cv2.error('failure')))

    page = PeopleGatorPageLayout('page', (20, 20))
    polygon = np.array([(-3, 0), (6, 0), (6, 6), (-3, 6)])
    face = add_face(page, None, 'visible', polygon, landmarks)
    empty = add_face(page, None, 'outside', polygon - 10, [None] * 5)
    page_pixels = np.zeros((20, 20, 3), dtype=np.uint8)
    page_pixels[:6, :6] = (0, 0, 255)
    doc = PeopleGatorDocument(page_layouts=[page], page_images={page.id: page_pixels})
    parser = DocumentParser(config(PRECISION='bf16', DECIMAL_PLACES='1'), 'cpu', tmp_path)
    assert parser.process_document(doc) is doc
    forward.assert_called_once()
    pixels = forward.call_args.args[0]
    assert pixels.dtype == torch.bfloat16
    assert pixels[0, :, 50, 50].tolist() == [1, -1, -1]
    assert not empty.embeddings
    result, = face.embeddings
    assert result.embedding == [0.3, 0.9] + [0.0] * 510
    assert result.processing_info.precision == 'torch.bfloat16'
    assert result.processing_info.decimal_places == 1


def test_empty_document_and_inference_failure(tmp_path, inference):
    import numpy as np
    from people_gator.core.document_parser import DocumentParser
    from people_gator.core.layout import PeopleGatorDocument, PeopleGatorPageLayout

    _, forward = inference
    parser = DocumentParser(config(), 'cpu', tmp_path)
    empty = PeopleGatorDocument()
    assert parser.process_document(empty) is empty
    forward.assert_not_called()

    page = PeopleGatorPageLayout('page', (20, 20))
    polygon = np.array([(0, 0), (10, 0), (10, 10), (0, 10)])
    face = add_face(page, None, 'face-1', polygon, [None] * 5)
    doc = PeopleGatorDocument(page_layouts=[page],
                              page_images={page.id: np.zeros((20, 20, 3), dtype=np.uint8)})
    forward.side_effect = RuntimeError('model failed')
    with pytest.raises(RuntimeError, match='model failed'):
        parser.process_document(doc)
    forward.assert_called_once()
    assert not face.embeddings
