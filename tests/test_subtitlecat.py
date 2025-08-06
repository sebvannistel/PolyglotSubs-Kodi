import os
import sys
import json
import unittest
from unittest.mock import MagicMock, patch


# Ensure the repository root is on sys.path so 'a4kSubtitles' can be imported
current_dir = os.path.dirname(__file__)
repo_root = os.path.abspath(os.path.join(current_dir, "..", ".."))
sys.path.append(repo_root)

# Ensure the Subtitlecat service loads with mocked Kodi modules
os.environ["A4KSUBTITLES_API_MODE"] = json.dumps({"kodi": True})

from a4kSubtitles.services import subtitlecat as subtitlecat_module


class TestSubtitlecatBuildDownloadRequest(unittest.TestCase):
    def setUp(self):
        self.core_mock = MagicMock()
        self.core_mock.logger = MagicMock()
        # _get_setting reads from core.settings.get
        self.core_mock.settings.get.side_effect = lambda key, default=None: default

        self.service_name = "subtitlecat_test_service"
        self.base_action_args = {
            "needs_client_side_translation": True,
            "original_srt_url": "http://example.com/orig.srt",
            "target_translation_lang": "fr",
            "filename": "test.srt",
        }

        # Reset caches to avoid cross-test interference
        subtitlecat_module._CLIENT_TRANSLATED_CONTENT_CACHE = subtitlecat_module.SimpleLRUCache(maxsize=128)
        subtitlecat_module._TRANSLATED_CACHE = subtitlecat_module.SimpleLRUCache(maxsize=64)

    @patch("a4kSubtitles.services.subtitlecat.time.sleep")
    @patch("a4kSubtitles.services.subtitlecat._restore_subtitle_tags", side_effect=lambda text, tags: text)
    @patch("a4kSubtitles.services.subtitlecat.srt.compose", side_effect=lambda items: "composed_srt_content")
    @patch("a4kSubtitles.services.subtitlecat._gtranslate_text_chunk")
    @patch("a4kSubtitles.services.subtitlecat._get_session")
    def test_translation_applied(self, mock_get_session, mock_gtranslate, mock_compose, mock_restore, mock_sleep):
        """Ensure translated lines are inserted into the parsed subtitles."""

        # Mock download of original SRT
        mock_session = MagicMock()
        mock_response = MagicMock()
        mock_response.text = (
            "1\n00:00:00,000 --> 00:00:01,000\nS1\n\n"
            "2\n00:00:01,500 --> 00:00:02,000\nS2\n"
        )
        mock_response.raise_for_status.return_value = None
        mock_session.get.return_value = mock_response
        mock_get_session.return_value = mock_session

        # Google translate returns two segments
        mock_gtranslate.return_value = (["T1", "T2"], "en")

        result = subtitlecat_module.build_download_request(
            self.core_mock, self.service_name, self.base_action_args
        )

        mock_gtranslate.assert_called_once_with([
            "S1",
            "S2",
        ], "fr", self.core_mock, self.service_name, 0)
        # Ensure translated content was composed
        composed_items = mock_compose.call_args[0][0]
        self.assertEqual(composed_items[0].content, "T1")
        self.assertEqual(composed_items[1].content, "T2")

        with patch("io.open", MagicMock()) as mock_open:
            self.assertTrue(result["save_callback"]("/fake/path.srt"))
            mock_open.assert_called_once_with("/fake/path.srt", "w", encoding="utf-8")

    @patch("a4kSubtitles.services.subtitlecat.time.sleep")
    @patch("a4kSubtitles.services.subtitlecat.srt.compose", side_effect=lambda items: "composed_srt_content")
    @patch("a4kSubtitles.services.subtitlecat._gtranslate_text_chunk")
    @patch("a4kSubtitles.services.subtitlecat._get_session")
    def test_no_translatable_lines(self, mock_get_session, mock_gtranslate, mock_compose, mock_sleep):
        """Lines consisting only of tags should not be sent for translation."""

        mock_session = MagicMock()
        mock_response = MagicMock()
        mock_response.text = (
            "1\n00:00:00,000 --> 00:00:01,000\n<i></i>\n"
        )
        mock_response.raise_for_status.return_value = None
        mock_session.get.return_value = mock_response
        mock_get_session.return_value = mock_session

        result = subtitlecat_module.build_download_request(
            self.core_mock, self.service_name, self.base_action_args
        )

        mock_gtranslate.assert_not_called()
        mock_compose.assert_called_once()
        with patch("io.open", MagicMock()) as mock_open:
            self.assertTrue(result["save_callback"]("/fake/path.srt"))
            mock_open.assert_called_once_with("/fake/path.srt", "w", encoding="utf-8")

    @patch("a4kSubtitles.services.subtitlecat.time.sleep")
    @patch("a4kSubtitles.services.subtitlecat._restore_subtitle_tags", side_effect=lambda text, tags: text)
    @patch("a4kSubtitles.services.subtitlecat.srt.compose", side_effect=lambda items: "composed_srt_content")
    @patch("a4kSubtitles.services.subtitlecat._gtranslate_text_chunk")
    @patch("a4kSubtitles.services.subtitlecat._get_session")
    def test_fewer_segments_than_translatable_lines(self, mock_get_session, mock_gtranslate, mock_compose, mock_restore, mock_sleep):
        """Missing translations are replaced with the failure placeholder."""

        mock_session = MagicMock()
        mock_response = MagicMock()
        mock_response.text = (
            "1\n00:00:00,000 --> 00:00:01,000\nS1\n\n"
            "2\n00:00:01,500 --> 00:00:02,000\nS2\n"
        )
        mock_response.raise_for_status.return_value = None
        mock_session.get.return_value = mock_response
        mock_get_session.return_value = mock_session

        mock_gtranslate.return_value = (["T1"], "en")

        subtitlecat_module.build_download_request(
            self.core_mock, self.service_name, self.base_action_args
        )

        mock_gtranslate.assert_called_once_with([
            "S1",
            "S2",
        ], "fr", self.core_mock, self.service_name, 0)

        composed_items = mock_compose.call_args[0][0]
        self.assertEqual(composed_items[0].content, "T1")
        self.assertEqual(
            composed_items[1].content,
            subtitlecat_module.DEFAULT_TRANSLATION_FAILED_PLACEHOLDER,
        )

    @patch("a4kSubtitles.services.subtitlecat.time.sleep")
    @patch("a4kSubtitles.services.subtitlecat._restore_subtitle_tags", side_effect=lambda text, tags: text)
    @patch("a4kSubtitles.services.subtitlecat.srt.compose", side_effect=lambda items: "composed_srt_content")
    @patch("a4kSubtitles.services.subtitlecat._gtranslate_text_chunk")
    @patch("a4kSubtitles.services.subtitlecat._get_session")
    def test_more_segments_than_translatable_lines(self, mock_get_session, mock_gtranslate, mock_compose, mock_restore, mock_sleep):
        """Extra segments from Google Translate are discarded."""

        mock_session = MagicMock()
        mock_response = MagicMock()
        mock_response.text = (
            "1\n00:00:00,000 --> 00:00:01,000\nS1\n\n"
            "2\n00:00:01,500 --> 00:00:02,000\nS2\n"
        )
        mock_response.raise_for_status.return_value = None
        mock_session.get.return_value = mock_response
        mock_get_session.return_value = mock_session

        mock_gtranslate.return_value = (["T1", "T2", "EXTRA"], "en")

        subtitlecat_module.build_download_request(
            self.core_mock, self.service_name, self.base_action_args
        )

        mock_gtranslate.assert_called_once_with([
            "S1",
            "S2",
        ], "fr", self.core_mock, self.service_name, 0)

        composed_items = mock_compose.call_args[0][0]
        self.assertEqual(len(composed_items), 2)
        self.assertEqual(composed_items[0].content, "T1")
        self.assertEqual(composed_items[1].content, "T2")

    @patch("a4kSubtitles.services.subtitlecat.time.sleep")
    @patch("a4kSubtitles.services.subtitlecat._restore_subtitle_tags", side_effect=lambda text, tags: text)
    @patch("a4kSubtitles.services.subtitlecat.srt.compose", side_effect=lambda items: "composed_srt_content")
    @patch("a4kSubtitles.services.subtitlecat._gtranslate_text_chunk")
    @patch("a4kSubtitles.services.subtitlecat._get_session")
    def test_single_segment_fewer_segments(self, mock_get_session, mock_gtranslate, mock_compose, mock_restore, mock_sleep):
        """A single subtitle line uses placeholder when translation is missing."""

        mock_session = MagicMock()
        mock_response = MagicMock()
        mock_response.text = (
            "1\n00:00:00,000 --> 00:00:01,000\nS1\n"
        )
        mock_response.raise_for_status.return_value = None
        mock_session.get.return_value = mock_response
        mock_get_session.return_value = mock_session

        mock_gtranslate.return_value = ([], "en")
        subtitlecat_module.build_download_request(
            self.core_mock, self.service_name, self.base_action_args
        )
        composed_items = mock_compose.call_args[0][0]
        self.assertEqual(
            composed_items[0].content,
            subtitlecat_module.DEFAULT_TRANSLATION_FAILED_PLACEHOLDER,
        )

    @patch("a4kSubtitles.services.subtitlecat.time.sleep")
    @patch("a4kSubtitles.services.subtitlecat._restore_subtitle_tags", side_effect=lambda text, tags: text)
    @patch("a4kSubtitles.services.subtitlecat.srt.compose", side_effect=lambda items: "composed_srt_content")
    @patch("a4kSubtitles.services.subtitlecat._gtranslate_text_chunk")
    @patch("a4kSubtitles.services.subtitlecat._get_session")
    def test_single_segment_more_segments(self, mock_get_session, mock_gtranslate, mock_compose, mock_restore, mock_sleep):
        """Extra segments for a single line are ignored."""

        mock_session = MagicMock()
        mock_response = MagicMock()
        mock_response.text = (
            "1\n00:00:00,000 --> 00:00:01,000\nS1\n"
        )
        mock_response.raise_for_status.return_value = None
        mock_session.get.return_value = mock_response
        mock_get_session.return_value = mock_session

        mock_gtranslate.return_value = (["T1", "EXTRA"], "en")
        subtitlecat_module.build_download_request(
            self.core_mock, self.service_name, self.base_action_args
        )
        composed_items = mock_compose.call_args[0][0]
        self.assertEqual(composed_items[0].content, "T1")


if __name__ == "__main__":
    unittest.main()

