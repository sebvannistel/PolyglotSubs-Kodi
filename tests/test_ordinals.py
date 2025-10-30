import pytest

from a4kSubtitles.lib import ordinals


@pytest.mark.parametrize(
    "value, expected",
    [
        (1, " first"),
        (2, " second"),
        (3, " third"),
        (4, " fourth"),
        (5, " fifth"),
        (8, " eighth"),
        (9, " ninth"),
        (12, " twelfth"),
        (20, " twentieth"),
        (21, "twenty-first"),
        (22, "twenty-second"),
        (30, " thirtieth"),
        (31, "thirty-first"),
        (100, "one hundredth"),
        (101, "one hundred and first"),
        (1002, "one thousand, and second"),
        (2013, "two thousand, and thirteenth"),
        (1_000_001, "one million, and first"),
    ],
)
def test_to_ordinal_matches_legacy_english(value, expected):
    assert ordinals.to_ordinal(value, kodi_language="English") == expected


def test_to_ordinal_defaults_to_english():
    assert ordinals.to_ordinal(21) == "twenty-first"


@pytest.mark.parametrize(
    "kodi_language, expected",
    [
        (None, "en"),
        ("", "en"),
        ("English", "en"),
        ("en_US", "en"),
        ("Portuguese (Brazil)", "pt_BR"),
        ("fr-be", "fr_BE"),
        ("Spanish (Venezuela)", "es_VE"),
        ("es-VE", "es_VE"),
        ("Serbian", "sr"),
        ("Unknown", "en"),
    ],
)
def test_kodi_locale_mapping(kodi_language, expected):
    assert ordinals.kodi_locale_to_num2words_locale(kodi_language) == expected


@pytest.mark.parametrize(
    "value, kodi_language, expected",
    [
        (2, "Spanish", "segundo"),
        (2, "es-ES", "segundo"),
        (2, "French", "deuxième"),
        (2, "Portuguese (Brazil)", "segundo"),
    ],
)
def test_to_ordinal_respects_locale(value, kodi_language, expected):
    assert ordinals.to_ordinal(value, kodi_language=kodi_language) == expected


def test_to_ordinal_rejects_non_numeric():
    with pytest.raises(ValueError):
        ordinals.to_ordinal("not-a-number")
