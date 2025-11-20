# -*- coding: utf-8 -*-

import importlib
import json
import logging
import os
import re
import sys

# The mocking is now handled by tests/kodi_mocks.py and injected into sys.modules via tests/conftest.py
# when running tests. In production (inside Kodi), these imports will succeed.
import xbmc
import xbmcaddon
import xbmcgui
import xbmcplugin
import xbmcvfs

kodi = sys.modules[__name__]

addon = xbmcaddon.Addon()
addon_id = addon.getAddonInfo("id")
addon_name = addon.getAddonInfo("name")
addon_version = addon.getAddonInfo("version")
addon_icon = addon.getAddonInfo("icon")
try:
    addon_profile = xbmcvfs.translatePath(addon.getAddonInfo("profile"))
except AttributeError as e:
    logging.getLogger(__name__).debug("xbmcvfs.translatePath not available: %s", e)
    addon_profile = xbmc.translatePath(addon.getAddonInfo("profile"))


def json_rpc(method, params, log_error=True):  # pragma: no cover
    """
    Executes a JSON-RPC method.

    Args:
        method (str): The JSON-RPC method to execute.
        params (dict): The parameters for the method.
        log_error (bool, optional): Whether to log errors. Defaults to True.

    Returns:
        The result of the JSON-RPC method, or None if an error occurred.
    """
    try:
        result = xbmc.executeJSONRPC(
            json.dumps(
                {"jsonrpc": "2.0", "method": method, "id": 1, "params": params or {}}
            )
        )
        if "error" in result and log_error:
            from . import logger

            logger.error(result)
        result = json.loads(result)["result"]
        try:
            return result["value"]
        except (KeyError, TypeError) as e:
            if log_error:
                from . import logger

                logger.error("Invalid JSON-RPC result structure: %s" % e)
            return result
    except KeyError:
        return None


def get_kodi_setting(setting, log_error=True):  # pragma: no cover
    """
    Gets a Kodi setting.

    Args:
        setting (str): The setting to get.
        log_error (bool, optional): Whether to log errors. Defaults to True.

    Returns:
        The value of the setting, or None if an error occurred.
    """
    return json_rpc("Settings.GetSettingValue", {"setting": setting}, log_error)


def get_kodi_player_subtitles(log_error=True):  # pragma: no cover
    """
    Gets the subtitles of the current player.

    Args:
        log_error (bool, optional): Whether to log errors. Defaults to True.

    Returns:
        The subtitles of the current player, or None if an error occurred.
    """
    return json_rpc(
        "Player.GetProperties",
        {
            "playerid": 1,
            "properties": ["subtitleenabled", "currentsubtitle", "subtitles"],
        },
        log_error,
    )


def notification(text, time=3000):  # pragma: no cover
    """
    Shows a notification.

    Args:
        text (str): The text to show.
        time (int, optional): The time to show the notification in milliseconds. Defaults to 3000.
    """
    xbmc.executebuiltin(
        "Notification(%s, %s, %d, %s)" % (addon_name, text, time, addon_icon)
    )


def get_progress_dialog():  # pragma: no cover
    """
    Gets a progress dialog.

    Returns:
        A progress dialog wrapper.
    """
    wrapper = lambda: None
    wrapper.dialog = None
    wrapper.latest_update = None

    def open():
        wrapper.dialog = xbmcgui.DialogProgress()
        wrapper.dialog.create(addon_name, "Searching...")
        if wrapper.latest_update:
            (progress, text) = wrapper.latest_update
            wrapper.dialog.update(progress, text)

    def close():
        if wrapper.dialog:
            wrapper.dialog.close()
            wrapper.dialog = None

    def iscanceled():
        return wrapper.dialog.iscanceled() if wrapper.dialog else False

    def update(progress, text):
        if wrapper.dialog:
            wrapper.dialog.update(progress, text)
        else:
            wrapper.latest_update = (progress, text)

    wrapper.open = open
    wrapper.close = close
    wrapper.iscanceled = iscanceled
    wrapper.update = update
    return wrapper


def update_progress(core):  # pragma: no cover
    """
    Updates the progress dialog.

    Args:
        core: The core module.
    """
    if core.progress_dialog is None or core.progress_dialog.iscanceled():
        return

    text = re.sub(r"\|+", "|", core.progress_text).strip("|")
    total = core.progress_text.count("|") + 1
    count = text.count("|") + 1 if text != "" else 0
    progress = int(float(total - count) / total * 100)
    core.progress_dialog.update(progress, text.replace("|", " | "))


def parse_language(language):  # pragma: no cover
    """
    Parses a language string.

    Args:
        language (str): The language string to parse.

    Returns:
        str: The parsed language.
    """
    if language == "original":
        audio_streams = xbmc.Player().getAvailableAudioStreams()
        if len(audio_streams) == 0:
            return None
        return xbmc.convertLanguage(audio_streams[0], xbmc.ENGLISH_NAME)
    elif language == "default":
        return xbmc.getLanguage()
    elif language == "none":
        return None
    elif language == "forced_only":
        return parse_language(get_kodi_setting("locale.audiolanguage"))
    else:
        return language


def create_listitem(item):  # pragma: no cover
    """
    Creates a list item.

    Args:
        item (dict): The item to create a list item for.

    Returns:
        xbmcgui.ListItem: The created list item.
    """
    (item_name, item_ext) = os.path.splitext(item["name"])
    item_name = item_name.replace(".", " ")
    item_ext = item_ext.upper()[1:]
    item_service = item["service"]
    item_color = item.get("color", "white")

    args = {
        "label": item["lang"],
        "label2": "%s ([B]%s[/B]) ([B][COLOR %s]%s[/COLOR][/B])"
        % (item_name, item_ext, item_color, item_service),
        "offscreen": True,
    }

    listitem = xbmcgui.ListItem(**args)
    listitem.setArt(
        {
            "icon": str(item["rating"]),
            "thumb": item["lang_code"],
        }
    )
    listitem.setProperty("sync", item["sync"])
    listitem.setProperty("hearing_imp", item["impaired"])

    return listitem


def get_setting(group, id=None):
    """
    Gets an addon setting.

    Args:
        group (str): The group of the setting.
        id (str, optional): The ID of the setting. Defaults to None.

    Returns:
        str: The value of the setting.
    """
    key = "%s.%s" % (group, id) if id else group
    return addon.getSetting(key).strip()


def get_int_setting(group, id=None):
    """
    Gets an addon setting as an integer.

    Args:
        group (str): The group of the setting.
        id (str, optional): The ID of the setting. Defaults to None.

    Returns:
        int: The value of the setting.
    """
    return int(get_setting(group, id))


def get_bool_setting(group, id=None):
    """
    Gets an addon setting as a boolean.

    Args:
        group (str): The group of the setting.
        id (str, optional): The ID of the setting. Defaults to None.

    Returns:
        bool: The value of the setting.
    """
    return get_setting(group, id).lower() == "true"


def get_versionstring():
    """
    Gets the Kodi version string.

    Returns:
        str: The Kodi version string.
    """
    return xbmc.getInfoLabel("System.BuildVersionCode")


def get_version():
    """
    Gets the Kodi version as a list of integers.

    Returns:
        list: The Kodi version as a list of integers.
    """
    return list(map(int, get_versionstring().split(".")))


def get_version_major():
    """
    Gets the major Kodi version.

    Returns:
        int: The major Kodi version.
    """
    return get_version()[0]


def get_version_minor():
    """
    Gets the minor Kodi version.

    Returns:
        int: The minor Kodi version.
    """
    return get_version()[1]


def get_version_patch():
    """
    Gets the patch Kodi version.

    Returns:
        int: The patch Kodi version.
    """
    return get_version()[2]
