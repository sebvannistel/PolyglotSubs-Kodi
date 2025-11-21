import unittest
from unittest.mock import MagicMock, patch, ANY
import sys
import os
import json

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
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '../..')))

# Ensure a4kSubtitles package is initialized
import a4kSubtitles
a4kSubtitles.initialize()

from a4kSubtitles.services import opensubtitles

class TestOpenSubtitles(unittest.TestCase):
    def setUp(self):
        self.core = MagicMock()
        self.core.os.getenv.return_value = "false"
        self.core.json = json
        self.core.datetime = MagicMock()
        self.core.time = MagicMock()
        self.core.kodi = MagicMock()
        self.core.utils = MagicMock()
        self.core.services = {
            "opensubtitles": MagicMock(display_name="OpenSubtitles")
        }

        # Setup default mock values
        self.service_name = "opensubtitles"
        self.core.kodi.get_setting.return_value = "test_user"
        self.core.kodi.xbmc = MagicMock()
        self.core.kodi.xbmc.ISO_639_1 = "iso639_1"
        self.core.kodi.xbmc.ENGLISH_NAME = "english_name"

    def test_build_auth_request_no_credentials(self):
        self.core.kodi.get_setting.return_value = ""
        self.core.cache.get_tokens_cache.return_value = {}

        req = opensubtitles.build_auth_request(self.core, self.service_name)

        self.assertIsNone(req)
        self.core.kodi.notification.assert_called_with(
            "OpenSubtitles now requires authentication! Enter username/password in the addon Settings->Accounts or disable the service."
        )

    def test_build_auth_request_valid_credentials(self):
        self.core.cache.get_tokens_cache.return_value = {}

        req = opensubtitles.build_auth_request(self.core, self.service_name)

        self.assertIsNotNone(req)
        self.assertEqual(req['method'], 'POST')
        self.assertTrue(req['url'].endswith('/login'))
        data = json.loads(req['data'])
        self.assertEqual(data['username'], 'test_user')
        self.assertEqual(data['password'], 'test_user')
        self.assertIn('headers', req)
        self.assertEqual(req['headers']['Content-Type'], 'application/json')
        self.assertEqual(req['headers']['Api-Key'], '7IQ4FYAepMynq20VYYHyj5mVHtx3qvKa')

    def test_parse_auth_response_success(self):
        response = MagicMock()
        response.status_code = 200
        response.text = json.dumps({
            "token": "test_token",
            "base_url": "api.opensubtitles.com",
            "user": {"allowed_downloads": 10}
        })

        self.core.datetime.now.return_value.strftime.return_value = "2023-01-01 00:00:00"
        cache_mock = {}
        self.core.cache.get_tokens_cache.return_value = cache_mock

        opensubtitles.parse_auth_response(self.core, self.service_name, response)

        self.assertIn(self.service_name, cache_mock)
        self.assertEqual(cache_mock[self.service_name]['token'], "test_token")
        self.core.cache.save_tokens_cache.assert_called_with(cache_mock)

    def test_parse_auth_response_failure(self):
        response = MagicMock()
        response.status_code = 401
        response.text = json.dumps({"message": "Unauthorized"})

        opensubtitles.parse_auth_response(self.core, self.service_name, response)

        self.core.kodi.notification.assert_called_with(
            "OpenSubtitles authentication failed! Check your OpenSubtitles.com username and password."
        )

    def test_build_search_requests_no_token(self):
        self.core.cache.get_tokens_cache.return_value = {}

        reqs = opensubtitles.build_search_requests(self.core, self.service_name, MagicMock())

        self.assertEqual(reqs, [])

    def test_build_search_requests_tvshow(self):
        token_cache = {
            "token": "test_token",
            "base_url": "api.test.com",
            "ttl": "2099-01-01 00:00:00"
        }
        self.core.cache.get_tokens_cache.return_value = {self.service_name: token_cache}
        self.core.utils.get_lang_ids.return_value = ["en"]

        meta = MagicMock()
        meta.is_tvshow = True
        meta.tvshow = "Test Show"
        meta.season = 1
        meta.episode = 5
        meta.languages = ["English"]
        meta.filehash = None

        reqs = opensubtitles.build_search_requests(self.core, self.service_name, meta)

        self.assertEqual(len(reqs), 1)
        self.assertEqual(reqs[0]['method'], 'GET')
        self.assertIn('api.test.com', reqs[0]['url'])
        self.assertEqual(reqs[0]['params']['query'], "Test Show S01E05")
        self.assertEqual(reqs[0]['params']['type'], "episode")
        self.assertEqual(reqs[0]['params']['season_number'], 1)
        self.assertEqual(reqs[0]['params']['episode_number'], 5)
        self.assertEqual(reqs[0]['headers']['Authorization'], "Bearer test_token")

    def test_build_search_requests_movie(self):
        token_cache = {
            "token": "test_token",
            "base_url": "api.test.com",
            "ttl": "2099-01-01 00:00:00"
        }
        self.core.cache.get_tokens_cache.return_value = {self.service_name: token_cache}
        self.core.utils.get_lang_ids.return_value = ["en"]

        meta = MagicMock()
        meta.is_tvshow = False
        meta.title = "Test Movie"
        meta.year = 2023
        meta.imdb_id = "tt1234567"
        meta.languages = ["English"]
        meta.filehash = "hash123"

        reqs = opensubtitles.build_search_requests(self.core, self.service_name, meta)

        self.assertEqual(len(reqs), 1)
        self.assertEqual(reqs[0]['params']['query'], "Test Movie 2023")
        self.assertEqual(reqs[0]['params']['type'], "movie")
        self.assertEqual(reqs[0]['params']['imdb_id'], "1234567")
        self.assertEqual(reqs[0]['params']['moviehash'], "hash123")

    def test_parse_search_response(self):
        meta = MagicMock()
        meta.imdb_id_as_int = 1234567

        response = MagicMock()
        response.text = json.dumps({
            "data": [
                {
                    "attributes": {
                        "feature_details": {"imdb_id": 1234567},
                        "files": [{"file_name": "sub1.srt", "file_id": 101}],
                        "language": "en",
                        "ratings": 8.0,
                        "moviehash_match": True,
                        "hearing_impaired": False
                    }
                },
                {
                    "attributes": {
                        "feature_details": {"imdb_id": 9999999}, # Different IMDB ID
                        "files": [{"file_name": "sub2.srt", "file_id": 102}],
                        "language": "fr",
                        "ratings": 5.0,
                        "moviehash_match": False,
                        "hearing_impaired": True
                    }
                }
            ]
        })

        self.core.utils.get_lang_id.side_effect = lambda l, f: "English" if l == "en" else "French"

        results = opensubtitles.parse_search_response(self.core, self.service_name, meta, response)

        # Note: The original implementation returns None for filtered results, but map returns [Result, None].
        # The original code uses map which in Python 3 returns an iterator, then list() converts it.
        # If the map function returns None, list(map(...)) will include None.
        # We should check if the original code filters None values.
        # Looking at opensubtitles.py: return list(map(map_result, results["data"]))
        # It does NOT filter None values! This seems to be a bug or at least unexpected behavior in the original code,
        # assuming the consumer handles None.
        # However, to match current behavior in test, we expect [Result, None].

        # Wait, if I look at the code again:
        # return list(map(map_result, results["data"]))
        # Yes, it returns None for mismatches.

        self.assertEqual(len(results), 2)
        self.assertIsNotNone(results[0])
        self.assertIsNone(results[1])

        self.assertEqual(results[0]['name'], "sub1.srt")
        self.assertEqual(results[0]['sync'], "true")
        self.assertEqual(results[0]['impaired'], "false")
        self.assertEqual(results[0]['rating'], 4)
        self.assertEqual(results[0]['action_args']['url'], 101)

    def test_build_download_request(self):
        args = {"url": 123}
        token_cache = {
            "token": "test_token",
            "base_url": "api.test.com",
            "ttl": "2099-01-01 00:00:00"
        }
        self.core.cache.get_tokens_cache.return_value = {self.service_name: token_cache}

        req = opensubtitles.build_download_request(self.core, self.service_name, args)

        self.assertEqual(req['method'], 'POST')
        self.assertTrue(req['url'].endswith('/download'))
        data = json.loads(req['data'])
        self.assertEqual(data['file_id'], 123)

        # Test the 'next' lambda
        download_resp = MagicMock()
        download_resp.text = json.dumps({"link": "http://download.link", "remaining": 10})
        next_req = req['next'](download_resp)
        self.assertEqual(next_req['method'], 'GET')
        self.assertEqual(next_req['url'], "http://download.link")

if __name__ == '__main__':
    unittest.main()
