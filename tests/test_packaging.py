"""Distribution checks requiring only the test extra, with no model or services."""

import ast
import configparser
from email.parser import BytesParser
import json
import os
from pathlib import Path
import subprocess
import sys
import tarfile
import venv
import zipfile

import pytest
from packaging.requirements import Requirement
from packaging.utils import canonicalize_name

try:
    import tomllib
except ModuleNotFoundError:  # Python 3.10
    import tomli as tomllib


ROOT = Path(__file__).resolve().parents[1]
SOURCE_DIRS = ("people_gator", "processing_api", "user_scripts")
CONFIG = tomllib.loads((ROOT / "pyproject.toml").read_text())


def run(*args, cwd):
    result = subprocess.run(args, cwd=cwd, text=True, capture_output=True)
    assert result.returncode == 0, result.stdout + result.stderr
    return result.stdout


def test_metadata_and_direct_dependencies():
    project = CONFIG["project"]
    metadata = {}
    exec((ROOT / "people_gator/globals.py").read_text(), metadata)
    assert project["version"] == metadata["software_version"]
    assert project["readme"] == "README.md"
    assert (ROOT / project["license"]["file"]).is_file()

    # Catch missing declarations when a new third-party import is added.
    imports_to_distributions = {
        "anno_page": "anno-page", "pero_ocr": "pero-ocr", "cv2": "opencv-python",
        "numpy": "numpy", "lxml": "lxml", "shapely": "shapely",
        "torch": "torch", "ultralytics": "ultralytics", "pydantic": "pydantic",
        "openai": "openai", "jinja2": "jinja2", "jsonschema": "jsonschema",
        "requests": "requests", "safe_gpu": "safe-gpu", "rapidfuzz": "rapidfuzz", "scipy": "scipy",
        "doc_api": "doc-api", "doc_worker": "doc-api", "doc_client": "doc-api",
    }
    base = {canonicalize_name(Requirement(d).name) for d in project["dependencies"]}
    assert not base
    extras = project["optional-dependencies"]
    groups = {extra: {canonicalize_name(Requirement(d).name) for d in dependencies}
              for extra, dependencies in extras.items()}
    assert groups["client"] == groups["api"] == groups["worker"] == {"doc-api"}
    assert "doc-api" not in groups["tool"]
    assert set(extras["full"]) == set(extras["tool"]) | set(extras["client"])
    for directory in SOURCE_DIRS:
        declared = groups["worker"] if directory == "processing_api" else groups["tool"]
        for path in (ROOT / directory).rglob("*.py"):
            for node in ast.walk(ast.parse(path.read_text())):
                if isinstance(node, ast.Import):
                    modules = [alias.name.split(".")[0] for alias in node.names]
                elif isinstance(node, ast.ImportFrom) and node.module and not node.level:
                    modules = [node.module.split(".")[0]]
                else:
                    continue
                for module in modules:
                    if module in sys.stdlib_module_names or module in SOURCE_DIRS:
                        continue
                    assert module in imports_to_distributions, (path, module)
                    assert imports_to_distributions[module] in declared, (path, module)

    groups = {"base": project["dependencies"], **project["optional-dependencies"]}
    for extra, dependencies in groups.items():
        for dependency in dependencies:
            requirement = Requirement(dependency)
            if requirement.url:
                revision = requirement.url.rsplit("@", 1)[-1]
                assert len(revision) == 40 and all(c in "0123456789abcdef" for c in revision)


@pytest.fixture(scope="module")
def wheel(tmp_path_factory):
    dist = tmp_path_factory.mktemp("dist")
    # The default build command builds the wheel from the sdist, checking both.
    run(sys.executable, "-m", "build", "--no-isolation", "--outdir", str(dist), str(ROOT), cwd=dist)
    sdist, = dist.glob("*.tar.gz")
    with tarfile.open(sdist) as archive:
        assert any(name.endswith("/pyproject.toml") for name in archive.getnames())
        assert any(name.endswith("/LICENSE") for name in archive.getnames())
    wheel_path, = dist.glob("*.whl")
    return wheel_path


def test_wheel_contents_and_metadata(wheel):
    with zipfile.ZipFile(wheel) as archive:
        files = set(archive.namelist())
        for directory in SOURCE_DIRS:
            for path in (ROOT / directory).rglob("*.py"):
                assert path.relative_to(ROOT).as_posix() in files
        assert not any(name.startswith(("tests/", "docs/")) for name in files)
        metadata_path, = (name for name in files if name.endswith(".dist-info/METADATA"))
        metadata = BytesParser().parsebytes(archive.read(metadata_path))
        assert metadata["Name"] == CONFIG["project"]["name"]
        assert metadata["Requires-Python"] == CONFIG["project"]["requires-python"]
        assert set(metadata.get_all("Provides-Extra")) == set(CONFIG["project"]["optional-dependencies"])
        for dependency in metadata.get_all("Requires-Dist"):
            requirement = Requirement(dependency)
            assert requirement.marker is not None
            assert not requirement.marker.evaluate({"extra": ""})
        entries_path, = (name for name in files if name.endswith(".dist-info/entry_points.txt"))
        entries = configparser.ConfigParser()
        entries.read_string(archive.read(entries_path).decode())
        assert dict(entries["console_scripts"]) == CONFIG["project"]["scripts"]
        for target in entries["console_scripts"].values():
            module, function = target.split(":")
            tree = ast.parse(archive.read(module.replace(".", "/") + ".py"))
            assert any(isinstance(node, ast.FunctionDef) and node.name == function for node in tree.body)


def test_clean_wheel_install(wheel, tmp_path):
    environment = tmp_path / "venv"
    venv.EnvBuilder(with_pip=True).create(environment)
    scripts = environment / ("Scripts" if os.name == "nt" else "bin")
    python = scripts / ("python.exe" if os.name == "nt" else "python")
    run(str(python), "-m", "pip", "install", "--no-deps", "--no-index", str(wheel), cwd=tmp_path)
    # Run away from the checkout so namespace-package discovery errors surface.
    output = run(str(python), "-I", "-c", """
import importlib.metadata as metadata
from people_gator.globals import software_version
from people_gator.core.services import UuidService
from people_gator.enums import ProcessingMode
import json
distribution = metadata.distribution('people-gator')
assert distribution.version == software_version
print(json.dumps({entry.name: entry.value for entry in distribution.entry_points}))
""", cwd=tmp_path)
    assert json.loads(output) == CONFIG["project"]["scripts"]
    for command in CONFIG["project"]["scripts"]:
        assert (scripts / (command + (".exe" if os.name == "nt" else ""))).is_file()
