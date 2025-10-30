import json
import os
import sys
from unittest.mock import MagicMock, patch

import pytest

current_dir = os.path.dirname(__file__)
repo_root = os.path.abspath(os.path.join(current_dir, "..", ".."))
if repo_root not in sys.path:
    sys.path.append(repo_root)

os.environ.setdefault("A4KSUBTITLES_API_MODE", json.dumps({"kodi": True}))

from a4kSubtitles.services.subtitlecat import translation as sc_translation


def test_gemini_chunk_translation_uses_translator(stub_gemini_translator):
    core = MagicMock()
    core.logger = MagicMock()
    core.settings.get.side_effect = lambda key, default=None: default

    stub_gemini_translator.translate_lines.return_value = ["uno", "dos"]
    stub_gemini_translator.config.model = "gemini-test"

    with patch(
        "a4kSubtitles.services.subtitlecat.translation._inc_gemini_counter_with_reset",
        return_value=(1, False, 0),
    ):
        results, detected = sc_translation._gemini_translate_text_chunk(
            ["one", "two"],
            "es",
            core,
            "subtitlecat",
        )

    assert results == ["uno", "dos"]
    assert detected == "auto"
    stub_gemini_translator.translate_lines.assert_called_once_with(
        ["one", "two"],
        source_language="auto",
        target_language="es",
        delimiter=sc_translation._CHUNK_SEP,
        log=None,
    )
