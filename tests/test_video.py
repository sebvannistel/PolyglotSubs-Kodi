import os
import types
from unittest.mock import MagicMock

import pytest

os.environ.setdefault("A4KSUBTITLES_API_MODE", '{"kodi": true}')

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
    meta = utils.Box(
        {
            "title": "Inception",
            "year": "2010",
            "season": "",
            "episode": "",
            "tvshow": "",
            "tvshow_year": "",
            "imdb_id": "",
        },
        default_box=True,
        default_box_attr=None,
    )

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
    meta = utils.Box(
        {
            "title": "Winter Is Coming",
            "year": "2011",
            "season": "1",
            "episode": "1",
            "tvshow": "Game of Thrones",
            "tvshow_year": "",
            "imdb_id": "",
        },
        default_box=True,
        default_box_attr=None,
    )

    series = FakeMovie(
        "0944947",
        title="Game of Thrones",
        kind="tv series",
        year=2011,
        **{"series years": "2011-2019"},
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
    meta = utils.Box(
        {
            "title": "",
            "year": "",
            "season": "",
            "episode": "",
            "tvshow": "",
            "tvshow_year": "",
            "imdb_id": "tt1375666",
        },
        default_box=True,
        default_box_attr=None,
    )

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
    meta = utils.Box(
        {
            "title": "Winter Is Coming",
            "year": "2011",
            "season": "1",
            "episode": "1",
            "tvshow": "Game of Thrones",
            "tvshow_year": "",
            "imdb_id": "tt0944947",
        },
        default_box=True,
        default_box_attr=None,
    )

    series = FakeMovie(
        "0944947",
        title="Game of Thrones",
        kind="tv series",
        year=2011,
        **{"series years": "2011-2019"},
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
    imdb_client.get_movie_episodes.return_value = {
        "data": {"episodes": {1: {1: episode}}}
    }
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
    meta = utils.Box(
        {
            "title": "",
            "year": "",
            "season": "",
            "episode": "",
            "tvshow": "Game of Thrones",
            "tvshow_year": "",
            "imdb_id": "tt0944947",
        },
        default_box=True,
        default_box_attr=None,
    )

    series = FakeMovie(
        "0944947",
        title="Game of Thrones",
        kind="tv series",
        year=2011,
        **{"series years": "2011-2019"},
    )

    imdb_client = MagicMock()
    imdb_client.get_movie.return_value = series
    imdb_client.update.side_effect = lambda *_: None

    monkeypatch.setattr(video, "__get_imdb_client", lambda core: imdb_client)

    video.__scrape_tvshow_year(types.SimpleNamespace(), meta)

    assert meta.tvshow_year == "2011"
    assert tvshow_year_cache["tt0944947"] == "2011"


def test_get_episode_from_listing_invalid_input():
    assert video.__get_episode_from_listing(None, 1, 1) is None
    assert video.__get_episode_from_listing({}, 1, 1) is None
    assert video.__get_episode_from_listing({"data": {}}, 1, 1) is None
    assert video.__get_episode_from_listing({"data": {"episodes": {}}}, 1, 1) is None


def test_get_episode_from_listing_found():
    episode = {"title": "Test Episode"}
    listing = {"data": {"episodes": {1: {1: episode}}}}
    assert video.__get_episode_from_listing(listing, 1, 1) == episode

    listing_str_keys = {"data": {"episodes": {"1": {"1": episode}}}}
    assert video.__get_episode_from_listing(listing_str_keys, 1, 1) == episode


def test_get_episode_from_listing_list_structure():
    episode1 = {"title": "Episode 1"}
    episode2 = {"title": "Episode 2"}
    listing = {"data": {"episodes": {1: [episode1, episode2]}}}
    assert video.__get_episode_from_listing(listing, 1, 1) == episode1
    assert video.__get_episode_from_listing(listing, 1, 2) == episode2
    assert video.__get_episode_from_listing(listing, 1, 3) is None


def test_extract_year():
    assert video.__extract_year(None) is None
    assert video.__extract_year(2023) == 2023
    assert video.__extract_year("2023") == 2023
    assert video.__extract_year("Released in 2023") == 2023
    assert video.__extract_year("No year here") is None


def test_format_imdb_id():
    assert video.__format_imdb_id(None) == ""
    assert video.__format_imdb_id("tt1234567") == "tt1234567"
    assert video.__format_imdb_id("1234567") == "tt1234567"
    assert video.__format_imdb_id(1234567) == "tt1234567"


def test_is_imdb_id():
    assert video.__is_imdb_id("tt1234567") is True
    assert video.__is_imdb_id("1234567") is False
    assert video.__is_imdb_id("") is False


def test_get_filename(monkeypatch):
    mock_player = MagicMock()
    mock_player.getPlayingFile.return_value = "/path/to/video/Test.Movie.2023.mkv"
    monkeypatch.setattr(video.xbmc, "Player", lambda: mock_player)

    filename = video.__get_filename("Test Movie")
    assert filename == "Test.Movie.2023.mkv"

    mock_player.getPlayingFile.return_value = "/path/to/video/Test.Movie.2023.mp4"
    filename = video.__get_filename("Test Movie")
    assert filename == "Test.Movie.2023.mp4"

    mock_player.getPlayingFile.side_effect = Exception("Player error")
    filename = video.__get_filename("Test Movie")
    assert filename == "Test Movie"


def test_set_size_and_hash_small_file(monkeypatch):
    core = MagicMock()
    core.progress_dialog.dialog = None
    meta = utils.Box({}, default_box=True)

    mock_file = MagicMock()
    mock_file.size.return_value = 1000
    mock_file.hash.side_effect = Exception("No hash method")

    monkeypatch.setattr(video.xbmcvfs, "File", lambda path: mock_file)

    video.__set_size_and_hash(core, meta, "/path/to/small.file")

    assert meta.filesize == 1000
    assert 'filehash' not in meta


def test_set_size_and_hash_large_file(monkeypatch):
    core = MagicMock()
    core.progress_dialog.dialog = None
    meta = utils.Box({}, default_box=True)

    mock_file = MagicMock()
    mock_file.size.return_value = 200000
    mock_file.readBytes.return_value = b'\x01' * 8  # 64-bit int

    monkeypatch.setattr(video.xbmcvfs, "File", lambda path: mock_file)
    mock_file.hash.side_effect = Exception("No hash method")

    def mock_sum(f, result):
        result.filehash += 12345

    monkeypatch.setattr(video, "__sum_64k_bytes", mock_sum)

    video.__set_size_and_hash(core, meta, "/path/to/large.file")

    assert meta.filesize == 200000
    # 200000 + 12345 (first chunk) + 12345 (last chunk) = 224690
    # hex(224690) = 0x36db2
    assert meta.filehash == "%016x" % 224690
