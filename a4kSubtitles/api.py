# -*- coding: utf-8 -*-

import os
import json
import importlib
import a4kSubtitles

api_mode_env_name = 'A4KSUBTITLES_API_MODE'

class A4kSubtitlesApi(object):
    """
    A4kSubtitlesApi provides a Pythonic interface to the a4kSubtitles addon.

    It allows for searching and downloading subtitles, as well as mocking settings and video metadata for testing purposes.
    """
    def __init__(self, mocks=None):
        """
        Initializes the A4kSubtitlesApi.

        Args:
            mocks (dict, optional): A dictionary of mocks to use. Defaults to None.
        """
        if mocks is None:
            mocks = {}

        api_mode = {
            'kodi': False,
            'xbmc': False,
            'xbmcaddon': False,
            'xbmcplugin': False,
            'xbmcgui': False,
            'xbmcvfs': False,
        }

        api_mode.update(mocks)
        os.environ[api_mode_env_name] = json.dumps(api_mode)

        a4kSubtitles.initialize()
        self.core = importlib.import_module('a4kSubtitles.core')

    def __mock_video_meta(self, meta):
        """
        Mocks the video metadata.

        Args:
            meta (dict): A dictionary of video metadata.

        Returns:
            function: A function to restore the original video metadata.
        """
        def get_info_label(label):
            if label == 'System.BuildVersionCode':
                return meta.get('version', '19.1.0')
            if label == 'VideoPlayer.Year':
                return meta.get('year', '')
            if label == 'VideoPlayer.Season':
                return meta.get('season', '')
            if label == 'VideoPlayer.Episode':
                return meta.get('episode', '')
            if label == 'VideoPlayer.TVShowTitle':
                return meta.get('tvshow', '')
            if label == 'VideoPlayer.OriginalTitle':
                return meta.get('title', '')
            if label == 'VideoPlayer.Title':
                return meta.get('_title', '')
            if label == 'VideoPlayer.IMDBNumber':
                return meta.get('imdb_id', '')
            if label == 'Player.FilenameAndPath':
                return meta.get('url', '')
        default = self.core.kodi.xbmc.getInfoLabel
        self.core.kodi.xbmc.getInfoLabel = get_info_label

        default_ = self.core.kodi.xbmc.Player().getPlayingFile
        self.core.kodi.xbmc.Player().getPlayingFile = lambda: meta.get('filename', '')

        default__ = self.core.kodi.xbmcvfs.File.size
        self.core.kodi.xbmcvfs.File.size = lambda: meta.get('filesize', '')

        default___ = self.core.kodi.xbmcvfs.File.hash
        self.core.kodi.xbmcvfs.File.hash = lambda: meta.get('filehash', '')

        def restore():
            self.core.kodi.xbmc.getInfoLabel = default
            self.core.kodi.xbmc.Player().getPlayingFile = default_
            self.core.kodi.xbmcvfs.File.size = default__
            self.core.kodi.xbmcvfs.File.hash = default___
        return restore

    def mock_settings(self, settings):
        """
        Mocks the addon settings.

        Args:
            settings (dict): A dictionary of settings to mock.

        Returns:
            function: A function to restore the original settings.
        """
        default = self.core.kodi.addon.getSetting

        def get_setting(id):
            setting = settings.get(id, None)
            if not setting:
                setting = default(id)
            return setting

        self.core.kodi.addon.getSetting = get_setting

        def restore():
            self.core.kodi.addon.getSetting = default
        return restore

    def search(self, params, settings=None, video_meta=None):
        """
        Searches for subtitles.

        Args:
            params (dict): A dictionary of search parameters.
            settings (dict, optional): A dictionary of settings to mock. Defaults to None.
            video_meta (dict, optional): A dictionary of video metadata to mock. Defaults to None.

        Returns:
            list: A list of subtitle results.
        """
        restore_settings = None
        restore_video_meta = None

        try:
            if settings is not None:
                restore_settings = self.mock_settings(settings)

            if video_meta is not None:
                restore_video_meta = self.__mock_video_meta(video_meta)

            return self.core.search(self.core, params)
        finally:
            if restore_settings:
                restore_settings()
            if restore_video_meta:
                restore_video_meta()

    def download(self, params, settings=None):
        """
        Downloads a subtitle.

        Args:
            params (dict): A dictionary of download parameters.
            settings (dict, optional): A dictionary of settings to mock. Defaults to None.

        Returns:
            str: The path to the downloaded subtitle file.
        """
        restore_settings = None

        try:
            if settings:
                restore_settings = self.mock_settings(settings)

            return self.core.download(self.core, params)
        finally:
            if restore_settings:
                restore_settings()

    def auto_load_enabled(self, settings=None):
        """
        Checks if auto-loading of subtitles is enabled.

        Args:
            settings (dict, optional): A dictionary of settings to mock. Defaults to None.

        Returns:
            bool: True if auto-loading is enabled, False otherwise.
        """
        restore_settings = None

        try:
            if settings:
                restore_settings = self.mock_settings(settings)

            return self.core.kodi.get_bool_setting('general.auto_search') and self.core.kodi.get_bool_setting('general.auto_download')
        finally:
            if restore_settings:
                restore_settings()
