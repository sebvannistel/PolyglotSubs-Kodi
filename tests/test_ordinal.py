# -*- coding: utf-8 -*-

import pytest

from a4kSubtitles.lib import kodi, ordinal


@pytest.mark.parametrize(
    "number,expected",
    [
        (1, "first"),
        (2, "second"),
        (3, "third"),
        (4, "fourth"),
        (11, "eleventh"),
        (21, "twenty-first"),
        (101, "one hundred and first"),
    ],
)
def test_convert_matches_english_ordinals(number, expected):
    assert ordinal.convert(number) == expected


def test_convert_respects_kodi_locale(monkeypatch):
    monkeypatch.setattr(
        kodi,
        "get_kodi_setting",
        lambda setting, log_error=True: "resource.language.fr_fr",
    )
    monkeypatch.setattr(
        kodi.xbmc,
        "getLanguage",
        lambda *args, **kwargs: "French",
    )

    assert ordinal.convert(1) == "premier"
    assert ordinal.convert(2) == "deuxième"


def test_convert_falls_back_to_english(monkeypatch):
    monkeypatch.setattr(
        kodi,
        "get_kodi_setting",
        lambda setting, log_error=True: "resource.language.zh_cn",
    )
    monkeypatch.setattr(
        kodi.xbmc,
        "getLanguage",
        lambda *args, **kwargs: "Chinese",
    )

    assert ordinal.convert(2) == "second"


def test_convert_accepts_explicit_language(monkeypatch):
    monkeypatch.setattr(
        kodi,
        "get_kodi_setting",
        lambda setting, log_error=True: "resource.language.en_gb",
    )
    monkeypatch.setattr(
        kodi.xbmc,
        "getLanguage",
        lambda *args, **kwargs: "English",
    )

    assert ordinal.convert(2, lang="es") == "segundo"
