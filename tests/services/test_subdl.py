
import pytest
from unittest.mock import MagicMock, patch
from a4kSubtitles.services import subdl

class TestSubDL:
    @pytest.fixture
    def core(self):
        core = MagicMock()
        core.kodi.get_setting.return_value = "test_api_key"
        core.utils.get_lang_ids.return_value = ["en", "es"]
        core.json.loads = MagicMock()
        return core

    @pytest.fixture
    def meta(self):
        meta = MagicMock()
        meta.languages = ["English", "Spanish"]
        meta.is_tvshow = False
        meta.title = "Test Movie"
        meta.year = "2023"
        meta.imdb_id = "tt1234567"
        meta.filename_without_ext = "Test.Movie.2023"
        return meta

    def test_build_search_requests_missing_apikey(self, core, meta):
        core.kodi.get_setting.return_value = ""
        requests = subdl.build_search_requests(core, "subdl", meta)
        assert requests == []
        core.kodi.notification.assert_called_once()

    def test_build_search_requests_movie(self, core, meta):
        requests = subdl.build_search_requests(core, "subdl", meta)
        assert len(requests) == 1
        req = requests[0]
        assert req["url"] == "https://api.subdl.com/api/v1/subtitles"
        assert req["params"]["api_key"] == "test_api_key"
        assert req["params"]["type"] == "movie"
        assert req["params"]["imdb_id"] == "tt1234567"
        assert req["params"]["year"] == "2023"

    def test_build_search_requests_tvshow(self, core, meta):
        meta.is_tvshow = True
        meta.tvshow = "Test Show"
        meta.season = "1"
        meta.episode = "1"
        meta.tvshow_year = "2022"
        meta.tvshow_year_thread = None

        requests = subdl.build_search_requests(core, "subdl", meta)
        assert len(requests) == 1
        req = requests[0]
        assert req["params"]["type"] == "tv"
        assert req["params"]["film_name"] == "Test Show"
        assert req["params"]["season_number"] == "1"
        assert req["params"]["episode_number"] == "1"
        assert req["params"]["year"] == "2022"

    def test_parse_search_response_success(self, core, meta):
        response = MagicMock()
        response.text = '{"status": true, "subtitles": [{"release_name": "Test.Movie.2023.srt", "language": "en", "url": "/dl/123", "hi": false}]}'
        core.json.loads.return_value = {"status": True, "subtitles": [{"release_name": "Test.Movie.2023.srt", "language": "en", "url": "/dl/123", "hi": False}]}
        core.services = {"subdl": MagicMock(display_name="SubDL")}
        core.utils.get_lang_ids.return_value = ["en"]
        meta.languages = ["English"]

        results = subdl.parse_search_response(core, "subdl", meta, response)
        assert len(results) == 1
        assert results[0]["name"] == "Test.Movie.2023.srt"
        assert results[0]["lang"] == "English"
        assert results[0]["impaired"] == "false"
        assert results[0]["action_args"]["url"] == "/dl/123"

    def test_parse_search_response_failure(self, core, meta):
        response = MagicMock()
        response.text = '{"status": false, "message": "Error"}'
        core.json.loads.return_value = {"status": False, "message": "Error"}

        results = subdl.parse_search_response(core, "subdl", meta, response)
        assert results == []
        core.logger.error.assert_called()

    def test_parse_search_response_exception(self, core, meta):
        response = MagicMock()
        response.text = "invalid json"
        core.json.loads.side_effect = Exception("Invalid JSON")

        results = subdl.parse_search_response(core, "subdl", meta, response)
        assert results == []
        core.logger.error.assert_called()

    def test_build_download_request(self, core):
        args = {"url": "/dl/123", "filename": "test.srt"}
        request = subdl.build_download_request(core, "subdl", args)
        assert request["url"] == "https://dl.subdl.com/dl/123"
