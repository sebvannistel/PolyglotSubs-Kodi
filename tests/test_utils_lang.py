# -*- coding: utf-8 -*-

from a4kSubtitles.lib import kodi, logger, utils
from tests.utils import spy_fn


def test_get_lang_id_logs_on_invalid_language():
    spy = spy_fn(logger, "error")
    result = utils.get_lang_id("notalanguage", kodi.xbmc.ISO_639_2)
    spy.restore()

    assert result == ""
    assert spy.call_count >= 1
