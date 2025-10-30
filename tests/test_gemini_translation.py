from unittest.mock import Mock

import pytest

from a4kSubtitles.services.subtitlecat import translation as sc_translation


class DummyCore:
    def __init__(self, settings):
        self.settings = settings
        self.logger = Mock()


@pytest.mark.usefixtures("gemini_translator_stub")
def test_translate_text_chunk_uses_gemini_stub(gemini_translator_stub):
    placeholder = "@@MISSING@@"
    core = DummyCore(
        {
            "subtitlecat_translation_failed_placeholder": placeholder,
            "subtitlecat_gemini_request_limit": 0,
            "subtitlecat_gemini_throttle_sleep": 0,
        }
    )

    gemini_translator_stub.translate.side_effect = (
        lambda texts, *, target_language, start_index=1: ["Hola", None]
    )

    translated, detected = sc_translation._translate_text_chunk(
        ["Hello", ""],
        "es",
        core,
        "subtitlecat",
    )

    assert translated == ["Hola", ""]
    assert detected == "auto"
    gemini_translator_stub.translate.assert_called_once()
    _, kwargs = gemini_translator_stub.translate.call_args
    assert kwargs["target_language"] == "es"
    assert kwargs["start_index"] == 1
