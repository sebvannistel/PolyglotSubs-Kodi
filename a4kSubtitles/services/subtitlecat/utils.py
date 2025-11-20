import importlib
import re
import sys
import threading
from pathlib import Path

import requests


def _load_cloudscraper():
    module = importlib.import_module("cloudscraper")
    if not hasattr(module, "create_scraper"):
        package_dir = (
            Path(__file__).resolve().parents[3] / "packages" / "cloudscraper-3.0.0"
        )
        if package_dir.exists():
            package_path = str(package_dir)
            if package_path not in sys.path:
                sys.path.insert(0, package_path)
            sys.modules.pop("cloudscraper", None)
            module = importlib.import_module("cloudscraper")
    return module


cloudscraper = _load_cloudscraper()

from cachetools import LRUCache as _CachetoolsLRUCache
from cloudscraper.exceptions import (
    CloudflareChallengeError as _CloudflareChallengeError,
)
from cloudscraper.exceptions import CloudflareException as _CloudflareException
from rapidfuzz import fuzz

SC_BASE_URL = "https://www.subtitlecat.com"
SC_USER_AGENT = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
    "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/91.0.4472.124 "
    "Safari/537.36 a4kSubtitles-SubtitlecatMod/1.0.1"
)
SC_SCRAPER_DELAY_SECONDS = 4.0
_SCRAPER_DEFAULT_HEADERS = {
    "User-Agent": SC_USER_AGENT,
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
    "Accept-Language": "en-US,en;q=0.9",
    "Cache-Control": "no-cache",
}

KODI_REGIONAL_LANG_MAP = {
    "pt-br": ("Portuguese (Brazil)", "pt"),
    "es-419": ("Spanish", "es"),
    "sr-me": ("Serbian", "sr"),
}

_thread_local_session_storage = threading.local()

CLOUDFLARE_EXCEPTION = _CloudflareException
CLOUDFLARE_CHALLENGE_EXCEPTION = _CloudflareChallengeError
SCRAPER_REQUEST_EXCEPTION = requests.exceptions.RequestException
SCRAPER_TIMEOUT_EXCEPTION = requests.exceptions.Timeout
SCRAPER_HTTP_ERROR = requests.exceptions.HTTPError
SCRAPER_CONNECTION_ERROR = requests.exceptions.ConnectionError


def _create_scraper():
    scraper = cloudscraper.create_scraper(
        browser="firefox",
        delay=SC_SCRAPER_DELAY_SECONDS,
    )
    scraper.headers.update(_SCRAPER_DEFAULT_HEADERS)
    return scraper


def _get_session():
    """Return a thread-local CloudScraper session with default headers."""
    session = getattr(_thread_local_session_storage, "session", None)
    if session is None:
        session = _create_scraper()
        _thread_local_session_storage.session = session
    return session


class LRUCache(_CachetoolsLRUCache):
    """Thread-safe wrapper around :class:`cachetools.LRUCache`."""

    _MISSING = object()

    def __init__(self, maxsize=128, getsizeof=None):
        if not isinstance(maxsize, int) or maxsize <= 0:
            raise ValueError("maxsize must be a positive integer")
        super().__init__(maxsize=maxsize, getsizeof=getsizeof)
        self._lock = threading.RLock()

    def __getitem__(self, key):
        with self._lock:
            return super().__getitem__(key)

    def __setitem__(self, key, value):
        with self._lock:
            return super().__setitem__(key, value)

    def __contains__(self, key):
        with self._lock:
            return super().__contains__(key)

    def get(self, key, default=None):
        with self._lock:
            return super().get(key, default)

    def pop(self, key, default=_MISSING):
        with self._lock:
            if default is self._MISSING:
                return super().pop(key)
            return super().pop(key, default)

    def popitem(self):
        with self._lock:
            return super().popitem()

    def clear(self):
        with self._lock:
            return super().clear()

    def __delitem__(self, key):
        with self._lock:
            return super().__delitem__(key)


_CLEAN_PUNC = re.compile(r"[._-]")
_CLEAN_CAMEL = re.compile(r"(?<=[a-z])(?=[A-Z])")


def _is_title_close(wanted: str, got: str) -> bool:
    w_raw = wanted or ""
    g_raw = got or ""
    w_tmp = _CLEAN_CAMEL.sub(" ", w_raw)
    g_tmp = _CLEAN_CAMEL.sub(" ", g_raw)
    w_spaced = _CLEAN_PUNC.sub(" ", w_tmp)
    g_spaced = _CLEAN_PUNC.sub(" ", g_tmp)
    clean_w = " ".join(w_spaced.lower().split())
    clean_g = " ".join(g_spaced.lower().split())
    tokens_w = clean_w.split()
    tokens_g = clean_g.split()
    if len(tokens_w) < 3 and abs(len(tokens_w) - len(tokens_g)) > 1:
        return False
    return fuzz.token_set_ratio(clean_w, clean_g) >= 70


def _get_setting(core, key, default=None):
    if core and hasattr(core, "settings") and core.settings is not None:
        return core.settings.get(key, default)
    return default


def _post_download_fix_encoding(core, service_name, raw_bytes, outfile):
    import html
    import io

    _cd_module = None
    _cn_function = None
    _use_charset_normalizer_first = False
    try:
        from charset_normalizer import from_bytes as _cn_imported

        _cn_function = _cn_imported
        _use_charset_normalizer_first = True
    except ImportError:
        try:
            import chardet as _cd_imported

            _cd_module = _cd_imported
        except ImportError:
            pass
    enc = "utf-8"
    detected_source = "default (no detectors available or both failed import)"
    if _use_charset_normalizer_first and _cn_function:
        cn_matches = list(_cn_function(raw_bytes))
        if cn_matches and cn_matches[0].encoding:
            enc = cn_matches[0].encoding
            cn_confidence = getattr(cn_matches[0], "confidence", "N/A")
            detected_source = f"charset-normalizer (confidence: {cn_confidence})"
            core.logger.debug(
                f"[{service_name}] Detected by charset-normalizer: {enc} (confidence: {cn_confidence}) for {repr(outfile)}"
            )
        elif _cd_module:
            core.logger.debug(
                f"[{service_name}] charset-normalizer did not yield encoding. Falling back to chardet for {repr(outfile)}."
            )
            guess = _cd_module.detect(raw_bytes)
            chardet_confidence = guess.get("confidence") if guess else 0.0
            chardet_enc_value = guess["encoding"] if guess else None
            if chardet_enc_value:
                enc = chardet_enc_value
                detected_source = f"chardet (fallback, confidence: {chardet_confidence if chardet_confidence is not None else 'N/A'})"
                core.logger.debug(
                    f"[{service_name}] Detected by chardet (fallback): {enc} (confidence: {chardet_confidence if chardet_confidence is not None else 'N/A'}) for {repr(outfile)}"
                )
            else:
                detected_source = "default (charset-normalizer and chardet failed)"
                core.logger.debug(
                    f"[{service_name}] charset-normalizer and chardet (fallback) failed. Using default {enc} for {repr(outfile)}."
                )
        else:
            detected_source = "default (charset-normalizer failed, chardet unavailable)"
            core.logger.debug(
                f"[{service_name}] charset-normalizer failed and chardet unavailable. Using default {enc} for {repr(outfile)}."
            )
    elif _cd_module:
        guess = _cd_module.detect(raw_bytes)
        chardet_confidence = guess.get("confidence") if guess else 0.0
        chardet_enc_value = guess["encoding"] if guess else None
        if chardet_enc_value:
            enc = chardet_enc_value
            detected_source = f"chardet (primary, confidence: {chardet_confidence if chardet_confidence is not None else 'N/A'})"
            core.logger.debug(
                f"[{service_name}] Detected by chardet (primary): {enc} (confidence: {chardet_confidence if chardet_confidence is not None else 'N/A'}) for {repr(outfile)}"
            )
        else:
            detected_source = "default (chardet failed)"
            core.logger.debug(
                f"[{service_name}] chardet (primary) failed. Using default {enc} for {repr(outfile)}."
            )
    core.logger.debug(
        f"[{service_name}] Final encoding for decoding: '{enc}' (Source: {detected_source}) for {repr(outfile)}"
    )
    if enc is None:
        core.logger.debug(
            f"[{service_name}] Encoding resolved to None despite checks. Using 'utf-8' for {repr(outfile)}."
        )
        enc = "utf-8"
    text = raw_bytes.decode(enc, errors="replace")
    text = html.unescape(text)
    bom = _get_setting(core, "force_bom", False)
    final_encoding = "utf-8-sig" if bom else "utf-8"
    final_bytes_to_write = text.encode(final_encoding)
    with io.open(outfile, "wb") as fh:
        fh.write(final_bytes_to_write)
    core.logger.debug(
        f"[{service_name}] Successfully wrote processed subtitle to {repr(outfile)} with encoding {final_encoding}"
    )
