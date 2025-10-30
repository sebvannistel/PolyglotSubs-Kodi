# -*- coding: utf-8 -*-
"""Locale-aware ordinal helpers backed by :mod:`num2words`."""

from __future__ import annotations

from typing import List, Optional

from num2words import num2words

from . import kodi

_DEFAULT_LANGUAGE = "en"
_RESOURCE_LANGUAGE_PREFIX = "resource.language."


def _normalize_candidates(value: Optional[str]) -> List[str]:
    """Return a list of potential ``num2words`` language identifiers."""
    if isinstance(value, dict):
        value = value.get("value")

    if not isinstance(value, str):
        return []

    candidate = value.strip()
    if not candidate:
        return []

    results: List[str] = []

    # Include the raw candidate in case it is already a known code (e.g. "en").
    results.append(candidate)

    if candidate.startswith(_RESOURCE_LANGUAGE_PREFIX):
        candidate = candidate[len(_RESOURCE_LANGUAGE_PREFIX) :]
        results.append(candidate)

    candidate = candidate.replace("-", "_")
    results.append(candidate)

    if "_" in candidate:
        primary, region = candidate.split("_", 1)
        if primary:
            results.append(primary)
            results.append(f"{primary}_{region.upper()}")
    else:
        results.append(candidate.lower())

    # Try Kodi's language converter which accepts English names.
    for probe in [value, candidate]:
        try:
            iso = kodi.xbmc.convertLanguage(probe, kodi.xbmc.ISO_639_1)
        except Exception:  # pragma: no cover - defensive, mirrors Kodi's API
            continue
        if iso:
            results.append(iso.lower())

    seen = set()
    normalized: List[str] = []
    for entry in results:
        if not entry:
            continue
        entry = entry.strip()
        if not entry:
            continue
        if "_" in entry:
            parts = entry.split("_", 1)
            entry = f"{parts[0].lower()}_{parts[1].upper()}"
        else:
            entry = entry.lower()
        if entry not in seen:
            seen.add(entry)
            normalized.append(entry)

    return normalized


def _collect_language_candidates(explicit: Optional[str]) -> List[str]:
    """Aggregate language hints from Kodi and optional overrides."""
    candidates: List[str] = []
    candidates.extend(_normalize_candidates(explicit))

    try:
        kodi_locale = kodi.get_kodi_setting("locale.language", log_error=False)
    except Exception:  # pragma: no cover - JSON-RPC failures fall back to defaults
        kodi_locale = None
    candidates.extend(_normalize_candidates(kodi_locale))

    get_language = getattr(kodi.xbmc, "getLanguage", None)
    if callable(get_language):
        for args in ((kodi.xbmc.ISO_639_1,), (kodi.xbmc.ENGLISH_NAME,), tuple()):
            try:
                value = get_language(*args)
            except TypeError:
                continue
            except Exception:  # pragma: no cover - mirrors Kodi runtime behaviour
                break
            if value:
                candidates.extend(_normalize_candidates(value))
                break

    candidates.append(_DEFAULT_LANGUAGE)
    return candidates


def convert(number: int | str, lang: Optional[str] = None) -> str:
    """Convert ``number`` to its ordinal representation.

    The helper honours Kodi's interface language (``locale.language``) when it
    maps cleanly to one of :mod:`num2words`' supported locales. Callers may pass
    ``lang`` explicitly to bypass Kodi's settings. The function always falls
    back to English ordinals to preserve previous behaviour if no locale match
    is available.
    """

    tried = set()
    for candidate in _collect_language_candidates(lang):
        if not candidate or candidate in tried:
            continue
        tried.add(candidate)
        try:
            return num2words(number, to="ordinal", lang=candidate)
        except NotImplementedError:
            continue

    # Final fallback – ``num2words`` should always handle English ordinals.
    return num2words(number, to="ordinal", lang=_DEFAULT_LANGUAGE)


__all__ = ["convert"]
