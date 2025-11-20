# -*- coding: utf-8 -*-
import os
import sys
import json
from unittest.mock import MagicMock, Mock
from zipfile import ZipFile
try:
    from urllib.parse import unquote
except ImportError:
    from urlparse import unquote
from xml.etree import ElementTree

def create_mocks():
    # xbmc
    xbmc = MagicMock()
    xbmc.translatePath = lambda p: p
    xbmc.getInfoLabel.return_value = ""
    xbmc.executeJSONRPC.return_value = '{ "result": { "value": [] } }'
    xbmc.executebuiltin = Mock()
    xbmc.getCleanMovieTitle.side_effect = lambda t: t
    xbmc.getLanguage.return_value = "English"
    xbmc.getCondVisibility.return_value = False

    # Language conversion logic
    try:
        import iso639
        def convert_language(l, f):
            try:
                return iso639.Lang(l).asdict()[f]
            except:
                return None
        xbmc.convertLanguage.side_effect = convert_language
    except ImportError:
        xbmc.convertLanguage.return_value = "eng"

    xbmc.ISO_639_1 = "pt1"
    xbmc.ISO_639_2 = "pt2t"
    xbmc.ENGLISH_NAME = "name"
    xbmc.LOGDEBUG = "debug"
    xbmc.LOGINFO = "info"
    xbmc.LOGERROR = "error"
    xbmc.LOGNOTICE = "notice"

    # Player
    player_mock = MagicMock()
    player_mock.isPlayingVideo.return_value = None
    player_mock.getPlayingFile.return_value = ""
    player_mock.getAvailableSubtitleStreams.return_value = []
    xbmc.Player.return_value = player_mock

    # Monitor
    monitor_mock = MagicMock()
    monitor_mock.abortRequested.return_value = False
    xbmc.Monitor.return_value = monitor_mock

    # xbmcaddon
    xbmcaddon = MagicMock()
    addon_mock = MagicMock()

    def get_addon_info(name):
        if name == "id":
            return "service.subtitles.polyglotsubs-kodi"
        elif name == "name":
            return "a4ksubtitles"
        elif name == "version":
            try:
                tree = ElementTree.parse("addon.xml")
                root = tree.getroot()
                return root.get("version")
            except Exception:
                return "0.0.0"
        elif name == "profile":
             return os.path.abspath("tmp")
        elif name == "path":
             return os.getcwd()
        return ""

    addon_mock.getAddonInfo.side_effect = get_addon_info
    addon_mock.getSetting.return_value = ""
    xbmcaddon.Addon.return_value = addon_mock

    # xbmcplugin
    xbmcplugin = MagicMock()

    # xbmcgui
    xbmcgui = MagicMock()
    xbmcgui.ListItem = MagicMock

    # xbmcvfs
    xbmcvfs = MagicMock()
    xbmcvfs.mkdirs = lambda f: os.makedirs(f, exist_ok=True)
    xbmcvfs.translatePath = lambda p: p

    __archive_proto = "archive://"

    def listdir(archive_uri):
        archive_path = unquote(archive_uri).replace(__archive_proto, "")
        if os.path.exists(archive_path):
             with ZipFile(archive_path, "r") as zip_obj:
                return ([], zip_obj.namelist())
        return ([], [])

    xbmcvfs.listdir.side_effect = listdir

    def copy(src_uri, dest):
        if ".zip" in src_uri:
            idx = src_uri.find(".zip") + 4
            archive_path = unquote(src_uri[:idx]).replace(__archive_proto, "")
            member = unquote(src_uri[idx+1:]).replace(__archive_proto, "")

            with ZipFile(archive_path, "r") as zip_obj:
                dest_dir = os.path.dirname(dest)
                zip_obj.extract(member, dest_dir)
                extracted_path = os.path.join(dest_dir, member)
                if extracted_path != dest:
                    os.rename(extracted_path, dest)
        else:
             pass

    xbmcvfs.copy.side_effect = copy

    file_mock = MagicMock()
    file_mock.size.return_value = 0
    file_mock.hash.return_value = 0
    xbmcvfs.File.return_value = file_mock

    return {
        "xbmc": xbmc,
        "xbmcaddon": xbmcaddon,
        "xbmcplugin": xbmcplugin,
        "xbmcgui": xbmcgui,
        "xbmcvfs": xbmcvfs,
    }

def install_mocks():
    mocks = create_mocks()
    for name, mock_obj in mocks.items():
        sys.modules[name] = mock_obj
