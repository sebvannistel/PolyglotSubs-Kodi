import unittest
from unittest.mock import MagicMock, patch
import os
import sys
import json

# Ensure repository root on sys.path
current_dir = os.path.dirname(__file__)
repo_root = os.path.abspath(os.path.join(current_dir, '..', '..'))
sys.path.append(repo_root)

# Mock Kodi modules on import
os.environ["A4KSUBTITLES_API_MODE"] = json.dumps({"kodi": True})

from a4kSubtitles.services import subtitlecat as subtitlecat_module


class TestSubtitlecatClientTranslation(unittest.TestCase):
    def setUp(self):
        self.core = MagicMock()
        self.core.logger = MagicMock()
        # Return default value for any setting lookup
        self.core.settings.get.side_effect = lambda key, default=None: default
        self.service = "subtitlecat_test"
        self.args = {
            "needs_client_side_translation": True,
            "original_srt_url": "http://example.com/orig.srt",
            "target_translation_lang": "fr",
            "filename": "test.srt",
        }
        # Clear any cached translations between tests
        subtitlecat_module._CLIENT_TRANSLATED_CONTENT_CACHE = subtitlecat_module.SimpleLRUCache(maxsize=128)

    def _prepare_session_and_parse(self, mock_get_session, mock_srt_parse, srt_text):
        mock_session = MagicMock()
        mock_response = MagicMock()
        mock_response.text = srt_text
        mock_response.raise_for_status.return_value = None
        mock_session.get.return_value = mock_response
        mock_get_session.return_value = mock_session

        item1 = MagicMock()
        item2 = MagicMock()
        item1.content = "S1"
        item2.content = "S2"
        mock_srt_parse.return_value = [item1, item2]
        return item1, item2

    @patch("a4kSubtitles.services.subtitlecat.time.sleep")
    @patch("a4kSubtitles.services.subtitlecat.srt.compose", side_effect=lambda items: "composed_srt")
    @patch("a4kSubtitles.services.subtitlecat.html.unescape", side_effect=lambda x: x)
    @patch("a4kSubtitles.services.subtitlecat._restore_subtitle_tags", side_effect=lambda text, tag_map: text)
    @patch("a4kSubtitles.services.subtitlecat._gtranslate_text_chunk")
    @patch("a4kSubtitles.services.subtitlecat._protect_subtitle_tags")
    @patch("a4kSubtitles.services.subtitlecat.srt.parse")
    @patch("a4kSubtitles.services.subtitlecat._get_session")
    def test_translation_perfect_match(self, mock_get_session, mock_srt_parse,
                                      mock_protect, mock_translate, mock_restore,
                                      mock_unescape, mock_compose, mock_sleep):
        item1, item2 = self._prepare_session_and_parse(mock_get_session, mock_srt_parse, "1\nS1\n\n2\nS2\n")
        mock_protect.side_effect = [("S1p", {}, False), ("S2p", {}, False)]
        mock_translate.return_value = (["T1", "T2"], "en")

        result = subtitlecat_module.build_download_request(self.core, self.service, self.args)

        self.assertEqual(item1.content, "T1")
        self.assertEqual(item2.content, "T2")
        mock_translate.assert_called_once_with(["S1p", "S2p"], "fr", self.core, self.service, 0)

        with patch("io.open", MagicMock()) as mock_open:
            self.assertTrue(result["save_callback"]("/fake/path.srt"))
            mock_open.assert_called_once_with("/fake/path.srt", "w", encoding="utf-8")
            handle = mock_open.return_value.__enter__.return_value
            handle.write.assert_called_once_with("composed_srt")

    @patch("a4kSubtitles.services.subtitlecat.time.sleep")
    @patch("a4kSubtitles.services.subtitlecat.srt.compose", side_effect=lambda items: "composed_srt")
    @patch("a4kSubtitles.services.subtitlecat.html.unescape", side_effect=lambda x: x)
    @patch("a4kSubtitles.services.subtitlecat._restore_subtitle_tags", side_effect=lambda text, tag_map: text)
    @patch("a4kSubtitles.services.subtitlecat._gtranslate_text_chunk")
    @patch("a4kSubtitles.services.subtitlecat._protect_subtitle_tags")
    @patch("a4kSubtitles.services.subtitlecat.srt.parse")
    @patch("a4kSubtitles.services.subtitlecat._get_session")
    def test_translation_with_missing_segments(self, mock_get_session, mock_srt_parse,
                                               mock_protect, mock_translate, mock_restore,
                                               mock_unescape, mock_compose, mock_sleep):
        item1, item2 = self._prepare_session_and_parse(mock_get_session, mock_srt_parse, "1\nS1\n\n2\nS2\n")
        mock_protect.side_effect = [("S1p", {}, False), ("S2p", {}, False)]
        mock_translate.return_value = (["T1"], "en")  # Only one segment returned

        subtitlecat_module.build_download_request(self.core, self.service, self.args)

        self.assertEqual(item1.content, "T1")
        self.assertEqual(item2.content, subtitlecat_module.DEFAULT_TRANSLATION_FAILED_PLACEHOLDER)
        mock_translate.assert_called_once_with(["S1p", "S2p"], "fr", self.core, self.service, 0)


if __name__ == "__main__":
    unittest.main()
