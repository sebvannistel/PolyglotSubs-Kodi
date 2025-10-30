# -*- coding: utf-8 -*-

import os
import json
import struct
import hashlib
import re
import threading

from imdb import IMDb, IMDbError

from .kodi import xbmc, xbmcvfs, get_bool_setting, get_int_setting, addon_profile
from . import logger, cache, utils

__64k = 65536
__longlong_format_char = 'q'
__byte_size = struct.calcsize(__longlong_format_char)
__imdb_id_prefix = 'tt'
__cinemagoer_cache_dir = os.path.join(addon_profile, 'cinemagoer-cache')
__imdb_client = None
__imdb_client_lock = threading.Lock()
__tv_kinds = {'tv series', 'tv mini series', 'tv mini-series', 'tv show'}

def __sum_64k_bytes(file, result):
    """
    Sums the first and last 64k bytes of a file.

    Args:
        file (xbmcvfs.File): The file to sum.
        result (object): An object to store the result in.
    """
    range_value = __64k / __byte_size
    if utils.py3:
        range_value = round(range_value)

    for _ in range(range_value):
        try: chunk = file.readBytes(__byte_size)
        except: chunk = file.read(__byte_size)
        (value,) = struct.unpack(__longlong_format_char, chunk)
        result.filehash += value
        result.filehash &= 0xFFFFFFFFFFFFFFFF

def __set_size_and_hash(core, meta, filepath):
    """
    Sets the size and hash of a file.

    Args:
        core (module): The core module.
        meta (DictAsObject): The metadata object to set the size and hash in.
        filepath (str): The path to the file.
    """
    if core.progress_dialog and not core.progress_dialog.dialog:
        core.progress_dialog.open()

    f = xbmcvfs.File(filepath)
    try:
        filesize = meta.filesize = f.size()

        # used for mocking
        try:
            meta.filehash = f.hash()
            return
        except: pass

        if filesize < __64k * 2:
            return

        # ref: https://trac.opensubtitles.org/projects/opensubtitles/wiki/HashSourceCodes
        # filehash = filesize + 64bit sum of the first and last 64k of the file
        result = lambda: None
        result.filehash = filesize

        __sum_64k_bytes(f, result)
        f.seek(filesize - __64k, os.SEEK_SET)
        __sum_64k_bytes(f, result)

        meta.filehash = "%016x" % result.filehash
    finally:
        f.close()

def __get_filename(title):
    """
    Gets the filename of the currently playing video.

    Args:
        title (str): The title of the video.

    Returns:
        str: The filename of the video.
    """
    filename = title
    video_exts = ['mkv', 'mp4', 'avi', 'mov', 'mpeg', 'flv', 'wmv']

    try:
        filepath = xbmc.Player().getPlayingFile()
        filename = filepath.split('/')[-1]
        filename = utils.unquote(filename)

        for ext in video_exts:
            if ext in filename:
                filename = filename[:filename.index(ext) + len(ext)]
                break
    except: pass

    return filename

def __ensure_cinemagoer_cache_dir():
    try:
        xbmcvfs.mkdirs(__cinemagoer_cache_dir)
    except:  # pragma: no cover - safe guard for environments without xbmcvfs.mkdirs
        pass

    try:
        os.makedirs(__cinemagoer_cache_dir, exist_ok=True)
    except:  # pragma: no cover - best effort, ignore if we cannot ensure the cache directory
        pass

def __get_timeout():
    try:
        return get_int_setting('general.timeout')
    except:
        return 10

def __get_imdb_client(_core):
    global __imdb_client
    if __imdb_client is not None:
        return __imdb_client

    with __imdb_client_lock:
        if __imdb_client is not None:
            return __imdb_client

        __ensure_cinemagoer_cache_dir()
        try:
            os.environ.setdefault('IMDBPY_CACHE_DIR', __cinemagoer_cache_dir)
        except Exception:
            pass

        client = IMDb()
        try:
            client.set_timeout(__get_timeout())
        except Exception:
            pass

        __imdb_client = client
        return __imdb_client

def __format_imdb_id(movie_id):
    movie_id = str(movie_id)
    if movie_id.startswith(__imdb_id_prefix):
        return movie_id
    return __imdb_id_prefix + movie_id.zfill(7)

def __normalize_imdb_id(imdb_id):
    return imdb_id[2:] if imdb_id.startswith(__imdb_id_prefix) else imdb_id

def __extract_year(value):
    if isinstance(value, int):
        return str(value)
    if isinstance(value, str):
        match = re.search(r'\d{4}', value)
        if match:
            return match.group(0)
    return ''

def __store_tvshow_year(imdb_id, year):
    if not imdb_id or not year:
        return

    try:
        tvshow_years_cache = cache.get_tvshow_years_cache()
        tvshow_years_cache[imdb_id] = str(year)
        cache.save_tvshow_years_cache(tvshow_years_cache)
    except Exception:
        pass

def __apply_movie_details(meta, movie):
    title = movie.get('title') or movie.get('canonical title')
    year = __extract_year(movie.get('year') or movie.get('original air date'))

    if title:
        meta.title = title
    if year:
        meta.year = year

def __apply_series_details(meta, series_movie):
    series_title = series_movie.get('title') or series_movie.get('canonical title')
    series_year = __extract_year(series_movie.get('year') or series_movie.get('series years'))

    if series_title:
        meta.tvshow = series_title
    if series_year:
        meta.tvshow_year = series_year
        __store_tvshow_year(__format_imdb_id(series_movie.movieID), series_year)

def __apply_episode_details(meta, episode_movie, series_movie=None):
    title = episode_movie.get('title') or episode_movie.get('canonical title')
    year = __extract_year(episode_movie.get('year') or episode_movie.get('original air date'))
    season = episode_movie.get('season')
    episode_number = episode_movie.get('episode')
    series_title = episode_movie.get('tv series title') or (
        series_movie.get('title') if series_movie else None
    )

    if title:
        meta.title = title
    if year:
        meta.year = year
    if season not in (None, '', 'unknown'):
        meta.season = str(season)
    if episode_number not in (None, '', 'unknown'):
        meta.episode = str(episode_number)
    if series_title:
        meta.tvshow = series_title

    meta.imdb_id = __format_imdb_id(episode_movie.movieID)
    if meta.tvshow_year:
        __store_tvshow_year(meta.imdb_id, meta.tvshow_year)

def __select_best_result(results, expected_title, expected_year, allowed_kinds=None):
    expected_title = (expected_title or '').lower()
    allowed_kinds = {kind.lower() for kind in (allowed_kinds or [])}
    expected_year_int = None
    try:
        expected_year_int = int(expected_year)
    except Exception:
        expected_year_int = None

    best_match = None
    fallback = None
    for candidate in results or []:
        kind = (candidate.get('kind') or '').lower()
        if allowed_kinds and kind not in allowed_kinds:
            continue

        candidate_title = (candidate.get('title') or '').lower()
        candidate_year = candidate.get('year')

        if candidate_title == expected_title:
            if expected_year_int is None or candidate_year == expected_year_int:
                return candidate
            if best_match is None:
                best_match = candidate
        if fallback is None:
            fallback = candidate

    return best_match or fallback

def __populate_episode_from_series(imdb_client, meta, series_movie):
    try:
        season = int(meta.season)
        episode_number = int(meta.episode)
    except Exception:
        return

    try:
        episodes_data = imdb_client.get_movie_episodes(series_movie.movieID, season_nums=[season])
    except IMDbError as exc:
        logger.error(lambda: 'Failed to fetch episode listing via Cinemagoer: %s' % exc)
        return
    except Exception:
        return

    episodes = ((episodes_data or {}).get('data') or {}).get('episodes') or {}
    season_data = episodes.get(season) or episodes.get(str(season)) or {}
    episode_movie = season_data.get(episode_number) or season_data.get(str(episode_number))
    if not episode_movie:
        return

    __apply_episode_details(meta, episode_movie, series_movie)

def __scrape_tvshow_year(core, meta):
    if not meta.tvshow and not meta.imdb_id:
        return

    imdb_client = __get_imdb_client(core)

    try:
        lookup = None
        if meta.imdb_id:
            try:
                lookup = imdb_client.get_movie(__normalize_imdb_id(meta.imdb_id))
            except IMDbError as exc:
                logger.error(lambda: 'Failed to resolve IMDb title %s: %s' % (meta.imdb_id, exc))
        if lookup is None and meta.tvshow:
            search_results = imdb_client.search_movie(meta.tvshow)
            lookup = __select_best_result(search_results, meta.tvshow, meta.tvshow_year, __tv_kinds)

        if lookup is None:
            return

        if (lookup.get('kind') or '').lower() == 'episode' and meta.tvshow:
            search_results = imdb_client.search_movie(meta.tvshow)
            lookup = __select_best_result(search_results, meta.tvshow, meta.tvshow_year, __tv_kinds)

        if lookup is None:
            return

        __apply_series_details(meta, lookup)
        if meta.tvshow_year:
            __store_tvshow_year(meta.imdb_id or __format_imdb_id(lookup.movieID), meta.tvshow_year)
    except IMDbError as exc:
        logger.error(lambda: 'Cinemagoer failed to determine tv show year: %s' % exc)

def __scrape_imdb_id(core, meta):
    if meta.title == '' and meta.tvshow == '':
        return

    imdb_client = __get_imdb_client(core)
    is_movie = meta.season == '' and meta.episode == ''

    try:
        if is_movie:
            results = imdb_client.search_movie(meta.title)
            movie = __select_best_result(results, meta.title, meta.year)
            if not movie:
                return

            meta.imdb_id = __format_imdb_id(movie.movieID)
            __apply_movie_details(meta, movie)
            return

        show_title = meta.tvshow or meta.title
        if not show_title:
            return

        results = imdb_client.search_movie(show_title)
        series_movie = __select_best_result(results, show_title, meta.tvshow_year or meta.year, __tv_kinds)
        if not series_movie:
            return

        meta.imdb_id = __format_imdb_id(series_movie.movieID)
        __apply_series_details(meta, series_movie)

        if meta.season and meta.episode:
            __populate_episode_from_series(imdb_client, meta, series_movie)
    except IMDbError as exc:
        logger.error(lambda: 'Cinemagoer failed to resolve IMDb id: %s' % exc)

def __update_info_from_imdb(core, meta):
    if meta.imdb_id == '':
        return

    imdb_client = __get_imdb_client(core)
    try:
        movie = imdb_client.get_movie(__normalize_imdb_id(meta.imdb_id))
    except IMDbError as exc:
        logger.error(lambda: 'Cinemagoer failed to fetch title %s: %s' % (meta.imdb_id, exc))
        return
    except Exception:
        return

    kind = (movie.get('kind') or '').lower()

    if kind in __tv_kinds:
        __apply_series_details(meta, movie)
        if meta.season and meta.episode:
            __populate_episode_from_series(imdb_client, meta, movie)
    elif kind == 'episode':
        if not meta.tvshow and movie.get('tv series title'):
            meta.tvshow = movie.get('tv series title')
        if not meta.tvshow_year and meta.tvshow:
            __scrape_tvshow_year(core, meta)
        __apply_episode_details(meta, movie)
    else:
        __apply_movie_details(meta, movie)

def __get_basic_info(core):
    """
    Gets basic information about the currently playing video from Kodi.

    Args:
        core (module): The core module.

    Returns:
        DictAsObject: The basic information about the currently playing video.
    """
    meta = utils.DictAsObject({})
    filename_and_path = ''

    if core.kodi.get_version_major() >= 20:  # The InfoTagVideo API was added in kodi v20
        video_info = xbmc.Player().getVideoInfoTag()

        meta.year = video_info.getYear()
        meta.season = video_info.getSeason()
        meta.episode = video_info.getEpisode()
        meta.tvshow = video_info.getTVShowTitle()

        meta.title = video_info.getOriginalTitle()
        if meta.title == '':
            meta.title = video_info.getTitle()

        meta.imdb_id = video_info.getUniqueID('imdb')
        filename_and_path = video_info.getFilenameAndPath()

    if not meta.year:
        meta.year = xbmc.getInfoLabel('VideoPlayer.Year')
    if not meta.season:
        meta.season = xbmc.getInfoLabel('VideoPlayer.Season')
    if not meta.episode:
        meta.episode = xbmc.getInfoLabel('VideoPlayer.Episode')
    if not meta.tvshow:
        meta.tvshow = xbmc.getInfoLabel('VideoPlayer.TVShowTitle')

    if not meta.title:
        meta.title = xbmc.getInfoLabel('VideoPlayer.OriginalTitle')
        if meta.title == '':
            meta.title = xbmc.getInfoLabel('VideoPlayer.Title')

    if not meta.imdb_id:
        meta.imdb_id = xbmc.getInfoLabel('VideoPlayer.IMDBNumber')
    if not filename_and_path:
        filename_and_path = xbmc.getInfoLabel('Player.FilenameAndPath')

    meta.tvshow_year = ''
    meta.filename = __get_filename(meta.title)
    meta.filename_without_ext = meta.filename

    if meta.imdb_id == '':
        regex_result = re.search(r'.*(tt\d{7,}).*', filename_and_path, re.IGNORECASE)
        if regex_result:
            meta.imdb_id = regex_result.group(1)

    if meta.season == '' or meta.episode == '':
        filename_info = utils.extract_season_episode(meta.filename, zfill=0)
        filename_path_info = utils.extract_season_episode(filename_and_path, zfill=0)
        meta.season = meta.season or filename_path_info.season or filename_info.season
        meta.episode = meta.episode or filename_path_info.episode or filename_info.episode

    return meta

def __is_imdb_id(id: str) -> bool:
    """
    Checks if an ID is an IMDb ID.

    Args:
        id (str): The ID to check.

    Returns:
        bool: True if the ID is an IMDb ID, False otherwise.
    """
    return id.startswith(__imdb_id_prefix)

def get_meta(core):
    """
    Gets the metadata of the currently playing video.

    Args:
        core (module): The core module.

    Returns:
        DictAsObject: The metadata of the currently playing video.
    """
    meta = __get_basic_info(core)

    # Depending on the used scraper, the imdb_id returned by Kodi might not actually be an IMDB ID.
    if meta.imdb_id == '' or not __is_imdb_id(meta.imdb_id):
        cache_key = cache.hash_data(meta)
        imdb_id_cache = cache.get_imdb_id_cache()
        meta.imdb_id = imdb_id_cache.get(cache_key, '')

        if meta.imdb_id == '':
            __scrape_imdb_id(core, meta)

            if meta.imdb_id != '':
                imdb_id_cache[cache_key] = meta.imdb_id
                cache.save_imdb_id_cache(imdb_id_cache)

            if meta.tvshow_year != '':
                tvshow_years_cache = cache.get_tvshow_years_cache()
                tvshow_years_cache[meta.imdb_id] = meta.tvshow_year
                cache.save_tvshow_years_cache(tvshow_years_cache)

    if meta.imdb_id != '':
        __update_info_from_imdb(core, meta)

    meta_cache = cache.get_meta_cache()
    if meta.imdb_id != '' and meta_cache.imdb_id == meta.imdb_id and meta_cache.filename == meta.filename:
        meta = meta_cache
    else:
        meta.filesize = ''
        meta.filehash = ''

        try:
            filepath = xbmc.Player().getPlayingFile()
            __set_size_and_hash(core, meta, filepath)
        except:
            import traceback
            traceback.print_exc()

        try:
            meta.filename_without_ext = os.path.splitext(meta.filename)[0]
        except: pass

        meta_json = json.dumps(meta, indent=2)
        logger.debug(meta_json)

        meta = json.loads(meta_json)
        meta = utils.DictAsObject(meta)

        for key in meta.keys():
            value = utils.strip_non_ascii_and_unprintable(meta[key])
            meta[key] = str(value).strip()

        cache.save_meta_cache(meta)

    meta.is_tvshow = meta.tvshow != ''
    meta.is_movie = not meta.is_tvshow

    tvshow_year_requiring_service_enabled = (
        get_bool_setting('podnadpisi', 'enabled') or
        get_bool_setting('addic7ed', 'enabled')
    )

    if meta.is_tvshow and meta.imdb_id != '' and meta.tvshow_year == '' and tvshow_year_requiring_service_enabled:
        tvshow_years_cache = cache.get_tvshow_years_cache()
        tvshow_year = tvshow_years_cache.get(meta.imdb_id, '')

        if tvshow_year != '':
            meta.tvshow_year = tvshow_year
        else:
            meta.tvshow_year_thread = threading.Thread(target=__scrape_tvshow_year, args=(core, meta))
            meta.tvshow_year_thread.start()

    try:
        if len(meta.imdb_id) > 2:
            meta.imdb_id_as_int = int(meta.imdb_id[2:].lstrip('0'))
    except: pass

    return meta
