# -*- coding: utf-8 -*-

from .common import pytest, api


def test_auto_load_enabled():
    a4k_api = api.A4kSubtitlesApi({'kodi': True})

    assert a4k_api.auto_load_enabled({
        'general.auto_search': 'true',
        'general.auto_download': 'true',
    }) is True

    assert a4k_api.auto_load_enabled({
        'general.auto_search': 'false',
        'general.auto_download': 'true',
    }) is False

    assert a4k_api.auto_load_enabled({
        'general.auto_search': 'true',
        'general.auto_download': 'false',
    }) is False

    assert a4k_api.auto_load_enabled({
        'general.auto_search': 'false',
        'general.auto_download': 'false',
    }) is False


def test_search_uses_mocked_settings_and_video_meta():
    a4k_api = api.A4kSubtitlesApi({'kodi': True})

    def fake_search(core_module, params):
        return {
            'title': core_module.kodi.xbmc.getInfoLabel('VideoPlayer.OriginalTitle'),
            'setting': core_module.kodi.addon.getSetting('general.test'),
            'params': params,
        }

    default_search = a4k_api.core.search
    a4k_api.core.search = fake_search
    try:
        result = a4k_api.search({'q': 'query'}, settings={'general.test': 'value'}, video_meta={'title': 'Movie'})
    finally:
        a4k_api.core.search = default_search

    assert result == {
        'title': 'Movie',
        'setting': 'value',
        'params': {'q': 'query'},
    }


def test_download_uses_mocked_settings():
    a4k_api = api.A4kSubtitlesApi({'kodi': True})

    def fake_download(core_module, params):
        return {
            'setting': core_module.kodi.addon.getSetting('download.path'),
            'params': params,
        }

    default_download = a4k_api.core.download
    a4k_api.core.download = fake_download
    try:
        result = a4k_api.download({'id': 1}, settings={'download.path': '/tmp'})
    finally:
        a4k_api.core.download = default_download

    assert result == {
        'setting': '/tmp',
        'params': {'id': 1},
    }
