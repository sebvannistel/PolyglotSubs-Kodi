# -*- coding: utf-8 -*-

import os

os.environ["A4KSUBTITLES_API_MODE"] = '{"kodi": true}'
from a4kSubtitles.lib import kodi, logger
from tests.utils import spy_fn

os.environ.pop("A4KSUBTITLES_API_MODE", None)


def test_json_rpc_logs_on_missing_value():
    default = kodi.xbmc.executeJSONRPC
    kodi.xbmc.executeJSONRPC = lambda _: '{ "result": {} }'
    spy = spy_fn(logger, "error")

    result = kodi.json_rpc("Test", {})

    kodi.xbmc.executeJSONRPC = default
    spy.restore()

    assert result == {}
    assert spy.call_count == 1
