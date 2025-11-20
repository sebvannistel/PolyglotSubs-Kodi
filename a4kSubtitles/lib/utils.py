# -*- coding: utf-8 -*-

import json
import os
import re
import shutil
import string
import sys

try:
    JSONDecodeError = json.JSONDecodeError
except AttributeError:  # pragma: no cover
    JSONDecodeError = ValueError

from . import kodi, logger

try:
    import iso639
    from iso639.exceptions import (
        DeprecatedLanguageValue,
        InvalidLanguageValue,
    )
    from .third_party import chardet
    from guessit import guessit
except ImportError as e:
    logger.error("Failed to import third-party libraries: %s" % e)

try:  # pragma: no cover
    from urllib import quote_plus

    import Queue as queue
    from StringIO import StringIO
    from urlparse import parse_qsl, unquote
except ImportError:
    import queue
    from io import StringIO
    from urllib.parse import parse_qsl, quote_plus, unquote

    unicode = lambda v: v

__url_regex = r"[a-z0-9][a-z0-9-]{0,5}[a-z0-9]\.[a-z0-9]{2,20}\.[a-z]{2,5}"
__credit_part_regex = r"(sync|synced|fix|fixed|corrected|corrections)"
__credit_regex = __credit_part_regex + r" ?&? ?" + __credit_part_regex + r"? by"

default_encoding = "utf-8"
base_encoding = "raw_unicode_escape"
cp1251_garbled = "аеио".encode("cp1251").decode("raw_unicode_escape")
koi8r_garbled = "аеио".encode("koi8-r").decode("raw_unicode_escape")
code_pages = {
    "ara": "cp1256",
    "ar": "cp1256",
    "ell": "cp1253",
    "el": "cp1253",
    "heb": "cp1255",
    "he": "cp1255",
    "tur": "cp1254",
    "tr": "cp1254",
    "rus": "cp1251",
    "ru": "cp1251",
    "bg": "cp1251",
}

zip_utf8_flag = 0x800
py3_zip_missing_utf8_flag_fallback_encoding = "cp437"

py2 = sys.version_info[0] == 2
py3 = not py2

temp_dir = os.path.join(kodi.addon_profile, "temp")
data_dir = os.path.join(kodi.addon_profile, "data")


class DictAsObject(dict):
    """
    A dictionary that allows its keys to be accessed as attributes.

    Example:
        >>> d = DictAsObject({'a': 1})
        >>> d.a
        1
        >>> d.b = 2
        >>> d['b']
        2
    """

    def __getattr__(self, name):
        """
        Retrieves an item as an attribute.

        Args:
            name (str): The name of the attribute (dictionary key).

        Returns:
            The value associated with the key, or None if the key does not exist.
        """
        return self.get(name, None)

    def __setattr__(self, name, value):
        """
        Sets an item as an attribute.

        Args:
            name (str): The name of the attribute (dictionary key).
            value: The value to set.
        """
        self[name] = value


def get_all_relative_entries(relative_file, ext=".py", ignore_private=True):
    """
    Gets all relative entries in a directory.

    Args:
        relative_file (str): The file to get the relative entries from.
        ext (str, optional): The extension of the files to get. Defaults to ".py".
        ignore_private (bool, optional): Whether to ignore private files. Defaults to True.

    Returns:
        list: A list of relative entries.
    """
    entries = os.listdir(os.path.dirname(relative_file))
    return [
        os.path.splitext(name)[0]
        for name in entries
        if not ignore_private or not name.startswith("__") and name.endswith(ext)
    ]


def strip_non_ascii_and_unprintable(text):
    """
    Strips non-ASCII and unprintable characters from a string.

    Args:
        text (str): The string to strip.

    Returns:
        str: The stripped string.
    """
    if not isinstance(text, str) and (not py2 or not isinstance(text, unicode)):
        return str(text)

    result = "".join(char for char in text if char in string.printable)
    return result.encode("ascii", errors="ignore").decode("ascii", errors="ignore")


def slugify_filename(text):
    """
    Slugifies a filename.

    Args:
        text (str): The filename to slugify.

    Returns:
        str: The slugified filename.
    """
    return re.sub(r'[\\/*?:"<>|]', "_", text)


def get_lang_id(language, lang_format):
    """
    Gets the language ID for a language.

    Args:
        language (str): The language to get the ID for.
        lang_format (int): The format of the language ID.

    Returns:
        str: The language ID.
    """
    try:
        return get_lang_ids([language], lang_format)[0]
    except IndexError as e:
        logger.error("Language id not found: %s" % e)
        return ""


def get_lang_ids(languages, lang_format=kodi.xbmc.ISO_639_2):
    """
    Gets the language IDs for a list of languages.

    Args:
        languages (list): The list of languages to get the IDs for.
        lang_format (int, optional): The format of the language IDs. Defaults to kodi.xbmc.ISO_639_2.

    Returns:
        list: A list of language IDs.
    """
    try:
        lang_ids = []
        for language in languages:
            lang = language.lower()
            if lang in ["pb", "pob", "pt-br"] or "brazil" in lang:
                if lang_format == kodi.xbmc.ISO_639_1:
                    lang_ids.append("pt-br")
                elif lang_format == kodi.xbmc.ISO_639_2:
                    lang_ids.append("pob")
                elif lang_format == kodi.xbmc.ENGLISH_NAME:
                    lang_ids.append("Portuguese (Brazil)")
                continue

            lang = iso639.Lang(language)

            lang_id = None
            if lang_format == kodi.xbmc.ISO_639_1:
                lang_id = lang.pt1
            elif lang_format == kodi.xbmc.ISO_639_2:
                lang_id = lang.pt3
            elif lang_format == kodi.xbmc.ENGLISH_NAME:
                lang_id = lang.name

            if lang_id is not None:
                lang_ids.append(lang_id)

        return lang_ids
    except (InvalidLanguageValue, DeprecatedLanguageValue) as e:
        logger.error("Invalid language value: %s" % e)
        return []


def wait_threads(threads):
    """
    Waits for a list of threads to finish.

    Args:
        threads (list): The list of threads to wait for.
    """
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join()


def get_any_of_regex(array):
    """
    Gets a regex that matches any of the strings in an array.

    Args:
        array (list): The array of strings to match.

    Returns:
        str: The regex.
    """
    regex = r"("
    for target in array:
        regex += re.escape(target) + r"|"
    return regex[:-1] + r")"


def cleanup_subtitles(core, sub_contents):
    """
    Cleans up a subtitle file.

    Args:
        core (module): The core module.
        sub_contents (str): The contents of the subtitle file.

    Returns:
        str: The cleaned up subtitle file.
    """
    service_names_regex = get_any_of_regex(core.services.keys())
    all_lines = sub_contents.split("\n")
    cleaned_lines = []
    buffer = []
    garbage = False

    if all_lines[0].strip() != "":
        all_lines.insert(0, "")

    if all_lines[-1].strip() != "":
        all_lines.append("")

    for line in all_lines:
        line = line.strip()

        if garbage and line != "":
            continue

        garbage = False

        if line == "":
            if len(buffer) > 0:
                buffer.insert(0, "")
                cleaned_lines.extend(buffer)
                buffer = []
            continue

        line_contains_ad = (
            re.search(service_names_regex, line, re.IGNORECASE)
            or re.search(__url_regex, line, re.IGNORECASE)
            or re.search(__credit_regex, line, re.IGNORECASE)
        )

        if line_contains_ad:
            logger.debug("(detected ad) %s" % line.encode("ascii", errors="ignore"))
            if not re.match(r"^\{\d+\}\{\d+\}", line):
                garbage = True
                buffer = []
            continue

        buffer.append(line)

    if cleaned_lines[0] == "":
        cleaned_lines.pop(0)

    return "\n".join(cleaned_lines)


def open_file_wrapper(file, mode="r", encoding="utf-8"):
    """
    A wrapper for opening files that works in both Python 2 and 3.

    Args:
        file (str): The path to the file to open.
        mode (str, optional): The mode to open the file in. Defaults to "r".
        encoding (str, optional): The encoding of the file. Defaults to "utf-8".

    Returns:
        function: A function that opens the file.
    """
    if py2:
        return lambda: open(file, mode)
    return lambda: open(file, mode, encoding=encoding)


def get_json(path, filename):
    """
    Gets a JSON file.

    Args:
        path (str): The path to the directory containing the JSON file.
        filename (str): The name of the JSON file.

    Returns:
        dict: The JSON file as a dictionary, or None if an error occurred.
    """
    path = path if os.path.isdir(path) else os.path.dirname(path)
    if not filename.endswith(".json"):
        filename += ".json"

    json_path = os.path.join(path, filename)
    try:
        with open_file_wrapper(json_path)() as json_result:
            return json.load(json_result)
    except JSONDecodeError as e:
        logger.error("Failed to decode JSON file %s: %s" % (json_path, e))
        return None


def find_file_in_archive(core, namelist, exts, episode_number=""):
    """
    Finds a file in an archive.

    Args:
        core (module): The core module.
        namelist (list): The list of files in the archive.
        exts (list): The list of extensions to search for.
        episode_number (str, optional): The episode number to search for. Defaults to "".

    Returns:
        str: The name of the file, or None if no file was found.
    """
    first_ext_match = None
    exact_file = None
    for file in namelist:
        file_lower = file.lower()
        if any(file_lower.endswith(ext) for ext in exts):
            sub_meta = extract_season_episode(file_lower, True)
            if not first_ext_match:
                first_ext_match = file
            if episode_number == "" or sub_meta.episode == episode_number:
                exact_file = file
                break

    return exact_file if exact_file is not None else first_ext_match


def get_zipfile_namelist(zipfile):
    """
    Gets the namelist of a zipfile.

    Args:
        zipfile (zipfile.ZipFile): The zipfile to get the namelist from.

    Returns:
        list: The namelist of the zipfile.
    """
    infolist = zipfile.infolist()
    namelist = []

    if py2:
        for info in infolist:
            namelist.append(info.filename.decode(default_encoding))
    else:
        for info in infolist:
            filename = info.filename
            if not info.flag_bits & zip_utf8_flag:
                filename = info.filename.encode(
                    py3_zip_missing_utf8_flag_fallback_encoding
                ).decode(default_encoding)
            namelist.append(filename)

    return namelist


def extract_zipfile_member(zipfile, filename, dest):
    """
    Extracts a member from a zipfile.

    Args:
        zipfile (zipfile.ZipFile): The zipfile to extract the member from.
        filename (str): The name of the member to extract.
        dest (str): The destination to extract the member to.

    Returns:
        str: The path to the extracted member.
    """
    if py2:
        return zipfile.extract(filename.encode(default_encoding), dest)
    else:
        try:
            return zipfile.extract(filename, dest)
        except UnicodeEncodeError as e:
            logger.error("Unicode error extracting %s: %s" % (filename, e))
            filename = filename.encode(default_encoding).decode(
                py3_zip_missing_utf8_flag_fallback_encoding
            )
            return zipfile.extract(filename, dest)


def extract_season_episode(filename, episode_fallback=False, zfill=3):
    """
    Extracts the season and episode number from a filename using guessit.

    Args:
        filename (str): The filename to extract the season and episode number from.
        episode_fallback (bool, optional): (Unused with guessit) Whether to fallback to a simpler episode number extraction method.
        zfill (int, optional): The number of digits to pad the season and episode numbers with. Defaults to 3.

    Returns:
        DictAsObject: An object containing the season and episode number.
    """
    guess = guessit(filename)

    season = guess.get("season")
    episode = guess.get("episode")

    # Handle lists (multiple seasons/episodes) by taking the first one for simplicity,
    # or handling ranges if possible. The original implementation handled ranges slightly differently.
    episodes_range = range(0)

    if isinstance(season, list):
        season = season[0]

    if isinstance(episode, list):
        if len(episode) > 1 and all(isinstance(e, int) for e in episode):
            episodes_range = range(min(episode), max(episode) + 1)
        episode = episode[0]

    # Special handling for anime absolute numbers if 'episode' is missing
    if episode is None and season is None:
        # guessit often puts absolute episode numbers in 'absolute_episode' or just 'episode'
        # If it's in 'absolute_episode', we can use it as episode.
        absolute_episode = guess.get("absolute_episode")
        if absolute_episode:
             if isinstance(absolute_episode, list):
                 episode = absolute_episode[0]
             else:
                 episode = absolute_episode
    # If episode is not found but we have logic for ranges in guessit, we might need to check that.
    # But for now, let's map simple S/E.

    # If guessit returns integers, convert to string with padding.
    season_str = str(season).zfill(zfill) if season is not None else ""
    episode_str = str(episode).zfill(zfill) if episode is not None else ""

    # Fallback logic from original if guessit fails?
    # The original fallback logic was quite aggressive.
    # If guessit fails, we might want to keep the original regex as a backup if truly necessary,
    # but the goal is to replace it.

    if not episode_str and episode_fallback:
        # Original fallback logic for episode extraction
        # If no matches found, attempt to capture episode-like sequences
        fallback_pattern = re.compile(r"\bE?P?(\d{1,5})v?\d?\b", re.IGNORECASE)
        clean_filename = re.sub(
            r"[\s\.\:\;\(\)\[\]\{\}\\\/\&\€\'\`\#\@\=\$\?\!\%\+\-\_\*\^]", " ", filename
        )
        fallback_matches = fallback_pattern.findall(clean_filename)

        if fallback_matches:
            # Assuming the last number in the fallback matches is the episode number
            episode_str = fallback_matches[-1].lstrip("0").zfill(zfill)

    return DictAsObject(
        {
            "season": season_str.lstrip("0").zfill(zfill) if season_str else "",
            "episode": episode_str.lstrip("0").zfill(zfill) if episode_str else "",
            "episodes_range": episodes_range,
        }
    )
