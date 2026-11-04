"""Worker command regression checks, without a DocAPI server or GPU."""

import importlib
import itertools
import logging
import os
import sys
from types import SimpleNamespace
from unittest.mock import Mock

import pytest


@pytest.fixture
def worker_module(runtime_mode):
    if runtime_mode == "tool":
        pytest.skip("DocAPI is outside the tool installation mode")
    return importlib.import_module("processing_api.worker")


@pytest.fixture
def invoke(worker_module, monkeypatch, tmp_path):
    monkeypatch.setattr(worker_module.DocWorkerWrapper, "__init__", Mock(return_value=None))
    popen = Mock()
    popen.return_value.returncode = 0
    popen.return_value.communicate.return_value = ("", "")
    monkeypatch.setattr(worker_module.subprocess, "Popen", popen)
    engine_dir = tmp_path / "engine"
    engine_dir.mkdir()
    config_path = engine_dir / "config.ini"
    config = "[DB_API]\napi_url = https://example.invalid\nusername = test\npassword = test\n"
    config_path.write_text(config)

    def run(settings=None, alto=False, page=False, metadata=False, device="cpu", gpu_id=None,
            alto_dir="input alto", page_xml_dir="input page", meta_file="meta.json"):
        worker = worker_module.PeopleGatorWorker(
            "https://example.invalid", Mock(), device=device, gpu_id=gpu_id,
        )
        job = SimpleNamespace(engine_settings=settings, alto_required=alto,
                              page_required=page, meta_json_required=metadata)
        response = worker.process_job(
            job, Mock(), "input images", str(tmp_path / "results"),
            alto_dir=alto_dir, page_xml_dir=page_xml_dir, meta_file=meta_file,
            engine_dir=str(tmp_path / "engine"),
        )
        assert response.success
        popen.return_value.communicate.assert_called_once_with()
        args = popen.call_args.args[0]
        assert args[0] == "peoplegator"
        assert all(isinstance(value, str) and value for value in args)
        options = dict(zip(args[1::2], args[2::2]))
        assert len(options) * 2 + 1 == len(args)
        assert options["--config"] == str(tmp_path / "engine" / "config.ini")
        assert options["--input-image-path"] == "input images"
        assert config_path.read_text() == config
        # An allowlist also guards against leaking DocAPI or DB credentials.
        assert options.keys() <= {
            "--config", "--input-image-path", "--input-alto-path", "--input-xml-path",
            "--input-metadata-path", "--output-alto-path", "--output-xml-path",
            "--output-render-path", "--device", "--gpu-id", "--logging-level",
        }
        return options

    run.popen = popen
    return run


@pytest.mark.parametrize("input_format", ["alto", "page"])
@pytest.mark.parametrize("outputs", list(itertools.product([False, True], repeat=3)))
def test_input_and_output_combinations(invoke, tmp_path, input_format, outputs):
    settings = dict(zip(("alto", "page", "renders"), outputs))
    options = invoke({"outputs": settings}, alto=input_format == "alto", page=input_format == "page")
    assert options.get("--input-alto-path") == ("input alto" if input_format == "alto" else None)
    assert options.get("--input-xml-path") == ("input page" if input_format == "page" else None)
    for enabled, option, directory in zip(outputs,
            ("--output-alto-path", "--output-xml-path", "--output-render-path"),
            ("alto", "page", "renders")):
        assert options.get(option) == (str(tmp_path / "results" / directory) if enabled else None)


@pytest.mark.parametrize("settings", [None, {}, {"outputs": {}}, {"outputs": {"crops": True}},
    {"outputs": {"page": True}}, {"outputs": {"alto": False, "renders": True}}])
def test_missing_and_partial_output_settings(invoke, settings):
    options = invoke(settings)
    outputs = (settings or {}).get("outputs", {})
    for key, option in (("alto", "--output-alto-path"), ("page", "--output-xml-path"),
                        ("renders", "--output-render-path")):
        assert (option in options) == bool(outputs.get(key))


@pytest.mark.parametrize("required", [False, True])
@pytest.mark.parametrize("path", [None, "", "document metadata.json"])
def test_optional_metadata(invoke, required, path):
    options = invoke(metadata=required, meta_file=path)
    assert options.get("--input-metadata-path") == (path if required and path else None)


@pytest.mark.parametrize("input_format", ["alto", "page"])
@pytest.mark.parametrize("path", [None, ""])
def test_missing_optional_xml_path(invoke, input_format, path):
    options = invoke(alto=input_format == "alto", page=input_format == "page",
                     alto_dir=path, page_xml_dir=path)
    assert "--input-alto-path" not in options
    assert "--input-xml-path" not in options


def test_mutually_exclusive_xml_inputs(invoke):
    with pytest.raises(ValueError, match="ALTO.*PAGE"):
        invoke(alto=True, page=True)
    invoke.popen.assert_not_called()


@pytest.mark.parametrize(("device", "gpu_id"), [("cpu", None), ("gpu", None), ("gpu", 0), ("gpu", 2)])
def test_device_and_gpu_id(invoke, device, gpu_id):
    options = invoke(device=device, gpu_id=gpu_id)
    assert options["--device"] == device
    assert options.get("--gpu-id") == (str(gpu_id) if gpu_id is not None else None)


@pytest.mark.parametrize(("root_level", "worker_level", "expected"), [
    (logging.INFO, logging.NOTSET, "INFO"),
    (logging.DEBUG, logging.NOTSET, "DEBUG"),
    (logging.WARNING, logging.NOTSET, "WARNING"),
    (logging.INFO, logging.ERROR, "ERROR"),
])
def test_effective_logging_level(invoke, worker_module, monkeypatch, root_level, worker_level, expected):
    monkeypatch.setattr(logging.getLogger(), "level", root_level)
    monkeypatch.setattr(worker_module.logger, "level", worker_level)
    assert invoke()["--logging-level"] == expected


@pytest.mark.parametrize("gpu_id", [None, 0, 3])
def test_cli_and_main_forwarding(worker_module, monkeypatch, tmp_path, gpu_id):
    arguments = ["peoplegator_worker", "--api-url", "https://example.invalid", "--api-key", "test",
                 "--base-dir", str(tmp_path), "--device", "cpu", "--logging-level", "DEBUG"]
    if gpu_id is not None:
        arguments += ["--gpu-id", str(gpu_id)]
    monkeypatch.setattr(sys, "argv", arguments)
    constructor = Mock()
    monkeypatch.setattr(worker_module, "PeopleGatorWorker", constructor)
    monkeypatch.setattr(worker_module, "setup_logging", Mock())
    monkeypatch.setattr(worker_module, "Connector", Mock())
    assert worker_module.main() == 0
    assert constructor.call_args.kwargs["device"] == "cpu"
    assert constructor.call_args.kwargs["gpu_id"] == gpu_id
    assert constructor.call_args.kwargs["base_dir"] == str(tmp_path)
    constructor.return_value.start.assert_called_once_with()


def test_existing_defaults(worker_module, monkeypatch):
    monkeypatch.setattr(sys, "argv", ["peoplegator_worker"])
    args = worker_module.parse_arguments()
    assert args.device == "gpu"
    assert args.gpu_id is None
    assert args.logging_level == "INFO"
    assert args.base_dir == "peoplegator_worker_data"
    assert args.polling_interval == 1.0
    monkeypatch.setattr(worker_module.DocWorkerWrapper, "__init__", Mock(return_value=None))
    worker = worker_module.PeopleGatorWorker("https://example.invalid", Mock())
    assert worker.device == "cpu"
    assert worker.gpu_id is None


@pytest.fixture
def invoke_completion(worker_module, monkeypatch):
    instance = object.__new__(worker_module.PeopleGatorWorker)
    instance.device = "cpu"
    instance.gpu_id = 0
    process = Mock(returncode=0)
    process.communicate.return_value = ("", "")
    popen = Mock(return_value=process)
    monkeypatch.setattr(worker_module.subprocess, "Popen", popen)

    def run(returncode=0, output=("", ""), job_id="job-29", input_format="alto"):
        process.returncode = returncode
        process.communicate.return_value = output
        job = SimpleNamespace(alto_required=input_format == "alto",
                              page_required=input_format == "page",
                              meta_json_required=True,
                              engine_settings={"outputs": {"alto": True, "page": True, "renders": True}})
        if job_id is not None:
            job.id = job_id
        return instance.process_job(job, None, "input images", "results",
                                    alto_dir="input alto", page_xml_dir="input page",
                                    meta_file="meta.json", engine_dir="engine")

    run.process = process
    run.popen = popen
    return run


@pytest.mark.parametrize("output", [("", ""), ("processing complete", "diagnostic")])
def test_success_response(invoke_completion, output, caplog, worker_module):
    with caplog.at_level(logging.DEBUG, logger=worker_module.__name__):
        response = invoke_completion(output=output)
    assert response == worker_module.WorkerResponse.ok()
    assert not [record for record in caplog.records if record.levelno >= logging.ERROR]
    invoke_completion.process.communicate.assert_called_once_with()


@pytest.mark.parametrize("returncode", [1, 2, -15])
@pytest.mark.parametrize("output", [("processing started", "invalid configuration"), ("", "")])
@pytest.mark.parametrize("job_id", ["job-29", None])
def test_failure_response_and_diagnostics(invoke_completion, worker_module, caplog, returncode, output, job_id):
    with caplog.at_level(logging.ERROR, logger=worker_module.__name__):
        response = invoke_completion(returncode, output, job_id)
    job_label = job_id or "unknown"
    assert response == worker_module.WorkerResponse.fail(
        f"peoplegator processing for job {job_label} failed with return code {returncode}"
    )
    messages = [record.getMessage() for record in caplog.records
                if record.name == worker_module.__name__ and record.levelno == logging.ERROR]
    assert response.error_message in messages
    assert f"Job {job_label} stdout: {output[0]}" in messages
    assert f"Job {job_label} stderr: {output[1]}" in messages
    invoke_completion.process.communicate.assert_called_once_with()


def test_failure_message_omits_output_and_credentials(invoke_completion, worker_module, monkeypatch, caplog):
    monkeypatch.setenv("DOCAPI_KEY", "worker-secret")
    output = ("password=child-secret", "sensitive diagnostic")
    with caplog.at_level(logging.ERROR, logger=worker_module.__name__):
        response = invoke_completion(2, output)
    assert "worker-secret" not in caplog.text
    for value in ("worker-secret", "child-secret", "sensitive diagnostic", "--config"):
        assert value not in response.error_message


@pytest.mark.parametrize("input_format", ["alto", "page"])
@pytest.mark.parametrize("returncode", [0, 2])
def test_command_unchanged(invoke_completion, worker_module, monkeypatch, caplog, input_format, returncode):
    monkeypatch.setenv("WORKER_TEST_VALUE", "preserved")
    with caplog.at_level(logging.INFO, logger=worker_module.__name__):
        invoke_completion(returncode=returncode, input_format=input_format)
    option = "--input-alto-path" if input_format == "alto" else "--input-xml-path"
    path = "input alto" if input_format == "alto" else "input page"
    invoke_completion.popen.assert_called_once_with(
        ["peoplegator", "--config", os.path.join("engine", "config.ini"),
         "--input-image-path", "input images",
         "--logging-level", "INFO", "--device", "cpu", "--gpu-id", "0",
         option, path, "--input-metadata-path", "meta.json",
         "--output-alto-path", os.path.join("results", "alto"),
         "--output-xml-path", os.path.join("results", "page"),
         "--output-render-path", os.path.join("results", "renders")],
        stdout=worker_module.subprocess.PIPE, stderr=worker_module.subprocess.PIPE,
        env=os.environ.copy(), text=True,
    )
