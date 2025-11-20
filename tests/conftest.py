from unittest.mock import Mock

import pytest


@pytest.fixture
def gemini_translator_stub(monkeypatch):
    """Provide a deterministic Gemini translator stub for unit tests."""

    stub = Mock()

    def _translate(texts, *, target_language, start_index=1):
        return [f"{target_language}:{text}" if text else "" for text in texts]

    stub.translate.side_effect = _translate
    monkeypatch.setattr(
        "a4kSubtitles.services.subtitlecat.translation._get_gemini_translator",
        lambda core, service_name: stub,
    )
    return stub


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
