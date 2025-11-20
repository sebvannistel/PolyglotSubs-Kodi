# -*- coding: utf-8 -*-

import hashlib
import json
import os
import sys

from . import kodi, utils

try:
    from .third_party.diskcache import Cache
except ImportError:
    # Fallback if third_party import fails, though it shouldn't in production
    from diskcache import Cache

# Legacy file paths - kept for migration if needed, or we can ignore them.
# We will use a directory for diskcache.
__cache_dir = os.path.join(kodi.addon_profile, "cache")
if not os.path.exists(__cache_dir):
    try:
        os.makedirs(__cache_dir)
    except OSError:
        pass

# Initialize DiskCache
# We use a single cache instance for everything, using keys to separate data.
# Or we could use separate Caches. Using one is simpler.
# We set a size limit (e.g., 100MB) and cull limit.
__cache = Cache(__cache_dir, size_limit=100 * 1024 * 1024)

# Keys for different cache types
KEY_META = "meta_cache"
KEY_TVSHOW_YEARS = "tvshow_years_cache"
KEY_IMDB_ID = "imdb_id_cache"
KEY_TOKENS = "tokens_cache"
KEY_LAST_RESULTS = "last_results"

# Exposed for backward compatibility with search.py, though we will update search.py
results_filepath = os.path.join(kodi.addon_profile, "last_results.json")


def hash_data(data):
    """
    Hashes a dictionary.

    Args:
        data (dict): The dictionary to hash.

    Returns:
        str: The SHA256 hash of the dictionary.
    """
    json_data = json.dumps(data).encode(utils.default_encoding)
    return hashlib.sha256(json_data).hexdigest()


def get_meta_hash(meta):
    """
    Hashes the metadata of a video.

    Args:
        meta (dict): The metadata of the video.

    Returns:
        str: The SHA256 hash of the metadata.
    """
    return hash_data(
        {
            "imdb_id": meta.imdb_id,
            "filename": meta.filename,
            "languages": meta.languages,
            "preferredlanguage": meta.preferredlanguage,
        }
    )


def __get_data(key, default=None):
    if default is None:
        default = {}
    return utils.Box(__cache.get(key, default), default_box=True, default_box_attr=None)


def __save_data(key, data):
    __cache[key] = dict(data)  # Ensure it's a dict before saving


def get_meta_cache():
    """
    Gets the metadata cache.

    Returns:
        Box: The metadata cache.
    """
    meta_cache = __get_data(KEY_META)
    meta_cache.setdefault("imdb_id", "")
    meta_cache.setdefault("tvshow_year", "")
    return meta_cache


def save_meta_cache(meta_cache):
    """
    Saves the metadata cache.

    Args:
        meta_cache (dict): The metadata cache to save.
    """
    return __save_data(KEY_META, meta_cache)


def get_tvshow_years_cache():
    """
    Gets the TV show years cache.

    Returns:
        Box: The TV show years cache.
    """
    return __get_data(KEY_TVSHOW_YEARS)


def save_tvshow_years_cache(data):
    """
    Saves the TV show years cache.

    Args:
        data (dict): The TV show years cache to save.
    """
    return __save_data(KEY_TVSHOW_YEARS, data)


def get_imdb_id_cache():
    """
    Gets the IMDB ID cache.

    Returns:
        Box: The IMDB ID cache.
    """
    return __get_data(KEY_IMDB_ID)


def save_imdb_id_cache(data):
    """
    Saves the IMDB ID cache.

    Args:
        data (dict): The IMDB ID cache to save.
    """
    return __save_data(KEY_IMDB_ID, data)


def get_tokens_cache():
    """
    Gets the tokens cache.

    Returns:
        Box: The tokens cache.
    """
    return __get_data(KEY_TOKENS)


def save_tokens_cache(data):
    """
    Saves the tokens cache.

    Args:
        data (dict): The tokens cache to save.
    """
    return __save_data(KEY_TOKENS, data)


def get_last_results(meta_hash_check=None):
    """
    Gets the last results from the cache.

    Args:
        meta_hash_check (str, optional): If provided, checks if the cached hash matches.

    Returns:
        dict: The last results object (keys: hash, timestamp, results), or None.
    """
    data = __cache.get(KEY_LAST_RESULTS)
    if data and meta_hash_check and data.get("hash") != meta_hash_check:
        return None
    return data


def save_last_results(data):
    """
    Saves the last results to the cache.

    Args:
        data (dict): The results data (hash, timestamp, results).
    """
    __cache[KEY_LAST_RESULTS] = data
