import os
import types
from unittest.mock import MagicMock

import pytest

os.environ.setdefault("A4KSUBTITLES_API_MODE", "{\"kodi\": true}")

from a4kSubtitles.lib import utils, video


class FakeMovie(dict):
    def __init__(self, movie_id, **data):
        super().__init__(**data)
        self.movieID = movie_id

    def getID(self):
        return self.movieID


@pytest.fixture(autouse=True)
def _reset_cinemagoer_client(monkeypatch):
    monkeypatch.setattr(video, "__cinemagoer_client", None, raising=False)


@pytest.fixture(autouse=True)
def tvshow_year_cache(monkeypatch):
    store = {}

    def save(data):
        store.update(data)

    monkeypatch.setattr(video.cache, "get_tvshow_years_cache", lambda: store)
    monkeypatch.setattr(video.cache, "save_tvshow_years_cache", save)
    return store


def test_scrape_imdb_id_movie(monkeypatch):
    meta = utils.DictAsObject({
        "title": "Inception",
        "year": "2010",
        "season": "",
        "episode": "",
        "tvshow": "",
        "tvshow_year": "",
        "imdb_id": "",
    })

    imdb_client = MagicMock()
    imdb_client.search_movie.return_value = [
        FakeMovie("1375666", title="Inception", kind="movie", year=2010)
    ]
    monkeypatch.setattr(video, "__get_imdb_client", lambda core: imdb_client)

    video.__scrape_imdb_id(types.SimpleNamespace(), meta)

    assert meta.imdb_id == "tt1375666"
    assert meta.title == "Inception"
    assert meta.year == "2010"


def test_scrape_imdb_id_tv_episode(monkeypatch, tvshow_year_cache):
    meta = utils.DictAsObject({
        "title": "Winter Is Coming",
        "year": "2011",
        "season": "1",
        "episode": "1",
        "tvshow": "Game of Thrones",
        "tvshow_year": "",
        "imdb_id": "",
    })

    series = FakeMovie(
        "0944947",
        title="Game of Thrones",
        kind="tv series",
        year=2011,
        **{"series years": "2011-2019"}
    )
    episode = FakeMovie(
        "1480055",
        title="Winter Is Coming",
        year=2011,
        season=1,
        episode=1,
    )
    listing = {"data": {"episodes": {1: {1: episode}}}}

    imdb_client = MagicMock()
    imdb_client.search_movie.return_value = [series]
    imdb_client.get_movie_episodes.return_value = listing
    imdb_client.update.side_effect = lambda *_: None

    monkeypatch.setattr(video, "__get_imdb_client", lambda core: imdb_client)

    video.__scrape_imdb_id(types.SimpleNamespace(), meta)

    assert meta.imdb_id == "tt1480055"
    assert meta.title == "Winter Is Coming"
    assert meta.year == "2011"
    assert tvshow_year_cache["tt0944947"] == "2011"


def test_update_info_from_imdb_movie(monkeypatch):
    meta = utils.DictAsObject({
        "title": "",
        "year": "",
        "season": "",
        "episode": "",
        "tvshow": "",
        "tvshow_year": "",
        "imdb_id": "tt1375666",
    })

    imdb_client = MagicMock()
    imdb_client.get_movie.return_value = FakeMovie(
        "1375666", title="Inception", kind="movie", year=2010
    )

    monkeypatch.setattr(video, "__get_imdb_client", lambda core: imdb_client)

    video.__update_info_from_imdb(types.SimpleNamespace(), meta)

    assert meta.title == "Inception"
    assert meta.year == "2010"
    assert meta.tvshow == ""


def test_update_info_from_imdb_episode(monkeypatch, tvshow_year_cache):
    meta = utils.DictAsObject({
        "title": "Winter Is Coming",
        "year": "2011",
        "season": "1",
        "episode": "1",
        "tvshow": "Game of Thrones",
        "tvshow_year": "",
        "imdb_id": "tt0944947",
    })

    series = FakeMovie(
        "0944947",
        title="Game of Thrones",
        kind="tv series",
        year=2011,
        **{"series years": "2011-2019"}
    )
    episode = FakeMovie(
        "1480055",
        title="Winter Is Coming",
        kind="episode",
        year=2011,
        season=1,
        episode=1,
    )
    episode["episode of"] = series

    imdb_client = MagicMock()
    imdb_client.get_movie.return_value = series
    imdb_client.get_movie_episodes.return_value = {"data": {"episodes": {1: {1: episode}}}}
    imdb_client.update.side_effect = lambda *_: None

    monkeypatch.setattr(video, "__get_imdb_client", lambda core: imdb_client)

    video.__update_info_from_imdb(types.SimpleNamespace(), meta)

    assert meta.imdb_id == "tt1480055"
    assert meta.title == "Winter Is Coming"
    assert meta.tvshow == "Game of Thrones"
    assert meta.season == "1"
    assert meta.episode == "1"
    assert tvshow_year_cache["tt0944947"] == "2011"


def test_scrape_tvshow_year(monkeypatch, tvshow_year_cache):
    meta = utils.DictAsObject({
        "title": "",
        "year": "",
        "season": "",
        "episode": "",
        "tvshow": "Game of Thrones",
        "tvshow_year": "",
        "imdb_id": "tt0944947",
    })

    series = FakeMovie(
        "0944947",
        title="Game of Thrones",
        kind="tv series",
        year=2011,
        **{"series years": "2011-2019"}
    )

    imdb_client = MagicMock()
    imdb_client.get_movie.return_value = series
    imdb_client.update.side_effect = lambda *_: None

    monkeypatch.setattr(video, "__get_imdb_client", lambda core: imdb_client)

    video.__scrape_tvshow_year(types.SimpleNamespace(), meta)

    assert meta.tvshow_year == "2011"
    assert tvshow_year_cache["tt0944947"] == "2011"
