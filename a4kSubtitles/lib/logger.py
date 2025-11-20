# -*- coding: utf-8 -*-

from .kodi import addon_id, get_kodi_setting, xbmc

__get_debug_logenabled_err = False


def __get_debug_logenabled():
    """
    Checks if debug logging is enabled in Kodi.

    Returns:
        bool: True if debug logging is enabled, False otherwise.
    """
    global __get_debug_logenabled_err
    if __get_debug_logenabled_err:
        return False

    try:
        return get_kodi_setting("debug.showloginfo", log_error=False)
    except:
        __get_debug_logenabled_err = True

    return False


try:
    notice_type = xbmc.LOGNOTICE
except:
    notice_type = xbmc.LOGINFO


def __log(message, level):
    """
    Logs a message to the Kodi log.

    Args:
        message (str or function): The message to log. If it's a function, it will be called to get the message.
        level (int): The log level.
    """
    if level == notice_type and not __get_debug_logenabled():
        return

    is_lazy_msg = callable(message)
    if is_lazy_msg:
        message = message()

    xbmc.log("{0}: {1}".format(addon_id, message), level)


def error(message):
    """
    Logs an error message.

    Args:
        message (str or function): The message to log. If it's a function, it will be called to get the message.
    """
    __log(message, xbmc.LOGERROR)


def debug(message):
    """
    Logs a debug message.

    Args:
        message (str or function): The message to log. If it's a function, it will be called to get the message.
    """
    __log(message, notice_type)


def warning(message):
    """
    Logs a warning message.

    Args:
        message (str or function): The message to log. If it's a function, it will be called to get the message.
    """
    __log(message, xbmc.LOGWARNING)
