import pytest
from unittest.mock import MagicMock, call, patch
import json
import queue
from a4kSubtitles import search

class MockThread:
    def __init__(self, target, args=()):
        self.target = target
        self.args = args
    def start(self):
        # print(f"DEBUG: MockThread starting target: {self.target}")
        self.target(*self.args)
    def join(self):
        pass

@pytest.fixture
def mock_core():
    core = MagicMock()
    core.services = {}
    core.logger = MagicMock()
    core.kodi = MagicMock()
    core.request = MagicMock()
    core.utils = MagicMock()
    core.video = MagicMock()
    core.cache = MagicMock()
    core.time = MagicMock()
    core.json = json

    # Use MockThread instead of real threading
    core.threading = MagicMock()
    core.threading.Thread = MockThread

    core.utils.queue = queue
    core.api_mode_enabled = False

    # Mock utils functions
    core.utils.unquote = lambda x: x
    core.utils.quote_plus = lambda x: x

    def wait_threads(threads):
        for t in threads:
            t.start()
        for t in threads:
            t.join()
    core.utils.wait_threads = wait_threads

    # Mock kodi functions
    core.kodi.get_bool_setting.return_value = True
    core.kodi.get_int_setting.return_value = 10
    core.kodi.parse_language.side_effect = lambda x: x

    # Mock regex
    import re
    core.re = re
    import difflib
    core.difflib = difflib

    return core

def test_auth_service(mock_core):
    service = MagicMock()
    mock_core.services = {'test_service': service}
    request = {'auth': 'req'}
    response = MagicMock()
    mock_core.request.execute.return_value = response

    search.__auth_service(mock_core, 'test_service', request)

    mock_core.request.execute.assert_called_with(mock_core, request)
    service.parse_auth_response.assert_called_with(mock_core, 'test_service', response)

def test_query_service_success(mock_core):
    service = MagicMock()
    service.display_name = 'TestService'
    mock_core.services = {'test_service': service}
    mock_core.progress_text = "TestService|"

    request = {'url': 'http://test.com'}
    response = MagicMock()
    response.status_code = 200
    response.text = "result"
    mock_core.request.execute.return_value = response

    results = []
    meta = {'title': 'Test'}

    service_results = [{'service_name': 'test_service', 'name': 'Result 1'}]
    service.parse_search_response.return_value = service_results

    search.__query_service(mock_core, 'test_service', meta, request, results)

    assert len(results) == 1
    assert results[0] == service_results[0]
    mock_core.request.execute.assert_called_with(mock_core, request)
    service.parse_search_response.assert_called_with(mock_core, 'test_service', meta, response)
    assert "TestService" not in mock_core.progress_text
    mock_core.kodi.update_progress.assert_called_with(mock_core)

def test_query_service_failure(mock_core):
    service = MagicMock()
    service.display_name = 'TestService'
    mock_core.services = {'test_service': service}
    mock_core.progress_text = "TestService|"

    request = {'url': 'http://test.com'}
    mock_core.request.execute.return_value = None

    results = []
    meta = {'title': 'Test'}

    search.__query_service(mock_core, 'test_service', meta, request, results)

    assert len(results) == 0
    assert "TestService" not in mock_core.progress_text

def test_has_results():
    results = [
        {'service_name': 's1', 'val': 1},
        {'service_name': 's2', 'val': 2}
    ]
    assert search.__has_results('s1', results) is True
    assert search.__has_results('s3', results) is False

def test_save_results(mock_core):
    meta = {'imdb_id': 'tt1234567'}
    results = [{'item': 1}]
    mock_core.time.time.return_value = 1000
    mock_core.cache.get_meta_hash.return_value = 'hash123'

    search.__save_results(mock_core, meta, results)

    mock_core.cache.save_last_results.assert_called_with({
        "hash": 'hash123',
        "timestamp": 1000,
        "results": results
    })

def test_save_results_empty(mock_core):
    meta = {'imdb_id': 'tt1234567'}
    results = []
    search.__save_results(mock_core, meta, results)
    mock_core.cache.save_last_results.assert_not_called()

def test_save_results_exception(mock_core):
    meta = {'imdb_id': 'tt1234567'}
    results = [{'item': 1}]
    mock_core.cache.get_meta_hash.side_effect = Exception("Error")
    # Should not raise
    search.__save_results(mock_core, meta, results)

def test_get_last_results_miss(mock_core):
    meta = {'imdb_id': 'tt1234567'}
    mock_core.cache.get_meta_hash.return_value = 'hash123'
    mock_core.cache.get_last_results.return_value = None

    res, force = search.__get_last_results(mock_core, meta)
    assert res == []
    assert force == []

def test_get_last_results_hit(mock_core):
    meta = {'imdb_id': 'tt1234567'}
    mock_core.cache.get_meta_hash.return_value = 'hash123'
    cached = {
        "timestamp": 1000,
        "results": [{'service_name': 's1'}]
    }
    mock_core.cache.get_last_results.return_value = cached
    mock_core.time.time.return_value = 1000 + 60 # 1 min later

    res, force = search.__get_last_results(mock_core, meta)
    assert res == cached["results"]
    assert force == []

def test_get_last_results_bsplayer_expired(mock_core):
    meta = {'imdb_id': 'tt1234567'}
    mock_core.cache.get_meta_hash.return_value = 'hash123'
    cached = {
        "timestamp": 1000,
        "results": [{'service_name': 'bsplayer'}, {'service_name': 'other'}]
    }
    mock_core.cache.get_last_results.return_value = cached
    mock_core.time.time.return_value = 1000 + 200 # > 3 min later

    res, force = search.__get_last_results(mock_core, meta)
    assert len(res) == 1
    assert res[0]['service_name'] == 'other'
    assert 'bsplayer' in force

def test_apply_language_filter(mock_core):
    meta = MagicMock()
    meta.languages = ['en', 'de']
    results = [
        {'lang': 'en'},
        {'lang': 'fr'},
        {'lang': 'de'}
    ]
    filtered = search.__apply_language_filter(meta, results)
    assert len(filtered) == 2
    assert {'lang': 'en'} in filtered
    assert {'lang': 'de'} in filtered

def test_apply_limit(mock_core):
    meta = MagicMock()
    meta.languages = ['en', 'de']
    mock_core.kodi.get_int_setting.return_value = 4

    results = [
        {'lang': 'en', 'id': 1}, {'lang': 'en', 'id': 2}, {'lang': 'en', 'id': 3},
        {'lang': 'de', 'id': 4}, {'lang': 'de', 'id': 5}, {'lang': 'de', 'id': 6},
    ]

    # limit is 4. lang_limit will be 4/2 = 2.
    # Should get 2 en and 2 de.
    limited = search.__apply_limit(mock_core, results, meta)
    assert len(limited) == 4
    en_count = sum(1 for r in limited if r['lang'] == 'en')
    de_count = sum(1 for r in limited if r['lang'] == 'de')
    assert en_count == 2
    assert de_count == 2

def test_parse_languages(mock_core):
    mock_core.kodi.parse_language.side_effect = lambda x: x if x in ['en', 'de'] else None
    langs = search.__parse_languages(mock_core, ["en", "de", "fr", "unknown"])
    assert len(langs) == 2
    assert 'en' in langs
    assert 'de' in langs

def test_search_no_imdb(mock_core):
    params = {'languages': 'en', 'preferredlanguage': 'en'}
    mock_core.video.get_meta.return_value = MagicMock(imdb_id="")

    result = search.search(mock_core, params)

    assert result is None
    mock_core.kodi.notification.assert_called_with("IMDB ID is not provided")

def test_search_full_flow(mock_core):
    params = {'languages': 'en', 'preferredlanguage': 'en'}
    meta = MagicMock()
    meta.imdb_id = "tt1234567"
    meta.languages = ['en']
    meta.preferredlanguage = 'en'
    meta.filename_without_ext = "Movie.Title"
    meta.is_tvshow = False
    meta.episode = ""
    meta.season = ""

    mock_core.video.get_meta.return_value = meta

    # Ensure check_cancellation loop doesn't run
    mock_core.progress_dialog = None

    # Mock services
    service1 = MagicMock()
    service1.display_name = 'Service1'
    service1.build_auth_request.return_value = None
    service1.build_search_requests.return_value = [{'url': 'req1'}]

    # Mock __query_service behavior via side_effect of modifying results list
    def query_side_effect(core, service_name, meta, request, results):
        results.append({
            'service_name': 'service1',
            'lang': 'en',
            'name': 'Movie Title',
            'rating': 0,
            'sync': False,
            'impaired': False,
            'service': 'service1',
            'action_args': {'url': 'http://dl'}
        })

    # Use patch for prepare_results as well
    with patch('a4kSubtitles.search.__query_service', side_effect=query_side_effect):
        try:
            mock_core.services = {'service1': service1}
            mock_core.cache.get_meta_hash.return_value = 'hash'
            mock_core.cache.get_last_results.return_value = None

            # Run search
            result = search.search(mock_core, params)

            # In standard mode, result is None, but kodi items are added
            assert result is None
            mock_core.cache.save_last_results.assert_called()
            mock_core.kodi.xbmcplugin.addDirectoryItem.assert_called()

        except Exception as e:
            raise e

def test_search_api_mode(mock_core):
    mock_core.api_mode_enabled = True
    params = {'languages': 'en', 'preferredlanguage': 'en'}
    meta = MagicMock()
    meta.imdb_id="tt1234567"
    meta.languages=['en']
    meta.preferredlanguage='en'
    meta.filename_without_ext = "Movie.Title"
    meta.is_tvshow = False
    meta.episode = ""
    meta.season = ""

    mock_core.video.get_meta.return_value = meta

    mock_core.services = {}
    mock_core.cache.get_last_results.return_value = None

    result = search.search(mock_core, params)
    assert result == []

def test_prepare_results_sorting(mock_core):
    meta = MagicMock()
    meta.languages = ['en']
    meta.preferredlanguage = 'en'
    meta.filename_without_ext = "Movie.Title.1080p"
    meta.is_tvshow = False
    meta.episode = ""
    meta.season = ""

    results = [
        {
            'service_name': 's1', 'lang': 'en', 'name': 'Movie.Title.720p',
            'rating': 0, 'sync': False, 'impaired': False, 'service': 's1',
            'action_args': {'url': 'u1'}
        },
        {
            'service_name': 's1', 'lang': 'en', 'name': 'Movie.Title.1080p',
            'rating': 0, 'sync': False, 'impaired': False, 'service': 's1',
            'action_args': {'url': 'u2'}
        }
    ]

    sorted_results = search.__prepare_results(mock_core, meta, results)

    # 1080p should be first because it matches filename
    assert sorted_results[0]['name'] == 'Movie.Title.1080p'
    assert sorted_results[1]['name'] == 'Movie.Title.720p'

def test_prepare_results_sorting_episode(mock_core):
    meta = MagicMock()
    meta.languages = ['en']
    meta.preferredlanguage = 'en'
    meta.filename_without_ext = "Show.S01E02"
    meta.is_tvshow = True
    meta.season = '1'
    meta.episode = '2'

    # Mock utils extract_season_episode
    def extract_se(name):
        m = MagicMock()
        if 'S01E02' in name:
            m.season = '001'
            m.episode = '002'
            m.episodes_range = []
        else:
            m.season = '001'
            m.episode = '003'
            m.episodes_range = []
        return m

    mock_core.utils.extract_season_episode = extract_se

    results = [
        {
            'service_name': 's1', 'lang': 'en', 'name': 'Show.S01E03',
            'rating': 0, 'sync': False, 'impaired': False, 'service': 's1',
            'action_args': {'url': 'u1'}
        },
        {
            'service_name': 's1', 'lang': 'en', 'name': 'Show.S01E02',
            'rating': 0, 'sync': False, 'impaired': False, 'service': 's1',
            'action_args': {'url': 'u2'}
        }
    ]

    sorted_results = search.__prepare_results(mock_core, meta, results)

    assert sorted_results[0]['name'] == 'Show.S01E02'
