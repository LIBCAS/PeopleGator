"""Observability and processing regressions using synthetic data and services."""

import configparser
import importlib
import json
import logging
from types import SimpleNamespace
from unittest.mock import Mock

import pytest


@pytest.fixture
def processing(runtime_mode):
    if runtime_mode == "client":
        pytest.skip("Processing stack is outside client-only mode")
    return importlib.import_module("people_gator.core.layout")


@pytest.mark.parametrize("module_name", [
    "user_scripts.parse_folder", "user_scripts.merge_document_entities",
    "processing_api.client", "processing_api.worker",
])
@pytest.mark.parametrize("existing", [False, True])
def test_repeated_logging_setup(module_name, existing, tmp_path, runtime_mode):
    if runtime_mode == "client" and module_name.startswith("user_scripts"):
        pytest.skip("Processing stack is outside client-only mode")
    if runtime_mode == "tool" and module_name.startswith("processing_api"):
        pytest.skip("DocAPI is outside tool-only mode")
    module = importlib.import_module(module_name)
    root = logging.getLogger()
    saved_handlers, saved_level = root.handlers[:], root.level
    root.handlers = []
    if existing:
        root.addHandler(logging.StreamHandler())
    try:
        kwargs = {"log_file_path": str(tmp_path / "worker.log")} if module_name.endswith("worker") else {}
        module.setup_logging("DEBUG", **kwargs)
        handlers = root.handlers[:]
        module.setup_logging("ERROR", **kwargs)
        assert root.handlers == handlers
        assert root.level == logging.ERROR
        assert len(handlers) == (2 if kwargs else 1)
        logging.getLogger(module_name).error("unique-test-record")
        if kwargs:
            assert (tmp_path / "worker.log").read_text().count("unique-test-record") == 1
    finally:
        for handler in root.handlers:
            handler.close()
        root.handlers = saved_handlers
        root.setLevel(saved_level)


def test_document_milestones_and_engine_order(processing, caplog):
    from people_gator.core.document_parser import DocumentParser

    config = configparser.ConfigParser()
    parser = DocumentParser(config, "cpu", ".")
    document = processing.PeopleGatorDocument(id="doc-1")
    calls = []

    class Engine:
        def process_document(self, document):
            calls.append(self)
            return document

    parser.engines = [Engine(), Engine()]
    with caplog.at_level(logging.DEBUG):
        assert parser.process_document(document, import_from_app=True) is document
    assert calls == parser.engines
    assert "doc-1: 0 pages, 2 engines" in caplog.text
    assert "has no pages" in caplog.text
    assert "DB_API is not configured" in caplog.text
    assert "Completed processing document doc-1" in caplog.text
    assert [r.levelno for r in caplog.records if "processing document" in r.message.lower()] == [logging.INFO, logging.INFO]


@pytest.mark.parametrize("count", [0, 1, 3])
@pytest.mark.parametrize("level", [logging.INFO, logging.DEBUG])
def test_detection_preserves_coordinates_and_counts(processing, count, level, caplog):
    import numpy as np
    from people_gator.engines.face_detection import FaceDetectionYoloEngine

    engine = object.__new__(FaceDetectionYoloEngine)
    engine.categories = ["photograph"]
    engine.uuid_service = lambda: "fixed-uuid"
    source = SimpleNamespace(id="photo", category="photograph", get_polygon_bounding_box=lambda: (10, 20, 50, 60))
    empty = SimpleNamespace(id="empty", category="photograph", get_polygon_bounding_box=lambda: (0, 0, 0, 0))
    filtered = SimpleNamespace(id="text", category="text")
    page = processing.PeopleGatorPageLayout(id="P1", page_size=(80, 80))
    page.regions = [source, empty, filtered]
    tensor = lambda data: SimpleNamespace(cpu=lambda: np.array(data))
    result = SimpleNamespace(
        boxes=SimpleNamespace(data=tensor([[1, 2, 9, 10, .8, 0]] * count)),
        keypoints=SimpleNamespace(data=tensor([[[2, 3, 1]] * 5] * count)),
    )
    engine.detect_faces = Mock(return_value=[result])
    with caplog.at_level(level):
        assert engine.process_page(np.zeros((80, 80, 3), dtype=np.uint8), page) is page
    assert len(page.faces) == count
    for face in page.faces:
        assert face.get_polygon_bounding_box() == (11, 22, 19, 30)
        assert face.face_metadata.left_eye_position.to_json() == {"x": 12, "y": 23}
        assert face.source_region is source
    if level == logging.DEBUG:
        assert "P1: 1 eligible regions, 1 empty crops skipped" in caplog.text
        assert f"detected {count} faces" in caplog.text
    else:
        assert not caplog.records


def test_no_eligible_detection_regions(processing, caplog):
    import numpy as np
    from people_gator.engines.face_detection import FaceDetectionYoloEngine

    engine = object.__new__(FaceDetectionYoloEngine)
    engine.categories = None
    engine.detect_faces = Mock()
    page = processing.PeopleGatorPageLayout(id="empty-page")
    with caplog.at_level(logging.DEBUG):
        assert engine.process_page(np.zeros((5, 5, 3)), page) is page
    engine.detect_faces.assert_not_called()
    assert "empty-page: no eligible nonempty regions" in caplog.text


@pytest.mark.parametrize("failure", ["http", "model", "json"])
def test_database_failures_are_safe(processing, caplog, failure):
    from people_gator.core.db import DatabaseApiService

    secret = "secret-token-personal-payload"
    service = object.__new__(DatabaseApiService)
    service.api_url = "https://example.invalid"
    response = Mock(status_code=503 if failure == "http" else 200, text=secret)
    response.json.return_value = {"private": secret}
    service.connector = Mock()
    service.connector.get.return_value = response
    model = Mock(side_effect=ValueError(secret)) if failure == "model" else None
    with caplog.at_level(logging.DEBUG):
        if failure == "json":
            response.json.side_effect = ValueError(secret)
            with pytest.raises(ValueError, match=secret):
                service.search_entities(secret)
        else:
            assert service.search_entities(secret, response_model=model) is None
    assert secret not in caplog.text
    assert "Database" in caplog.text
    assert any(r.levelno >= logging.WARNING for r in caplog.records)


@pytest.mark.parametrize("failure", ["network", "json", "schema"])
def test_llm_failures_are_safe_and_keep_retry_semantics(processing, monkeypatch, caplog, failure):
    from people_gator.engines import llm

    secret = "secret-person-and-api-key"
    request = Mock()
    if failure == "network":
        request.side_effect = RuntimeError(secret)
    else:
        request.return_value = SimpleNamespace(output_text=secret if failure == "json" else '{"private": "' + secret + '"}')
    monkeypatch.setattr(llm, "OpenAI", Mock(return_value=SimpleNamespace(responses=SimpleNamespace(create=request))))
    schema = {"type": "object", "required": ["missing"]} if failure == "schema" else None
    with caplog.at_level(logging.DEBUG):
        result = llm.LLMPrompter._send_request("https://example.invalid", secret, {}, 2, schema)
    # A decoded dictionary survives schema failure in the existing implementation.
    assert result == ({"private": secret} if failure == "schema" else None)
    assert request.call_count == 2
    assert secret not in caplog.text
    assert "exhausted 2 attempts" in caplog.text
    assert "LLM request completed" not in caplog.text


def test_llm_success_after_retry(processing, monkeypatch, caplog):
    from people_gator.engines import llm

    request = Mock(side_effect=[RuntimeError("private"), SimpleNamespace(output_text='```json\n{"ok": true}\n```')])
    monkeypatch.setattr(llm, "OpenAI", Mock(return_value=SimpleNamespace(responses=SimpleNamespace(create=request))))
    with caplog.at_level(logging.DEBUG):
        assert llm.LLMPrompter._send_request("https://example.invalid", "secret", {}, 2, None) == {"ok": True}
    assert "LLM request completed" in caplog.text
    assert "private" not in caplog.text


@pytest.mark.parametrize("count", [0, 1, 3])
def test_matching_candidates_preserve_identity(processing, count, caplog):
    from people_gator.engines.entity_matching import EntityMatchingEngine

    face = processing.PeopleGatorFaceRegionLayout("face1", None, None, None)
    identity = processing.PeopleGatorIdentity("private-name", None)
    face.face_metadata = SimpleNamespace(identity_name="private-name", page_identity=SimpleNamespace(identity=identity))
    page = SimpleNamespace(id="P1", regions=[face])
    engine = object.__new__(EntityMatchingEngine)
    candidates = [{"entity_id": str(i)} for i in range(count)]
    engine.db_api_service = Mock()
    engine.db_api_service.search_entities.return_value = {"items": candidates}
    engine.db_api_service.create_entity.return_value = {"entity_id": "new"}
    engine.match_entity = Mock(return_value=candidates)
    with caplog.at_level(logging.DEBUG):
        assert engine.process_page(page) is page
    assert identity.peoplegator_id == ("new" if count == 0 else "0" if count == 1 else None)
    assert f"{count} candidate entities" in caplog.text
    assert "private-name" not in caplog.text


def test_assignment_updates_and_missing_results(processing, caplog):
    from people_gator.engines.face_assignment import (
        LLMFaceAssignmentEngine, LLMBatchFaceAssignmentEngine,
        FaceAssignmentData, FaceAssignmentResult, BatchFaceAssignmentData,
        BatchFaceAssignmentResult, BatchFaceAssignmentResultItem,
    )

    identity = processing.PeopleGatorIdentity("before", None)
    face = SimpleNamespace(id="f1", face_metadata=SimpleNamespace(page_identity=SimpleNamespace(identity=identity)))
    page = SimpleNamespace(id="P1")
    single = object.__new__(LLMFaceAssignmentEngine)
    data = FaceAssignmentData(face, None, (10, 20), None)
    with caplog.at_level(logging.DEBUG):
        assert single.update_layout(page, [data]) is page
    assert identity.name == "before"
    data.result = FaceAssignmentResult(name_normalized="after", name_in_text=None)
    single.update_layout(page, [data])
    assert identity.name == "after"
    batch = object.__new__(LLMBatchFaceAssignmentEngine)
    data = BatchFaceAssignmentData(faces=[{"id": 0, "coordinates": (10, 20)}], face_regions=[face])
    batch.update_layout([data])
    assert identity.name == "after"
    data.result = BatchFaceAssignmentResult(faces=[BatchFaceAssignmentResultItem(id=0, coordinates=[10, 20], name_normalized="batch", name_in_text=None)])
    batch.update_layout([data])
    assert identity.name == "batch"
    assert "after" not in caplog.text and "before" not in caplog.text


@pytest.mark.parametrize("exit_status", [0, 7])
def test_worker_completion_keeps_response_contract(exit_status, monkeypatch, caplog, runtime_mode):
    if runtime_mode == "tool":
        pytest.skip("DocAPI is outside tool-only mode")
    from processing_api import worker

    process = Mock(returncode=exit_status)
    process.communicate.return_value = ("private-stdout", "secret-token")
    monkeypatch.setattr(worker.subprocess, "Popen", Mock(return_value=process))
    instance = object.__new__(worker.PeopleGatorWorker)
    instance.device = "cpu"
    instance.gpu_id = None
    job = SimpleNamespace(id="job1", alto_required=False, page_required=False, meta_json_required=False, engine_settings={})
    with caplog.at_level(logging.DEBUG):
        result = instance.process_job(job, None, "images", "results", engine_dir="engine")
    expected = worker.WorkerResponse.ok() if exit_status == 0 else worker.WorkerResponse.fail(
        f"peoplegator processing for job job1 failed with return code {exit_status}"
    )
    assert result == expected
    assert "job1" in caplog.text
    assert (f"exit status {exit_status}" if exit_status == 0 else f"return code {exit_status}") in caplog.text
    assert "private-stdout" not in caplog.text and "secret-token" not in caplog.text
    assert any(r.levelno == (logging.INFO if exit_status == 0 else logging.ERROR) and ("exit status" in r.message or "return code" in r.message) for r in caplog.records)


def test_worker_arguments_never_logged(monkeypatch, caplog, runtime_mode):
    if runtime_mode == "tool":
        pytest.skip("DocAPI is outside tool-only mode")
    from processing_api import worker

    monkeypatch.setattr("sys.argv", ["worker", "--api-key", "secret-token"])
    with caplog.at_level(logging.DEBUG):
        assert worker.parse_arguments().api_key == "secret-token"
    assert "secret-token" not in caplog.text


def test_populated_xml_is_independent_of_logging_level(processing, caplog):
    import numpy as np
    from lxml import etree as ET
    from pero_ocr.core.layout import ALTOVersion

    identity = processing.PeopleGatorIdentity("Synthetic Person", "entity-1")
    page_identity = processing.PeopleGatorPageIdentity("person_001", "MODS_PERSON_0001", identity, creation_date_time="2026-01-01T00:00:00Z")
    metadata = processing.PeopleGatorFaceMetadata(
        "face_001", "MODS_FACE_0001", page_identity,
        *[processing.Position(12, 23) for _ in range(5)],
        creation_date_time="2026-01-01T00:00:00Z",
    )
    face = processing.PeopleGatorFaceRegionLayout(
        "face_001", np.array([[10, 20], [10, 40], [30, 40], [30, 20], [10, 20]]),
        metadata, None, category="face", detection_confidence=.8,
    )
    outputs = []
    for level in (logging.WARNING, logging.DEBUG):
        with caplog.at_level(level):
            page = ET.Element("Page")
            face.to_pagexml(page)
            root = ET.Element("alto", nsmap={None: "http://www.loc.gov/standards/alto/ns-v4#"})
            layout = ET.SubElement(root, "Layout")
            alto_page = ET.SubElement(layout, "Page", ID="P1")
            print_space = ET.SubElement(alto_page, "PrintSpace")
            coords = face.to_altoxml(print_space, None, 0, (0, 0, 0, 0), ALTOVersion.ALTO_v4_4)
            outputs.append((ET.tostring(page), ET.tostring(root), coords))
    assert outputs[0] == outputs[1]
    page = ET.fromstring(outputs[0][0])
    assert page.find("ImageRegion/Coords").get("points") == "10,20 10,40 30,40 30,20 10,20"
    root = ET.fromstring(outputs[0][1])
    assert root.xpath("//*[local-name()='ComposedBlock']/@TAGREFS") == ["face_001"]
    assert root.xpath("//*[local-name()='nameIdentifier']/text()") == ["uuid:entity-1"]
    assert root.xpath("//*[local-name()='points']/@x") == ["12.00"] * 5
    assert outputs[0][2] == (40, 30, 0, 0)


def test_import_export_keeps_app_contract(processing, monkeypatch, caplog):
    from people_gator.core import document_parser
    import numpy as np

    image = np.zeros((10, 10, 3), dtype=np.uint8)
    page = processing.PeopleGatorPageLayout(id="P1", page_size=(10, 10))
    document = processing.PeopleGatorDocument(
        id="doc1", name="private-document-title", library="library1",
        page_layouts=[page], page_images={"P1": image},
    )
    service = Mock()
    service.get_document_info.return_value = {"source_id": "document-source"}
    service.get_page_info.return_value = {"source_id": "page-source"}
    service.get_faces_for_page.return_value = {"items": [{"entity_id": None, "detection_id": "face1"}]}
    imported = processing.PeopleGatorFaceRegionLayout("face1", None, None, None)
    factory = Mock(return_value=imported)
    monkeypatch.setattr(processing.PeopleGatorFaceRegionLayout, "from_app_dict", factory)
    with caplog.at_level(logging.DEBUG):
        assert document_parser.import_document(document, service) is document
        assert document_parser.export_document(document, service) is None
    assert page.regions == [imported]
    factory.assert_called_once_with({"entity_id": None, "detection_id": "face1"}, None, page)
    service.create_face.assert_called_once_with(imported, "page-source")
    assert service.put_page_image.call_args.args[0] is image
    service.put_page_layout.assert_called_once_with(page.to_app_dict(), "page-source")
    assert "private-document-title" not in caplog.text
    assert "Finished import operations for document doc1" in caplog.text
    assert "Finished export operations for document doc1" in caplog.text


def test_authentication_failure_does_not_log_response(processing, monkeypatch, caplog):
    from people_gator.core.connector import Connector, AuthenticationError

    connector = Connector("private-user", "secret-password", "login", "refresh", [], login=False)
    connector.session = Mock()
    connector.session.post.return_value = SimpleNamespace(status_code=403, text="secret-response")
    with caplog.at_level(logging.DEBUG), pytest.raises(AuthenticationError):
        connector.login()
    assert "HTTP 403" in caplog.text
    assert not any(secret in caplog.text for secret in ("private-user", "secret-password", "secret-response"))


def test_single_assignment_request_contract(processing, caplog, tmp_path):
    from people_gator.engines.face_assignment import LLMFaceAssignmentEngine, FaceAssignmentData, FaceAssignmentResult

    identity = processing.PeopleGatorIdentity("before", None)
    face = SimpleNamespace(id="f1", face_metadata=SimpleNamespace(page_identity=SimpleNamespace(identity=identity)))
    data = FaceAssignmentData(face, None, (10, 20), None, context_text="private OCR")
    page = SimpleNamespace(id="P1")
    prompt = tmp_path / 'single-prompt.json'
    prompt.write_text(json.dumps({'user': '{{ face_coordinates }} {{ context_text }} {{ caption_text }}'}))
    config = configparser.ConfigParser()
    config.read_dict({'engine': {'PROMPT_TEMPLATE_PATH': str(prompt)}})
    engine = LLMFaceAssignmentEngine(config['engine'], 'cpu', str(tmp_path))
    engine.prepare_face_data = Mock(return_value=[data])
    engine.llm_prompter = Mock(return_value=(None, []))
    with caplog.at_level(logging.DEBUG):
        assert engine.process_page(None, page) is page
    assert identity.name == "before"
    result = FaceAssignmentResult(name_normalized="after", name_in_text=None)
    engine.llm_prompter.return_value = (result, [])
    assert engine.process_page(None, page) is page
    assert identity.name == "after"
    assert engine.llm_prompter.call_args.kwargs["data"]["context_text"] == "private OCR"
    # The existing caller's unpacking error is outside this maintenance issue.
    engine.llm_prompter.return_value = None
    with pytest.raises(TypeError):
        engine.process_page(None, page)
    assert "private OCR" not in caplog.text


@pytest.mark.parametrize("parallel", [False, True])
def test_batch_assignment_page_requests(processing, parallel, caplog, tmp_path):
    from people_gator.engines.face_assignment import LLMBatchFaceAssignmentEngine, BatchFaceAssignmentData, BatchFaceAssignmentResult, BatchFaceAssignmentResultItem
    from people_gator.enums import ProcessingMode

    identity = processing.PeopleGatorIdentity("before", None)
    face = SimpleNamespace(id="f1", face_metadata=SimpleNamespace(page_identity=SimpleNamespace(identity=identity)))
    data = BatchFaceAssignmentData(faces=[{"id": 0, "coordinates": (10, 20)}], face_regions=[face])
    page = SimpleNamespace(id="P1")
    prompt = tmp_path / 'batch-prompt.json'
    prompt.write_text(json.dumps({'user': '{{ faces }} {{ context_text }} {{ caption_text }}'}))
    config = configparser.ConfigParser()
    config.read_dict({'engine': {'PROMPT_TEMPLATE_PATH': str(prompt)}})
    engine = LLMBatchFaceAssignmentEngine(config['engine'], 'cpu', str(tmp_path))
    engine.processing_mode = ProcessingMode.PAGE_PARALLEL if parallel else ProcessingMode.SEQUENTIAL
    engine.prepare_face_data = Mock(return_value=[data])
    result = BatchFaceAssignmentResult(faces=[BatchFaceAssignmentResultItem(id=0, coordinates=[10, 20], name_normalized="after", name_in_text=None)])
    engine.llm_prompter = Mock()
    engine.llm_prompter.process.return_value = result
    engine.llm_prompter.process_parallel.return_value = [result]
    with caplog.at_level(logging.DEBUG):
        assert engine.process_page(None, page) is page
    assert identity.name == "after"
    assert "P1: prepared 1 LLM assignment requests" in caplog.text
    assert "after" not in caplog.text


def test_database_lookup_not_found_is_debug(processing, caplog):
    from people_gator.core.db import DatabaseApiService

    service = object.__new__(DatabaseApiService)
    service.api_url = "https://example.invalid"
    service.connector = Mock()
    service.connector.get.return_value = SimpleNamespace(status_code=404)
    with caplog.at_level(logging.DEBUG):
        assert service.get_document_info("doc1", "library1") is None
    assert "get_document_info failed (HTTP 404)" in caplog.text
    assert all(record.levelno == logging.DEBUG for record in caplog.records)


def test_http_transport_failure_propagates_without_payload(processing, caplog):
    import requests
    from people_gator.core.connector import Connector

    connector = Connector("user", "password", "login", "refresh", [], login=False)
    connector.session = Mock()
    failure = requests.ConnectionError("secret-url-and-token")
    connector.session.get.side_effect = failure
    with caplog.at_level(logging.DEBUG), pytest.raises(requests.ConnectionError) as caught:
        connector.get("https://example.invalid")
    assert caught.value is failure
    assert "HTTP operation get failed (ConnectionError)" in caplog.text
    assert "secret-url-and-token" not in caplog.text


def test_llm_last_invalid_response_is_not_logged_as_success(processing, monkeypatch, caplog):
    from people_gator.engines import llm

    request = Mock(side_effect=[SimpleNamespace(output_text="{}"), SimpleNamespace(output_text='{"unexpected": true}')])
    monkeypatch.setattr(llm, "OpenAI", Mock(return_value=SimpleNamespace(responses=SimpleNamespace(create=request))))
    with caplog.at_level(logging.DEBUG):
        result = llm.LLMPrompter._send_request("https://example.invalid", "secret", {}, 2, {"type": "object", "additionalProperties": False})
    assert result == {"unexpected": True}  # Preserve the existing return contract.
    assert "exhausted 2 attempts" in caplog.text
    assert "LLM request completed" not in caplog.text


@pytest.mark.parametrize("page_count", [0, 3, 25])
def test_entity_merge_progress_at_info(processing, monkeypatch, caplog, page_count):
    from user_scripts import merge_document_entities as merge

    args = SimpleNamespace(
        config="config.ini", prompt="prompt.json", metadata="metadata.json",
        logging_level="INFO", api_url="https://example.invalid", api_key="secret-key",
        model="test-model", reasoning_effort="low", max_output_tokens=1000,
    )
    monkeypatch.setattr(merge, "parse_arguments", lambda: args)
    monkeypatch.setattr(merge, "setup_logging", Mock())
    monkeypatch.setattr(merge, "load_config", Mock(return_value={"DB_API": {}}))
    monkeypatch.setattr(merge, "load_prompt", Mock(return_value={"system": "", "user": ""}))
    monkeypatch.setattr(merge, "load_metadata", Mock(return_value={"document": {
        "id": "doc1", "name": "private-title", "library": "library1",
    }}))
    service = Mock()
    service.get_document_pages.return_value = {"items": [{"source_id": f"page-{i}"} for i in range(page_count)]}
    service.get_entities_for_page.return_value = {"items": [{"entity_id": "entity1"}, {"entity_id": "entity2"}]}
    monkeypatch.setattr(merge, "DatabaseApiService", Mock(return_value=service))
    monkeypatch.setattr(merge, "LLMPrompter", Mock())
    monkeypatch.setattr(merge, "evaluate_page_entities", Mock(return_value=SimpleNamespace(groups=[
        SimpleNamespace(entity_ids=[0, 1], long_description="private-description", short_description="private-name"),
    ])))
    with caplog.at_level(logging.INFO):
        assert merge.main() == 0
    assert f"Document doc1: merging entities across {page_count} pages" in caplog.text
    assert f"Document doc1 entity merging completed ({page_count} pages)" in caplog.text
    progress = [r.message for r in caplog.records if "processed" in r.message]
    assert len(progress) <= 10
    if page_count:
        assert progress[-1] == f"Document doc1: processed {page_count}/{page_count} pages"
    else:
        assert not progress
    assert service.merge_entities.call_count == page_count
    if page_count:
        service.merge_entities.assert_called_with(
            "entity1", ["entity2"], description="private-description", short_description="private-name",
        )
    for private in ("secret-key", "private-title", "private-name", "private-description", "page-0"):
        assert private not in caplog.text
