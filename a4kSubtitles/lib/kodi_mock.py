# -*- coding: utf-8 -*-
# flake8: noqa

import os
import shutil

from zipfile import ZipFile
from xml.etree import ElementTree
from .third_party import iso639

try:  # pragma: no cover
    from urlparse import unquote
except ImportError:
    from urllib.parse import unquote

# xbmc
xbmc = lambda: None
xbmc.translatePath = lambda p: p
xbmc.getInfoLabel = lambda t: ''
xbmc.executeJSONRPC = lambda _: '{ "result": { "value": [] } }'
xbmc.executebuiltin = lambda _: None
xbmc.getCleanMovieTitle = lambda t: t
xbmc.getLanguage = lambda *_, **__: 'English'
xbmc.getCondVisibility = lambda _: False

xbmc.convertLanguage = lambda l, f: iso639.Lang(l).asdict()[f]
xbmc.ISO_639_1 = 'pt1'
xbmc.ISO_639_2 = 'pt2t'
xbmc.ENGLISH_NAME = 'name'

__player = lambda: None
__player.isPlayingVideo = lambda: None
__player.getPlayingFile = lambda: ''
__player.getAvailableSubtitleStreams = lambda: []
__player.setSubtitles = lambda s: None
__player.setSubtitleStream = lambda i: None
xbmc.Player = lambda: __player

__monitor = lambda: None
__monitor.abortRequested = lambda: False
__monitor.waitForAbort = lambda _: False
xbmc.Monitor = lambda: __monitor

def __log(msg, label):
    print(msg)
xbmc.log = __log
xbmc.LOGDEBUG = 'debug'
xbmc.LOGINFO = 'info'
xbmc.LOGERROR = 'error'
xbmc.LOGNOTICE = 'notice'

# xbmcaddon
xbmcaddon = lambda: None
__addon = lambda: None
def __get_addon_info(name):
    """
    Mocks the getAddonInfo method of the xbmcaddon.Addon class.

    Args:
        name (str): The name of the addon info to get.

    Returns:
        str: The value of the addon info.
    """
    if name == 'id':
        return 'service.subtitles.polyglotsubs-kodi'
    elif name == 'name':
        return 'a4ksubtitles'
    elif name == 'version':
        tree = ElementTree.parse(os.path.join(os.path.dirname(__file__), '..', '..', 'addon.xml'))
        root = tree.getroot()
        return root.get('version')
    elif name == 'profile':
        return os.path.join(os.path.dirname(__file__), '../../tmp')
__addon.getAddonInfo = __get_addon_info
__addon.getSetting = lambda _: ''
# Allow Addon() to be called with or without parameters
xbmcaddon.Addon = lambda *_, **__: __addon

# xbmcplugin
xbmcplugin = lambda: None
def __add_directory_item(*args, **kwargs):
    """Mocks the addDirectoryItem method of the xbmcplugin class."""
    return None
xbmcplugin.addDirectoryItem = __add_directory_item

# xbmcgui
xbmcgui = lambda: None
__listitem = lambda: None
__listitem.setProperty = lambda _, __: None
def __create_listitem(*args, **kwargs):
    """Mocks the ListItem method of the xbmcgui class."""
    return __listitem
xbmcgui.ListItem = __create_listitem

# xbmcvfs
xbmcvfs = lambda: None
def __mkdirs(f):
    """Mocks the mkdirs method of the xbmcvfs class."""
    try: os.makedirs(f)
    except Exception: pass
xbmcvfs.mkdirs = __mkdirs

__archive_proto = 'archive://'
def __listdir(archive_uri):
    """
    Mocks the listdir method of the xbmcvfs class.

    Args:
        archive_uri (str): The URI of the archive to list.

    Returns:
        tuple: A tuple containing two lists: directories and files.
    """
    archive_path = unquote(archive_uri).replace(__archive_proto, '')
    with ZipFile(archive_path, 'r') as zip_obj:
        return ([], zip_obj.namelist())
xbmcvfs.listdir = __listdir

def __copy(src_uri, dest):
    """
    Mocks the copy method of the xbmcvfs class.

    Args:
        src_uri (str): The source URI to copy.
        dest (str): The destination path to copy to.
    """
    archive_path = unquote(src_uri[:src_uri.find('.zip') + 4]).replace(__archive_proto, '')
    member = unquote(src_uri[src_uri.find('.zip') + 5:]).replace(__archive_proto, '')
    with ZipFile(archive_path, 'r') as zip_obj:
        dest_dir = os.path.dirname(dest)
        zip_obj.extract(member, dest_dir)
        os.rename(os.path.join(dest_dir, member), dest)
xbmcvfs.copy = __copy

def __File(_):
    """Mocks the File class of the xbmcvfs class."""
    return __File
__File.size = lambda: 0
__File.hash = lambda: 0
__File.close = lambda: None
xbmcvfs.File = __File
