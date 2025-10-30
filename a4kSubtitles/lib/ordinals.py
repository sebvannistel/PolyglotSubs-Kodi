# -*- coding: utf-8 -*-
"""Utilities for converting numbers to ordinal words.

This module wraps :func:`num2words.num2words` to provide backwards compatible
ordinal formatting for a4kSubtitles while also enabling locale aware
formatting when Kodi exposes the active language setting.
"""

from __future__ import annotations

from typing import Iterable, Optional, Tuple

from num2words import CONVERTER_CLASSES, num2words

from .third_party import iso639
from .third_party.iso639.exceptions import DeprecatedLanguageValue, InvalidLanguageValue

_DEFAULT_LOCALE = "en"
_SUPPORTED_LANGS = set(CONVERTER_CLASSES.keys())
_ENGLISH_GROUP_SCALES: Tuple[str, ...] = (
    "thousand",
    "million",
    "billion",
    "trillion",
    "quadrillion",
    "quintillion",
    "sextillion",
    "septillion",
    "octillion",
    "nonillion",
    "decillion",
)
_REGION_OVERRIDES = {
    ("pt", "brazil"): "pt_BR",
    ("fr", "belgium"): "fr_BE",
    ("fr", "switzerland"): "fr_CH",
    ("fr", "algeria"): "fr_DZ",
    ("en", "india"): "en_IN",
    ("en", "nigeria"): "en_NG",
    ("es", "venezuela"): "es_VE",
    ("es", "colombia"): "es_CO",
    ("es", "costa rica"): "es_CR",
    ("es", "guatemala"): "es_GT",
    ("es", "nicaragua"): "es_NI",
    ("az", "azerbaijan"): "az",
    ("pt", "portugal"): "pt",
}


def kodi_locale_to_num2words_locale(language: Optional[str]) -> str:
    """Map a Kodi language string to a ``num2words`` locale key."""

    if not language:
        return _DEFAULT_LOCALE

    normalized = str(language).strip()
    if not normalized:
        return _DEFAULT_LOCALE

    region_hint = _extract_region_hint(normalized)
    base_hint = _extract_base_language(normalized)

    for candidate in _candidate_locale_keys(normalized):
        if candidate in _SUPPORTED_LANGS:
            return candidate

    lang_info = _lookup_language(base_hint) or _lookup_language(normalized)
    if not lang_info:
        return _DEFAULT_LOCALE

    codes = [
        code
        for code in (lang_info.pt1, lang_info.pt2t, lang_info.pt2b, lang_info.pt3)
        if code
    ]

    if region_hint:
        region_locale = _match_region_locale(codes, region_hint)
        if region_locale:
            return region_locale

    for code in codes:
        locale = _match_supported_locale(code)
        if locale:
            return locale

    return _DEFAULT_LOCALE


def to_ordinal(number: object, kodi_language: Optional[str] = None) -> str:
    """Convert ``number`` to its ordinal word representation.

    The conversion honours the active Kodi language when possible while
    preserving the legacy English formatting (including hyphenation and comma
    placement) that the addon historically returned.
    """

    value = _coerce_int(number)
    locale = kodi_locale_to_num2words_locale(kodi_language)

    ordinal_text = num2words(value, to="ordinal", lang=locale)

    if locale.startswith("en"):
        cardinal_text = num2words(value, lang=locale)
        ordinal_text = _legacy_join(cardinal_text, ordinal_text)
        ordinal_text = _restore_group_commas(ordinal_text)

    return ordinal_text


def _candidate_locale_keys(language: str) -> Iterable[str]:
    parts = [language]
    transformed = language.replace("-", "_")
    if transformed != language:
        parts.append(transformed)
    parts.extend({language.lower(), language.upper(), transformed.lower(), transformed.upper()})
    return parts


def _extract_base_language(language: str) -> str:
    cleaned = language
    if "(" in cleaned and ")" in cleaned:
        cleaned = cleaned.split("(", 1)[0].strip()
    cleaned = cleaned.replace("-", "_")
    if "_" in cleaned:
        cleaned = cleaned.split("_", 1)[0]
    return cleaned.strip() or language


def _extract_region_hint(language: str) -> Optional[str]:
    region = None
    if "(" in language and ")" in language:
        region = language.split("(", 1)[1].split(")", 1)[0].strip()
    normalized = language.replace("-", "_")
    if "_" in normalized:
        suffix = normalized.split("_", 1)[1]
        region = region or suffix
    if region:
        return region.strip().lower()
    return None


def _lookup_language(language: str) -> Optional[iso639.Lang]:
    if not language:
        return None
    try:
        return iso639.Lang(language)
    except (InvalidLanguageValue, DeprecatedLanguageValue):
        try:
            return iso639.Lang(language.title())
        except (InvalidLanguageValue, DeprecatedLanguageValue):
            return None


def _match_region_locale(codes: Iterable[str], region_hint: str) -> Optional[str]:
    region = region_hint.lower().replace(" ", "")
    for code in codes:
        if not code:
            continue
        override = _REGION_OVERRIDES.get((code.lower(), region_hint)) or _REGION_OVERRIDES.get(
            (code.lower(), region)
        )
        if override and override in _SUPPORTED_LANGS:
            return override
        candidate = f"{code}_{region_hint.upper()}"
        match = _match_supported_locale(candidate)
        if match:
            return match
        candidate = f"{code}_{region.upper()}"
        match = _match_supported_locale(candidate)
        if match:
            return match
    return None


def _match_supported_locale(code: str) -> Optional[str]:
    if not code:
        return None
    if code in _SUPPORTED_LANGS:
        return code
    lowered = code.lower()
    if lowered in _SUPPORTED_LANGS:
        return lowered
    uppered = code.upper()
    if uppered in _SUPPORTED_LANGS:
        return uppered
    return None


def _coerce_int(number: object) -> int:
    try:
        return int(float(number))
    except (TypeError, ValueError) as error:
        raise ValueError("Ordinal conversion requires a numeric value") from error


def _legacy_join(cardinal_text: str, ordinal_text: str) -> str:
    hyphen_split = cardinal_text.rsplit("-", 1)
    word_split = cardinal_text.rsplit(" ", 1)
    parts = word_split
    delimiter = " "

    if len(word_split[-1]) > len(hyphen_split[-1]):
        parts = hyphen_split
        delimiter = "-"

    prefix = parts[0] if len(parts) > 1 else ""

    if delimiter == "-":
        ordinal_parts = ordinal_text.rsplit("-", 1)
    else:
        ordinal_parts = ordinal_text.rsplit(" ", 1)

    suffix = ordinal_parts[-1]

    if prefix:
        return prefix + delimiter + suffix
    if delimiter == "-":
        return suffix
    return " " + suffix


def _restore_group_commas(text: str) -> str:
    for scale in _ENGLISH_GROUP_SCALES:
        needle = f"{scale} and "
        replacement = f"{scale}, and "
        if needle in text and replacement not in text:
            text = text.replace(needle, replacement)
    return text
