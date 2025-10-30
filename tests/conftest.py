from unittest.mock import MagicMock, patch

import pytest


@pytest.fixture
def stub_gemini_translator():
    """Provide a stub Gemini translator for tests that inspect translation flows."""

    translator = MagicMock()
    translator.translate_lines.return_value = []
    translator.config = MagicMock(model="test-model")

    with patch(
        "a4kSubtitles.services.subtitlecat.translation._get_gemini_translator",
        return_value=translator,
    ) as patched:
        yield translator



def pytest_addoption(parser):
    parser.addoption(
        "--run-integration",
        action="store_true",
        default=False,
        help="run integration tests",
    )


def pytest_collection_modifyitems(config, items):
    if config.getoption("--run-integration"):
        return
    skip_integration = pytest.mark.skip(reason="need --run-integration option to run")
    for item in items:
        if "integration" in item.keywords:
            item.add_marker(skip_integration)
