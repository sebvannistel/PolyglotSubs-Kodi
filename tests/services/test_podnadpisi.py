
import pytest
from unittest.mock import MagicMock, patch
from a4kSubtitles.services import podnadpisi

class TestPodnadpisi:
    @pytest.fixture
    def core(self):
        core = MagicMock()
        core.utils.get_lang_ids.return_value = ["en"]
        core.json.loads = MagicMock()
        core.difflib.SequenceMatcher.return_value.ratio.return_value = 1.0
        return core

    @pytest.fixture
    def meta(self):
        meta = MagicMock()
        meta.languages = ["English"]
        meta.is_tvshow = False
        meta.title = "Test Movie"
        meta.year = "2023"
        meta.filename_without_ext = "Test.Movie.2023"
        return meta

    def test_build_search_requests_movie(self, core, meta):
        requests = podnadpisi.build_search_requests(core, "podnadpisi", meta)
        assert len(requests) == 1
        req = requests[0]
        assert req["url"] == "https://www.podnapisi.net/subtitles/search/advanced"
        assert req["params"]["keywords"] == "Test Movie"
        assert req["params"]["movie_type"] == "movie"
        assert req["params"]["year"] == "2023"

    def test_build_search_requests_tvshow(self, core, meta):
        meta.is_tvshow = True
        meta.tvshow = "Test Show"
        meta.is_movie = False
        meta.season = "1"
        meta.episode = "1"
        meta.tvshow_year = "2022"
        meta.tvshow_year_thread = None

        requests = podnadpisi.build_search_requests(core, "podnadpisi", meta)
        assert len(requests) == 1
        req = requests[0]
        assert req["params"]["keywords"] == "Test Show"
        assert req["params"]["movie_type"] == ["tv-series", "mini-series"]
        assert req["params"]["seasons"] == "1"
        assert req["params"]["episodes"] == "1"
        assert req["params"]["year"] == "2022"

    def test_parse_search_response_success(self, core, meta):
        response = MagicMock()
        response.text = '{"data": [{"custom_releases": ["Test.Movie.2023"], "language": "en", "download": "/dl/123", "flags": []}]}'
        core.json.loads.return_value = {"data": [{"custom_releases": ["Test.Movie.2023"], "language": "en", "download": "/dl/123", "flags": []}]}
        core.services = {"podnadpisi": MagicMock(display_name="Podnadpisi")}

        results = podnadpisi.parse_search_response(core, "podnadpisi", meta, response)
        assert len(results) == 1
        assert results[0]["name"] == "Test.Movie.2023.srt"
        assert results[0]["lang"] == "English"
        assert results[0]["action_args"]["url"] == "https://www.podnapisi.net/dl/123"

    def test_parse_search_response_no_releases(self, core, meta):
        response = MagicMock()
        core.json.loads.return_value = {"data": [{"custom_releases": [], "language": "en", "download": "/dl/123", "flags": []}]}
        core.services = {"podnadpisi": MagicMock(display_name="Podnadpisi")}

        results = podnadpisi.parse_search_response(core, "podnadpisi", meta, response)
        assert len(results) == 1
        assert results[0]["name"] == "Test Movie 2023.srt"

    def test_parse_search_response_exception(self, core, meta):
        response = MagicMock()
        core.json.loads.side_effect = Exception("Invalid JSON")

        results = podnadpisi.parse_search_response(core, "podnadpisi", meta, response)
        assert results == []
        core.logger.error.assert_called()

    def test_build_download_request(self, core):
        args = {"url": "https://www.podnapisi.net/dl/123"}
        request = podnadpisi.build_download_request(core, "podnadpisi", args)
        assert request["url"] == "https://www.podnapisi.net/dl/123"

        # Test retry logic
        retry_func = request["error"]
        retry_request = retry_func(MagicMock(status_code=500))
        assert retry_request["url"] == "https://www.podnapisi.net/dl/123"
        assert retry_func(MagicMock(status_code=200)) is None
