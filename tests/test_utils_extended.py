import unittest
from unittest.mock import MagicMock, patch, mock_open
import sys
import os
import json
import zipfile

# Mock modules that are not available in the test environment or rely on Kodi
sys.modules['xbmc'] = MagicMock()
mock_addon = MagicMock()
# Return absolute path to /app
mock_addon.getAddonInfo.return_value = "/app"
sys.modules['xbmcaddon'] = MagicMock()
sys.modules['xbmcaddon'].Addon.return_value = mock_addon

sys.modules['xbmcgui'] = MagicMock()
sys.modules['xbmcplugin'] = MagicMock()
sys.modules['xbmcvfs'] = MagicMock()

# Add the repo root to sys.path so we can import a4kSubtitles
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))

# Ensure a4kSubtitles package is initialized
import a4kSubtitles
a4kSubtitles.initialize()

from a4kSubtitles.lib import utils
from a4kSubtitles.lib.third_party.pysrt import SubRipItem, SubRipFile

class TestUtilsExtended(unittest.TestCase):
    def setUp(self):
        self.core = MagicMock()
        self.core.logger = MagicMock()

    def test_strip_non_ascii_and_unprintable(self):
        text = "Hello\x00World"
        # ftfy.fix_text should handle this
        self.assertEqual(utils.strip_non_ascii_and_unprintable(text), "HelloWorld")
        self.assertEqual(utils.strip_non_ascii_and_unprintable("Normal Text"), "Normal Text")

    def test_slugify_filename(self):
        filename = "Movie: The Movie!.mkv"
        # sanitize_filename with replacement_text="_"
        # pathvalidate 2.5.2 default doesn't replace !
        self.assertEqual(utils.slugify_filename(filename), "Movie_ The Movie!.mkv")

    def test_get_any_of_regex(self):
        array = ["one", "two", "three"]
        regex = utils.get_any_of_regex(array)
        self.assertEqual(regex, r"(one|two|three)")

        # Test escaping
        array = ["one.", "two*"]
        regex = utils.get_any_of_regex(array)
        self.assertEqual(regex, r"(one\.|two\*)")

    @patch('a4kSubtitles.lib.utils.subscleaner')
    @patch('a4kSubtitles.lib.utils.pysrt')
    def test_cleanup_subtitles_with_ads(self, mock_pysrt, mock_subscleaner):
        core = MagicMock()
        sub_contents = "1\n00:00:01,000 --> 00:00:02,000\nAd"

        mock_subs = MagicMock()
        mock_pysrt.from_string.return_value = mock_subs
        mock_subscleaner.remove_ad_lines.return_value = True

        def write_into(output):
            output.write("Cleaned Subtitles")

        mock_subs.write_into.side_effect = write_into

        result = utils.cleanup_subtitles(core, sub_contents)

        self.assertEqual(result, "Cleaned Subtitles")
        mock_subscleaner.remove_ad_lines.assert_called_once_with(mock_subs)

    @patch('a4kSubtitles.lib.utils.subscleaner')
    @patch('a4kSubtitles.lib.utils.pysrt')
    def test_cleanup_subtitles_no_ads(self, mock_pysrt, mock_subscleaner):
        core = MagicMock()
        sub_contents = "Original Subtitles"

        mock_subs = MagicMock()
        mock_pysrt.from_string.return_value = mock_subs
        mock_subscleaner.remove_ad_lines.return_value = False

        result = utils.cleanup_subtitles(core, sub_contents)

        self.assertEqual(result, "Original Subtitles")

    @patch('a4kSubtitles.lib.utils.subscleaner')
    @patch('a4kSubtitles.lib.utils.pysrt')
    def test_cleanup_subtitles_error(self, mock_pysrt, mock_subscleaner):
        core = MagicMock()
        sub_contents = "Original Subtitles"

        mock_pysrt.from_string.side_effect = Exception("Error")

        result = utils.cleanup_subtitles(core, sub_contents)

        self.assertEqual(result, "Original Subtitles")

    def test_get_json_success(self):
        with patch('a4kSubtitles.lib.utils.open_file_wrapper') as mock_wrapper:
            mock_file = mock_open(read_data='{"key": "value"}')
            mock_wrapper.return_value.return_value = mock_file.return_value

            result = utils.get_json("/path", "file")

            self.assertEqual(result, {"key": "value"})

    def test_get_json_error(self):
        with patch('a4kSubtitles.lib.utils.open_file_wrapper') as mock_wrapper:
            mock_file = mock_open(read_data='invalid json')
            mock_wrapper.return_value.return_value = mock_file.return_value

            result = utils.get_json("/path", "file")

            self.assertIsNone(result)

    def test_find_file_in_archive_exact_match_with_episode(self):
        core = MagicMock()
        namelist = ["Show.S01E01.srt", "Show.S01E02.srt"]
        exts = [".srt"]
        episode_number = "001"

        # We need to mock extract_season_episode since it's used inside find_file_in_archive
        with patch('a4kSubtitles.lib.utils.extract_season_episode') as mock_extract:
            mock_extract.side_effect = lambda f, fb: MagicMock(episode="001") if "E01" in f else MagicMock(episode="002")

            result = utils.find_file_in_archive(core, namelist, exts, episode_number)

            self.assertEqual(result, "Show.S01E01.srt")

    def test_find_file_in_archive_first_ext_match(self):
        core = MagicMock()
        namelist = ["Readme.txt", "Show.srt"]
        exts = [".srt"]
        episode_number = "001"

        with patch('a4kSubtitles.lib.utils.extract_season_episode') as mock_extract:
             mock_extract.return_value = MagicMock(episode="999")

             result = utils.find_file_in_archive(core, namelist, exts, episode_number)

             self.assertEqual(result, "Show.srt")

    def test_find_file_in_archive_no_match(self):
        core = MagicMock()
        namelist = ["Readme.txt"]
        exts = [".srt"]

        result = utils.find_file_in_archive(core, namelist, exts)

        self.assertIsNone(result)

    def test_get_zipfile_namelist(self):
        mock_zip = MagicMock()
        mock_info1 = MagicMock()
        mock_info1.filename = "test.txt"
        mock_info1.flag_bits = utils.zip_utf8_flag # UTF-8

        mock_info2 = MagicMock()
        # We need filename to be a MagicMock to mock encode
        filename_mock = MagicMock(spec=str)
        filename_mock.__str__.return_value = "latin1.txt"
        filename_mock.encode.return_value.decode.return_value = "latin1_decoded.txt"
        mock_info2.filename = filename_mock
        mock_info2.flag_bits = 0 # Not UTF-8

        mock_zip.infolist.return_value = [mock_info1, mock_info2]

        # We need to be careful with mocking behavior that depends on py2/py3
        # Assuming test environment is py3
        with patch('a4kSubtitles.lib.utils.py2', False):
            namelist = utils.get_zipfile_namelist(mock_zip)
            # Since we mocked the string object itself, the result list will contain the return value of decode
            self.assertEqual(namelist, ["test.txt", "latin1_decoded.txt"])

    def test_extract_zipfile_member(self):
        mock_zip = MagicMock()
        filename = "test.txt"
        dest = "/dest"

        with patch('a4kSubtitles.lib.utils.py2', False):
            utils.extract_zipfile_member(mock_zip, filename, dest)
            mock_zip.extract.assert_called_with(filename, dest)

    def test_extract_zipfile_member_unicode_error(self):
        mock_zip = MagicMock()
        filename = "test.txt"
        dest = "/dest"

        mock_zip.extract.side_effect = [UnicodeEncodeError("utf-8", "test", 0, 1, "error"), "extracted"]

        with patch('a4kSubtitles.lib.utils.py2', False):
             utils.extract_zipfile_member(mock_zip, filename, dest)
             # Should have been called twice
             self.assertEqual(mock_zip.extract.call_count, 2)

    def test_wait_threads(self):
        mock_thread1 = MagicMock()
        mock_thread2 = MagicMock()

        threads = [mock_thread1, mock_thread2]

        utils.wait_threads(threads)

        mock_thread1.start.assert_called_once()
        mock_thread2.start.assert_called_once()
        mock_thread1.join.assert_called_once()
        mock_thread2.join.assert_called_once()

    def test_get_all_relative_entries(self):
        with patch('os.listdir') as mock_listdir:
            mock_listdir.return_value = ["script.py", "__init__.py", "other.txt"]

            # Mocking os.path.dirname isn't needed if we pass a file path that has a dirname,
            # or we can just mock it.

            entries = utils.get_all_relative_entries("/path/to/file.py")

            self.assertEqual(entries, ["script"])

    def test_get_all_relative_entries_no_ignore_private(self):
        with patch('os.listdir') as mock_listdir:
            mock_listdir.return_value = ["script.py", "__init__.py"]

            entries = utils.get_all_relative_entries("/path/to/file.py", ignore_private=False)

            self.assertIn("script", entries)
            self.assertIn("__init__", entries)

if __name__ == '__main__':
    unittest.main()
