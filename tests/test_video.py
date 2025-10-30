import json
from types import SimpleNamespace

import pytest


class FakeMovie(dict):
    def __init__(self, movieID, **data):
        super().__init__(**data)
        self.movieID = movieID


class FakeIMDb:
    def __init__(self, search_map=None, movies=None, episodes=None):
        self._search_map = {k.lower(): v for k, v in (search_map or {}).items()}
        self._movies = movies or {}
        self._episodes = episodes or {}
        self.timeout = None

    def set_timeout(self, timeout):
        self.timeout = timeout

    def search_movie(self, query, results=None):
        return list(self._search_map.get((query or '').lower(), []))

    def get_movie(self, movie_id):
        movie = self._movies.get(movie_id)
        if movie is None:
            raise RuntimeError('Movie not found')
        return movie

    def get_movie_episodes(self, movie_id, season_nums='all'):
        return self._episodes.get(movie_id, {})


@pytest.fixture
def video_module(monkeypatch):
    monkeypatch.setenv("A4KSUBTITLES_API_MODE", json.dumps({"kodi": True}))

    import importlib
    from a4kSubtitles.lib import kodi as kodi_module

    importlib.reload(kodi_module)

    video_module = importlib.import_module("a4kSubtitles.lib.video")
    importlib.reload(video_module)
    return video_module


def _patch_caches(video_module, monkeypatch):
    imdb_cache = {}
    tvshow_years = {}

    monkeypatch.setattr(video_module.cache, "get_imdb_id_cache", lambda: imdb_cache)
    monkeypatch.setattr(video_module.cache, "save_imdb_id_cache", imdb_cache.update)
    monkeypatch.setattr(video_module.cache, "get_tvshow_years_cache", lambda: tvshow_years)
    monkeypatch.setattr(video_module.cache, "save_tvshow_years_cache", tvshow_years.update)

    return imdb_cache, tvshow_years


def test_cinemagoer_movie_resolution(video_module, monkeypatch):
    fake_movie = FakeMovie('1234567', title='The Matrix', year=1999, kind='movie')
    fake_client = FakeIMDb(
        search_map={'The Matrix': [fake_movie]},
        movies={'1234567': fake_movie},
    )

    _patch_caches(video_module, monkeypatch)
    monkeypatch.setattr(video_module, '__get_imdb_client', lambda core: fake_client)

    meta = video_module.utils.DictAsObject({
        'title': 'The Matrix',
        'year': '1999',
        'season': '',
        'episode': '',
        'tvshow': '',
        'tvshow_year': '',
        'imdb_id': ''
    })

    video_module.__scrape_imdb_id(SimpleNamespace(), meta)

    assert meta.imdb_id == 'tt1234567'
    assert meta.title == 'The Matrix'
    assert meta.year == '1999'


def test_cinemagoer_tv_episode_resolution(video_module, monkeypatch):
    fake_series = FakeMovie('7654321', title='Example Show', year=2015, kind='tv series', **{'series years': '2015-2017'})
    fake_episode = FakeMovie(
        '7654322',
        title='Example Episode',
        year=2016,
        kind='episode',
        season=1,
        episode=2,
        **{'tv series title': 'Example Show'}
    )

    fake_client = FakeIMDb(
        search_map={'Example Show': [fake_series]},
        movies={'7654321': fake_series, '7654322': fake_episode},
        episodes={'7654321': {'data': {'episodes': {1: {2: fake_episode}}}}}
    )

    _, tvshow_years = _patch_caches(video_module, monkeypatch)
    monkeypatch.setattr(video_module, '__get_imdb_client', lambda core: fake_client)

    meta = video_module.utils.DictAsObject({
        'title': 'Example Episode',
        'year': '2016',
        'season': '1',
        'episode': '2',
        'tvshow': 'Example Show',
        'tvshow_year': '',
        'imdb_id': ''
    })

    video_module.__scrape_imdb_id(SimpleNamespace(), meta)

    assert meta.imdb_id == 'tt7654322'
    assert meta.title == 'Example Episode'
    assert meta.tvshow == 'Example Show'
    assert meta.tvshow_year == '2015'

    video_module.__update_info_from_imdb(SimpleNamespace(), meta)

    assert meta.title == 'Example Episode'
    assert meta.year == '2016'
    assert tvshow_years['tt7654321'] == '2015'
    assert tvshow_years['tt7654322'] == '2015'
