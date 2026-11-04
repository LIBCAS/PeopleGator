import pytest


def pytest_addoption(parser):
    parser.addoption(
        "--runtime-mode", choices=("tool", "client", "full"), default="full",
        help="Installed dependency set required by runtime smoke tests (default: full).",
    )


@pytest.fixture
def runtime_mode(request):
    return request.config.getoption("--runtime-mode")
