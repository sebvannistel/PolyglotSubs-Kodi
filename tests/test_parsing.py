import sys
import os
import unittest
from unittest.mock import MagicMock

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

# Ensure a4kSubtitles package is initialized to add vendored libs to path
import a4kSubtitles
a4kSubtitles.initialize()

from a4kSubtitles.lib.utils import extract_season_episode

class TestExtractSeasonEpisode(unittest.TestCase):
    def test_standard_sxe(self):
        filename = "The.Show.S01E05.720p.HDTV.x264-Group.mkv"
        res = extract_season_episode(filename)
        self.assertEqual(res.season, "001")
        self.assertEqual(res.episode, "005")

    def test_standard_sxee(self):
        filename = "The.Show.S1E5.720p.HDTV.x264-Group.mkv"
        res = extract_season_episode(filename)
        self.assertEqual(res.season, "001")
        self.assertEqual(res.episode, "005")

    def test_x_notation(self):
        filename = "The.Show.1x05.720p.HDTV.x264-Group.mkv"
        res = extract_season_episode(filename)
        self.assertEqual(res.season, "001")
        self.assertEqual(res.episode, "005")

    def test_anime_notation(self):
        # Guessit handles anime absolute numbers but might not map them to "episode"
        # if it thinks it is absolute_episode, unless we configure it or it falls back.
        # Let's see how it behaves by default.
        filename = "[Group] Anime Show - 05 [720p].mkv"
        res = extract_season_episode(filename)
        # Default guessit might detect this as episode 5.
        self.assertEqual(res.episode, "005")

    def test_anime_notation_with_season(self):
        filename = "[Group] Anime Show S2 - 05 [720p].mkv"
        res = extract_season_episode(filename)
        self.assertEqual(res.season, "002")
        self.assertEqual(res.episode, "005")

    def test_date_based(self):
        # Date based usually doesn't have season/episode, but date.
        # Our current wrapper only returns season/episode.
        # If guessit returns date, season/episode will be None/Empty.
        filename = "The.Daily.Show.2023.10.25.720p.HDTV.x264-Group.mkv"
        res = extract_season_episode(filename)
        self.assertEqual(res.season, "")
        self.assertEqual(res.episode, "")

    def test_full_season_pack(self):
         filename = "The.Show.S01.1080p.BluRay.x264-Group"
         res = extract_season_episode(filename)
         self.assertEqual(res.season, "001")
         self.assertEqual(res.episode, "")

    def test_multi_episode(self):
        filename = "The.Show.S01E05-E06.720p.HDTV.x264-Group.mkv"
        res = extract_season_episode(filename)
        self.assertEqual(res.season, "001")
        # Current logic takes the first one
        self.assertEqual(res.episode, "005")
        # Check range
        self.assertEqual(list(res.episodes_range), [5, 6])

    def test_weak_match_year_conflict(self):
        # Ensure year is not taken as season or episode
        filename = "My Movie 2023.mkv"
        res = extract_season_episode(filename)
        self.assertEqual(res.season, "")
        self.assertEqual(res.episode, "")

if __name__ == '__main__':
    unittest.main()
