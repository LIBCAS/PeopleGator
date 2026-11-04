"""Smoke checks for an installed package; no model downloads or live services."""

import importlib
import os
from pathlib import Path
import subprocess
import sys

import pytest


def command(name, *arguments, cwd):
    executable = Path(sys.executable).parent / (name + (".exe" if os.name == "nt" else ""))
    result = subprocess.run([str(executable), *arguments], cwd=cwd, text=True, capture_output=True)
    assert result.returncode == 0, result.stdout + result.stderr
    return result.stdout


def test_installed_imports(tmp_path, runtime_mode):
    result = subprocess.run([sys.executable, "-I", "-c", """
import importlib
import importlib.util
import sys
mode = sys.argv[1]
processing_modules = (
    'people_gator.core.layout', 'people_gator.core.document_parser',
    'people_gator.core.db', 'people_gator.engines.face_detection',
    'people_gator.engines.face_assignment', 'people_gator.engines.entity_matching',
    'people_gator.engines.llm', 'user_scripts.parse_folder',
    'user_scripts.merge_document_entities',
)
api_modules = ('processing_api.api', 'processing_api.client', 'processing_api.worker')
modules = processing_modules if mode == 'tool' else api_modules if mode == 'client' else processing_modules + api_modules
for module in modules:
    importlib.import_module(module)
if mode == 'client':
    for module in ('torch', 'ultralytics', 'anno_page', 'pero_ocr'):
        assert importlib.util.find_spec(module) is None, module + ' must be absent in the client-only environment'
""", runtime_mode], cwd=tmp_path, text=True, capture_output=True)
    assert result.returncode == 0, result.stdout + result.stderr


@pytest.mark.parametrize(("name", "options"), [
    ("peoplegator", ["--config", "--input-alto-path", "--input-xml-path", "--device"]),
    ("peoplegator_merge_document_entities", ["--metadata", "--prompt", "--model"]),
    ("peoplegator_client", ["--api-url", "--alto-xmls", "--page-xmls"]),
    ("peoplegator_worker", ["--api-url", "--engines-dir", "--device", "--gpu-id"]),
])
def test_installed_cli_help(name, options, tmp_path, runtime_mode):
    if runtime_mode == "tool" and name in {"peoplegator_client", "peoplegator_worker"}:
        pytest.skip("DocAPI commands are outside the tool installation mode")
    if runtime_mode == "client" and name != "peoplegator_client":
        pytest.skip("Only client command is exercised in the client installation mode")
    output = command(name, "--help", cwd=tmp_path)
    for option in options:
        assert option in output


def test_installed_client_list_engines(tmp_path, runtime_mode):
    if runtime_mode == "tool":
        pytest.skip("DocAPI is outside the tool installation mode")
    result = subprocess.run([sys.executable, "-I", "-c", """
from importlib.metadata import distribution
from types import SimpleNamespace
from unittest.mock import patch
import importlib
import sys
entry, = (e for e in distribution('people-gator').entry_points if e.name == 'peoplegator_client')
main = entry.load()
module = importlib.import_module(main.__module__)
sys.argv = ['peoplegator_client', '--api-url', 'https://example.invalid', '--api-key', 'test', '--list-engines']
with patch.object(module, 'Adapter') as adapter:
    adapter.return_value.get_engines.return_value = SimpleNamespace(data=[])
    assert main() == 0
    adapter.return_value.get_engines.assert_called_once_with()
"""], cwd=tmp_path, text=True, capture_output=True)
    assert result.returncode == 0, result.stdout + result.stderr
    assert "No available engines." in result.stderr


def test_api_wrapper(monkeypatch, runtime_mode):
    if runtime_mode == "tool":
        pytest.skip("DocAPI is outside the tool installation mode")
    api = importlib.import_module("processing_api.api")
    calls = []
    monkeypatch.delenv("SERVER_NAME", raising=False)
    monkeypatch.setenv("APP_PORT", "8123")
    # main adds defaults for these keys; restore the environment after the test.
    for key in ("SERVER_NAME", "APP_VERSION", "APP_HOST", "PRODUCTION", "KEY_PREFIX", "BASE_DIR"):
        monkeypatch.setenv(key, "")
    monkeypatch.setattr(api, "doc_api_main", lambda: calls.append(True))
    assert api.main() == 0
    assert os.environ["SERVER_NAME"] == "PeopleGatorAPI"
    assert os.environ["APP_PORT"] == "8123"
    assert calls == [True]


@pytest.mark.parametrize("runner", ["cli", "worker"])
def test_installed_model_free_processing(tmp_path, runtime_mode, runner):
    if runtime_mode == "client":
        pytest.skip("Processing is outside the client installation mode")
    if runtime_mode == "tool" and runner == "worker":
        pytest.skip("DocAPI is outside the tool installation mode")
    import cv2
    import numpy as np
    from lxml import etree

    images = tmp_path / "images"
    pages = tmp_path / "pages"
    images.mkdir()
    pages.mkdir()
    assert cv2.imwrite(str(images / "P0001.jpg"), np.full((64, 64, 3), 255, dtype=np.uint8))
    (pages / "P0001.xml").write_text('''<?xml version="1.0"?>
<PcGts xmlns="http://schema.primaresearch.org/PAGE/gts/pagecontent/2019-07-15">
  <Metadata><Creator>packaging smoke test</Creator>
    <Created>2026-01-01T00:00:00Z</Created><LastChange>2026-01-01T00:00:00Z</LastChange>
  </Metadata>
  <Page imageFilename="P0001.jpg" imageWidth="64" imageHeight="64">
    <TextRegion id="r1"><Coords points="0,0 63,0 63,63 0,63"/>
      <TextLine id="l1"><Coords points="1,1 60,1 60,20 1,20"/>
        <Baseline points="1,18 60,18"/>
        <TextEquiv><Unicode>Test page</Unicode></TextEquiv>
      </TextLine>
    </TextRegion>
  </Page>
</PcGts>''')
    config = tmp_path / "config.ini"
    config.write_text("[PARSE_FOLDER]\n")
    output_page = tmp_path / "output-page"
    output_alto = tmp_path / "output-alto"
    if runner == "cli":
        command("peoplegator", "--config", str(config), "--input-image-path", str(images),
                "--input-xml-path", str(pages), "--output-xml-path", str(output_page),
                "--output-alto-path", str(output_alto), "--device", "cpu", cwd=tmp_path)
    else:
        # Exercise the installed worker and its real processing subprocess away from the checkout.
        result = subprocess.run([sys.executable, "-I", "-c", """
import logging
from pathlib import Path
from types import SimpleNamespace
from doc_api.connector import Connector
from processing_api.worker import PeopleGatorWorker
logging.basicConfig(level=logging.INFO)
root = Path.cwd()
worker = PeopleGatorWorker('https://example.invalid', Connector('test'), base_dir=str(root / 'worker'))
job = SimpleNamespace(alto_required=False, page_required=True, meta_json_required=False,
                      engine_settings={'outputs': {'alto': True, 'page': True, 'renders': True}})
response = worker.process_job(job, None, str(root / 'images'), str(root / 'results'),
                              page_xml_dir=str(root / 'pages'), engine_dir=str(root))
assert response.success
"""], cwd=tmp_path, text=True, capture_output=True,
            env={**os.environ, "PATH": str(Path(sys.executable).parent) + os.pathsep + os.environ.get("PATH", "")})
        assert result.returncode == 0, result.stdout + result.stderr
        output_page = tmp_path / "results" / "page"
        output_alto = tmp_path / "results" / "alto"
        rendered = cv2.imread(str(tmp_path / "results" / "renders" / "P0001.jpg"))
        assert rendered is not None and rendered.shape == (64, 64, 3)
    page = etree.parse(str(output_page / "P0001.xml"))
    assert page.xpath("//*[local-name()='Unicode']/text()") == ["Test page"]
    assert page.xpath("//*[local-name()='Page']/@imageWidth") == ["64"]
    alto = etree.parse(str(output_alto / "P0001.xml"))
    assert alto.xpath("//*[local-name()='String']/@CONTENT") == ["Test", "page"]
    assert alto.xpath("//*[local-name()='Page']/@WIDTH") == ["64"]
