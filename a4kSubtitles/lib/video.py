# -*- coding: utf-8 -*-

import os
import json
import struct
import hashlib
import re
import threading

from imdb import IMDb, IMDbError

from .kodi import xbmc, xbmcvfs, get_bool_setting, get_int_setting
from . import kodi, logger, cache, utils

__64k = 65536
__longlong_format_char = 'q'
__byte_size = struct.calcsize(__longlong_format_char)
__imdb_id_prefix = 'tt'
__cinemagoer_cache_dirname = 'cinemagoer-cache'

__cinemagoer_lock = threading.Lock()
__cinemagoer_client = None

def __format_imdb_id(movie_id):
    if not movie_id:
        return ''

    movie_id = str(movie_id)
    if movie_id.startswith(__imdb_id_prefix):
        return movie_id

    return '%s%s' % (__imdb_id_prefix, movie_id.zfill(7))

def __extract_year(value):
    if value is None:
        return None

    if isinstance(value, int):
        return value

    if isinstance(value, str):
        year_match = re.search(r'(\d{4})', value)
        if year_match:
            try:
                return int(year_match.group(1))
            except ValueError:
                return None

    return None

def __get_imdb_client(core):
    global __cinemagoer_client

    if __cinemagoer_client is not None:
        return __cinemagoer_client

    with __cinemagoer_lock:
        if __cinemagoer_client is not None:
            return __cinemagoer_client

        cache_dir = os.path.join(kodi.addon_profile, __cinemagoer_cache_dirname)
        try:
            if not xbmcvfs.exists(cache_dir):
                xbmcvfs.mkdirs(cache_dir)
        except Exception as exc:
            logger.error(lambda: 'Unable to prepare Cinemagoer cache directory %s: %s' % (cache_dir, exc))

        try:
            timeout = get_int_setting('general.timeout')
        except Exception:
            timeout = 10

        try:
            client = IMDb('http', reraiseExceptions=True, timeout=timeout, adultSearch=False)
        except Exception as exc:
            logger.error(lambda: 'Failed to initialize Cinemagoer client: %s' % exc)
            raise

        try:
            client.cache_directory = cache_dir
        except Exception:
            pass

        __cinemagoer_client = client

    return __cinemagoer_client

def __store_tvshow_year(meta, year, imdb_id=None):
    if year is None:
        return

    meta.tvshow_year = str(year)

    try:
        tvshow_years_cache = cache.get_tvshow_years_cache()
        cache_key = imdb_id or meta.imdb_id
        if cache_key:
            tvshow_years_cache[cache_key] = meta.tvshow_year
        cache.save_tvshow_years_cache(tvshow_years_cache)
    except Exception as exc:
        logger.error(lambda: 'Failed to persist Cinemagoer TV show year: %s' % exc)

def __get_episode_from_listing(listing, season_number, episode_number):
    if not listing:
        return None

    data = listing.get('data') if isinstance(listing, dict) else None
    if not data:
        data = listing

    episodes_by_season = data.get('episodes') if isinstance(data, dict) else None
    if not episodes_by_season:
        return None

    season_entry = episodes_by_season.get(season_number) or episodes_by_season.get(str(season_number))
    if not season_entry:
        if isinstance(episodes_by_season, dict):
            # Sometimes keys are strings that look like integers
            for key, value in episodes_by_season.items():
                try:
                    if int(key) == season_number:
                        season_entry = value
                        break
                except Exception:
                    continue

    if not season_entry:
        return None

    if isinstance(season_entry, list):
        index = episode_number - 1
        if 0 <= index < len(season_entry):
            return season_entry[index]
        return None

    return season_entry.get(episode_number) or season_entry.get(str(episode_number))

def __get_value(data, key):
    if data is None:
        return None

    try:
        value = data.get(key)
        if value is not None:
            return value
    except Exception:
        pass

    return getattr(data, key, None)

def __get_movie_id(data):
    value = __get_value(data, 'movieID')
    if value:
        return value

    return getattr(data, 'movieID', None)

def __apply_movie_info(meta, movie):
    meta.imdb_id = __format_imdb_id(__get_movie_id(movie))

    title = __get_value(movie, 'title')
    if title:
        meta.title = title

    year = __extract_year(__get_value(movie, 'year'))
    if year:
        meta.year = str(year)

    meta.tvshow = ''
    if meta.tvshow_year != '':
        meta.tvshow_year = ''
    meta.season = ''
    meta.episode = ''

def __apply_series_info(meta, series):
    meta.imdb_id = __format_imdb_id(__get_movie_id(series))

    title = __get_value(series, 'title')
    if title:
        meta.tvshow = title

    series_year = __extract_year(__get_value(series, 'series years')) or __extract_year(__get_value(series, 'year'))
    if series_year is not None:
        __store_tvshow_year(meta, series_year, imdb_id=meta.imdb_id)

def __apply_episode_info(meta, episode, client):
    meta.imdb_id = __format_imdb_id(__get_movie_id(episode))

    title = __get_value(episode, 'title')
    if title:
        meta.title = title

    year = __extract_year(__get_value(episode, 'year'))
    if year:
        meta.year = str(year)

    season_number = __get_value(episode, 'season')
    if season_number is not None:
        meta.season = str(season_number)

    episode_number = __get_value(episode, 'episode')
    if episode_number is not None:
        meta.episode = str(episode_number)

    series = __get_value(episode, 'episode of')
    if series:
        try:
            client.update(series)
        except IMDbError:
            pass

        title = __get_value(series, 'title')
        if title:
            meta.tvshow = title

        series_year = __extract_year(__get_value(series, 'series years')) or __extract_year(__get_value(series, 'year'))
        if series_year is not None:
            series_id = __format_imdb_id(__get_movie_id(series))
            __store_tvshow_year(meta, series_year, imdb_id=series_id)

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

def __scrape_tvshow_year(core, meta):
    """Resolve the TV show debut year using Cinemagoer."""
    if meta.imdb_id == '':
        return

    imdb_id = meta.imdb_id[2:] if __is_imdb_id(meta.imdb_id) else meta.imdb_id

    try:
        client = __get_imdb_client(core)
    except Exception:
        return

    try:
        show = client.get_movie(imdb_id)
    except IMDbError as exc:
        logger.error(lambda: 'Cinemagoer failed fetching year for %s: %s' % (meta.imdb_id, exc))
        return

    if not show:
        return

    series_year = __extract_year(__get_value(show, 'series years')) or __extract_year(__get_value(show, 'year'))

    if series_year is None and (__get_value(show, 'kind') or '').lower() == 'episode':
        series = __get_value(show, 'episode of')
        if series:
            try:
                client.update(series)
            except IMDbError:
                pass
            series_year = __extract_year(__get_value(series, 'series years')) or __extract_year(__get_value(series, 'year'))

    if series_year is not None:
        __store_tvshow_year(meta, series_year)

def __scrape_imdb_id(core, meta):
    """Resolve an IMDb identifier for the current video using Cinemagoer."""
    if meta.title == '' or meta.year == '':
        return

    is_movie = meta.season == '' and meta.episode == ''
    search_title = meta.title if is_movie else meta.tvshow

    if search_title == '':
        return

    try:
        client = __get_imdb_client(core)
    except Exception:
        return

    try:
        results = client.search_movie(search_title, results=25)
    except IMDbError as exc:
        logger.error(lambda: 'Cinemagoer search failed for "%s": %s' % (search_title, exc))
        return

    if not results:
        return

    if is_movie:
        target_year = __extract_year(meta.year)
        title_lower = meta.title.lower()

        for result in results:
            kind = (__get_value(result, 'kind') or '').lower()
            if kind not in ('movie', 'tv movie', 'feature film', 'film'):
                continue

            result_title = __get_value(result, 'title')
            if result_title and result_title.lower() != title_lower:
                continue

            result_year = __extract_year(__get_value(result, 'year'))
            if target_year and result_year and result_year != target_year:
                continue

            meta.imdb_id = __format_imdb_id(__get_movie_id(result))
            if result_year:
                meta.year = str(result_year)
            if result_title:
                meta.title = result_title
            return

        return

    # TV show / episode handling
    episode_year = __extract_year(meta.year)
    season_number = None
    episode_number = None
    try:
        season_number = int(meta.season) if meta.season != '' else None
        episode_number = int(meta.episode) if meta.episode != '' else None
    except ValueError:
        season_number = None
        episode_number = None

    for result in results:
        kind = (__get_value(result, 'kind') or '').lower()
        if kind not in ('tv series', 'tv mini series', 'tv mini-series', 'tv special'):
            continue

        series_id = __format_imdb_id(__get_movie_id(result))
        meta.imdb_id = series_id
        meta.tvshow = __get_value(result, 'title') or meta.tvshow

        try:
            client.update(result)
        except IMDbError as exc:
            logger.error(lambda: 'Cinemagoer update failed for series %s: %s' % (series_id, exc))

        series_year = __extract_year(__get_value(result, 'series years')) or __extract_year(__get_value(result, 'year'))
        if series_year is not None:
            __store_tvshow_year(meta, series_year)

        if not season_number or not episode_number:
            return

        try:
            listing = client.get_movie_episodes(result.movieID, season_nums={season_number})
        except IMDbError as exc:
            logger.error(lambda: 'Cinemagoer episode lookup failed for %s season %s: %s' % (series_id, season_number, exc))
            return

        episode_entry = __get_episode_from_listing(listing, season_number, episode_number)
        if not episode_entry:
            continue

        title = __get_value(episode_entry, 'title')
        if title:
            meta.title = title

        entry_year = __extract_year(__get_value(episode_entry, 'year')) or episode_year
        if entry_year:
            meta.year = str(entry_year)

        episode_id = __format_imdb_id(__get_movie_id(episode_entry))
        if episode_id:
            meta.imdb_id = episode_id
        return

def __update_info_from_imdb(core, meta):
    """Refresh metadata for the current video using Cinemagoer."""
    if meta.imdb_id == '':
        return

    try:
        client = __get_imdb_client(core)
    except Exception:
        return

    imdb_id = meta.imdb_id[2:] if __is_imdb_id(meta.imdb_id) else meta.imdb_id

    try:
        item = client.get_movie(imdb_id)
    except IMDbError as exc:
        logger.error(lambda: 'Cinemagoer failed to retrieve %s: %s' % (meta.imdb_id, exc))
        return

    if not item:
        return

    kind = (__get_value(item, 'kind') or '').lower()

    if kind == 'episode':
        __apply_episode_info(meta, item, client)
        return

    if kind in ('tv series', 'tv mini series', 'tv mini-series'):
        __apply_series_info(meta, item)

        try:
            season_number = int(meta.season)
            episode_number = int(meta.episode)
        except Exception:
            season_number = None
            episode_number = None

        if season_number and episode_number:
            try:
                listing = client.get_movie_episodes(item.movieID, season_nums={season_number})
            except IMDbError as exc:
                logger.error(lambda: 'Cinemagoer episode refresh failed for %s: %s' % (meta.imdb_id, exc))
                return

            episode = __get_episode_from_listing(listing, season_number, episode_number)
            if episode:
                __apply_episode_info(meta, episode, client)
        return

    __apply_movie_info(meta, item)

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
