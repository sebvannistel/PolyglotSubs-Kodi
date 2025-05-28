import unittest
from unittest.mock import Mock, MagicMock

import unittest
from unittest.mock import Mock, MagicMock

import unittest
from unittest.mock import Mock, MagicMock

import unittest
from unittest.mock import Mock, MagicMock

# Import the function using an alias
from a4kSubtitles.search import __sanitize_results as sanitize_results_to_test

class TestSanitizeResults(unittest.TestCase):
    def test_sanitize_preserves_translate_options(self):
        # 1. Mock core and meta objects
        mock_core = MagicMock()
        mock_core.utils.unquote = lambda x: x  # Mock unquote to return input

        mock_meta = Mock()

        # 2. Construct sample results data
        results_data = [
            {
                'service_name': 'subtitlecat',
                'lang': 'de',
                'name': 'Movie Title German',
                'action_args': {
                    'url': '',
                    'filename': 'Movie.Title.srt',
                    'needs_client_side_translation': True,
                    'original_srt_url': 'http://subtitlecat.com/original/german.srt',
                    'lang': 'de'
                }
            },
            {
                'service_name': 'subtitlecat',
                'lang': 'zh',
                'name': 'Movie Title Chinese',
                'action_args': {
                    'url': '',
                    'filename': 'Movie.Title.srt',
                    'needs_client_side_translation': True,
                    'original_srt_url': 'http://subtitlecat.com/original/chinese.srt',
                    'lang': 'zh'
                }
            },
            {
                'service_name': 'subtitlecat',
                'lang': 'fr',
                'name': 'Movie Title French',
                'action_args': {
                    'url': '', # No direct URL
                    'filename': 'Movie.Title.srt',
                    'method_type': 'SHARED_TRANSLATION_CONTENT', # Uses detail_url
                    'detail_url': 'http://subtitlecat.com/details/french.html',
                    'lang': 'fr'
                }
            },
            {
                'service_name': 'opensubtitles',
                'lang': 'en',
                'name': 'Movie Title English OpenSubtitles',
                'action_args': {
                    'url': 'http://opensubtitles.org/subs/english.srt', # Direct URL
                    'filename': 'Movie.Title.OS.srt',
                    'lang': 'en'
                }
            }
        ]

        # 3. Call the aliased function
        sanitized_results = sanitize_results_to_test(mock_core, mock_meta, results_data)

        # 4. Assertions
        self.assertEqual(len(sanitized_results), 4, "Should preserve all unique items")

        # Check for presence of specific translate options
        found_german_subtitlecat = any(
            r['service_name'] == 'subtitlecat' and r['lang'] == 'de' for r in sanitized_results
        )
        found_chinese_subtitlecat = any(
            r['service_name'] == 'subtitlecat' and r['lang'] == 'zh' for r in sanitized_results
        )
        found_french_subtitlecat = any(
            r['service_name'] == 'subtitlecat' and r['lang'] == 'fr' for r in sanitized_results
        )
        found_english_opensubtitles = any(
            r['service_name'] == 'opensubtitles' and r['lang'] == 'en' for r in sanitized_results
        )

        self.assertTrue(found_german_subtitlecat, "German Subtitlecat translate option missing")
        self.assertTrue(found_chinese_subtitlecat, "Chinese Subtitlecat translate option missing")
        self.assertTrue(found_french_subtitlecat, "French Subtitlecat translate option (SHARED_TRANSLATION_CONTENT) missing")
        self.assertTrue(found_english_opensubtitles, "English OpenSubtitles option missing")

if __name__ == '__main__':
    unittest.main()
