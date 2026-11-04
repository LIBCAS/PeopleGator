"""Smoke checks for an installed package; no model downloads or live services."""

import importlib
from pathlib import Path
import subprocess
import sys

import pytest


def command(name, *arguments, cwd):
    executable = Path(sys.executable).parent / name
    result = subprocess.run([str(executable), *arguments], cwd=cwd, text=True, capture_output=True)
    assert result.returncode == 0, result.stdout + result.stderr
    return result.stdout


def test_installed_core_imports(tmp_path):
    result = subprocess.run([sys.executable, "-I", "-c", """
import importlib
import importlib.util
for module in (
    'people_gator.core.layout', 'people_gator.core.document_parser',
    'people_gator.core.db', 'people_gator.engines.face_detection',
    'people_gator.engines.face_assignment', 'people_gator.engines.entity_matching',
    'people_gator.engines.llm', 'user_scripts.parse_folder',
    'user_scripts.merge_document_entities',
):
    importlib.import_module(module)
if importlib.util.find_spec('doc_api') is not None:
    for module in ('processing_api.api', 'processing_api.client', 'processing_api.worker'):
        importlib.import_module(module)
"""], cwd=tmp_path, text=True, capture_output=True)
    assert result.returncode == 0, result.stdout + result.stderr


@pytest.mark.parametrize(("name", "options"), [
    ("peoplegator", ["--config", "--input-alto-path", "--input-xml-path", "--device"]),
    ("peoplegator_merge_document_entities", ["--metadata", "--prompt", "--model"]),
    ("peoplegator_client", ["--api-url", "--alto-xmls", "--page-xmls"]),
    ("peoplegator_worker", ["--api-url", "--engines-dir", "--device"]),
])
def test_installed_cli_help(name, options, tmp_path):
    if name in {"peoplegator_client", "peoplegator_worker"}:
        pytest.importorskip("doc_api")
    output = command(name, "--help", cwd=tmp_path)
    for option in options:
        assert option in output


def test_api_wrapper(monkeypatch):
    pytest.importorskip("doc_api")
    api = importlib.import_module("processing_api.api")
    calls = []
    monkeypatch.delenv("SERVER_NAME", raising=False)
    monkeypatch.setenv("APP_PORT", "8123")
    # main adds defaults for these keys; restore the environment after the test.
    for key in ("SERVER_NAME", "APP_VERSION", "APP_HOST", "PRODUCTION", "KEY_PREFIX", "BASE_DIR"):
        monkeypatch.setenv(key, "")
    monkeypatch.setattr(api, "doc_api_main", lambda: calls.append(True))
    assert api.main() == 0
    import os
    assert os.environ["SERVER_NAME"] == "PeopleGatorAPI"
    assert os.environ["APP_PORT"] == "8123"
    assert calls == [True]


def test_installed_model_free_processing(tmp_path):
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
    command("peoplegator", "--config", str(config), "--input-image-path", str(images),
            "--input-xml-path", str(pages), "--output-xml-path", str(output_page),
            "--output-alto-path", str(output_alto), "--device", "cpu", cwd=tmp_path)
    page = etree.parse(str(output_page / "P0001.xml"))
    assert page.xpath("//*[local-name()='Unicode']/text()") == ["Test page"]
    assert page.xpath("//*[local-name()='Page']/@imageWidth") == ["64"]
    alto = etree.parse(str(output_alto / "P0001.xml"))
    assert alto.xpath("//*[local-name()='String']/@CONTENT") == ["Test", "page"]
    assert alto.xpath("//*[local-name()='Page']/@WIDTH") == ["64"]
