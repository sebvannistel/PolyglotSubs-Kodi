import threading
import re
import requests as system_requests
from rapidfuzz import fuzz
from collections import OrderedDict

SC_BASE_URL = "https://www.subtitlecat.com"
SC_USER_AGENT = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
    "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/91.0.4472.124 "
    "Safari/537.36 a4kSubtitles-SubtitlecatMod/1.0.1"
)

_thread_local_session_storage = threading.local()

def _get_session():
    """Return a thread-local requests.Session with default headers."""
    if not hasattr(_thread_local_session_storage, 'session'):
        session = system_requests.Session()
        session.headers.update({'User-Agent': SC_USER_AGENT})
        _thread_local_session_storage.session = session
    return _thread_local_session_storage.session

class SimpleLRUCache:
    """
    A simple thread-safe LRU cache.
    """
    def __init__(self, maxsize=128):
        """
        Initializes the cache.

        Args:
            maxsize (int, optional): The maximum size of the cache. Defaults to 128.
        """
        if not isinstance(maxsize, int) or maxsize <= 0:
            raise ValueError("maxsize must be a positive integer")
        self._cache = OrderedDict()
        self._maxsize = maxsize
        self._lock = threading.Lock()

    def get(self, key, default=None):
        """
        Gets an item from the cache.

        Args:
            key: The key of the item to get.
            default: The default value to return if the key is not in the cache.

        Returns:
            The value of the item, or the default value if the key is not in the cache.
        """
        with self._lock:
            if key not in self._cache:
                return default
            value = self._cache.pop(key)
            self._cache[key] = value
            return value

    def __setitem__(self, key, value):
        """
        Sets an item in the cache.

        Args:
            key: The key of the item to set.
            value: The value of the item to set.
        """
        with self._lock:
            if key in self._cache:
                self._cache.pop(key)
            elif len(self._cache) >= self._maxsize:
                self._cache.popitem(last=False)
            self._cache[key] = value

    def __getitem__(self, key):
        """
        Gets an item from the cache.

        Args:
            key: The key of the item to get.

        Returns:
            The value of the item.
        """
        with self._lock:
            if key not in self._cache:
                raise KeyError(key)
            value = self._cache.pop(key)
            self._cache[key] = value
            return value

    def __contains__(self, key):
        """
        Checks if an item is in the cache.

        Args:
            key: The key of the item to check.

        Returns:
            True if the item is in the cache, False otherwise.
        """
        with self._lock:
            return key in self._cache

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
    if core and hasattr(core, 'settings') and core.settings is not None:
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
    enc = 'utf-8'
    detected_source = "default (no detectors available or both failed import)"
    if _use_charset_normalizer_first and _cn_function:
        cn_matches = list(_cn_function(raw_bytes))
        if cn_matches and cn_matches[0].encoding:
            enc = cn_matches[0].encoding
            cn_confidence = getattr(cn_matches[0], 'confidence', 'N/A')
            detected_source = f"charset-normalizer (confidence: {cn_confidence})"
            core.logger.debug(f"[{service_name}] Detected by charset-normalizer: {enc} (confidence: {cn_confidence}) for {repr(outfile)}")
        elif _cd_module:
            core.logger.debug(f"[{service_name}] charset-normalizer did not yield encoding. Falling back to chardet for {repr(outfile)}.")
            guess = _cd_module.detect(raw_bytes)
            chardet_confidence = guess.get('confidence') if guess else 0.0
            chardet_enc_value = guess['encoding'] if guess else None
            if chardet_enc_value:
                enc = chardet_enc_value
                detected_source = f"chardet (fallback, confidence: {chardet_confidence if chardet_confidence is not None else 'N/A'})"
                core.logger.debug(f"[{service_name}] Detected by chardet (fallback): {enc} (confidence: {chardet_confidence if chardet_confidence is not None else 'N/A'}) for {repr(outfile)}")
            else:
                detected_source = "default (charset-normalizer and chardet failed)"
                core.logger.debug(f"[{service_name}] charset-normalizer and chardet (fallback) failed. Using default {enc} for {repr(outfile)}.")
        else:
            detected_source = "default (charset-normalizer failed, chardet unavailable)"
            core.logger.debug(f"[{service_name}] charset-normalizer failed and chardet unavailable. Using default {enc} for {repr(outfile)}.")
    elif _cd_module:
        guess = _cd_module.detect(raw_bytes)
        chardet_confidence = guess.get('confidence') if guess else 0.0
        chardet_enc_value = guess['encoding'] if guess else None
        if chardet_enc_value:
            enc = chardet_enc_value
            detected_source = f"chardet (primary, confidence: {chardet_confidence if chardet_confidence is not None else 'N/A'})"
            core.logger.debug(f"[{service_name}] Detected by chardet (primary): {enc} (confidence: {chardet_confidence if chardet_confidence is not None else 'N/A'}) for {repr(outfile)}")
        else:
            detected_source = "default (chardet failed)"
            core.logger.debug(f"[{service_name}] chardet (primary) failed. Using default {enc} for {repr(outfile)}.")
    core.logger.debug(f"[{service_name}] Final encoding for decoding: '{enc}' (Source: {detected_source}) for {repr(outfile)}")
    if enc is None:
        core.logger.debug(f"[{service_name}] Encoding resolved to None despite checks. Using 'utf-8' for {repr(outfile)}.")
        enc = 'utf-8'
    text = raw_bytes.decode(enc, errors='replace')
    text = html.unescape(text)
    bom = _get_setting(core, 'force_bom', False)
    final_encoding = 'utf-8-sig' if bom else 'utf-8'
    final_bytes_to_write = text.encode(final_encoding)
    with io.open(outfile, 'wb') as fh:
        fh.write(final_bytes_to_write)
    core.logger.debug(f"[{service_name}] Successfully wrote processed subtitle to {repr(outfile)} with encoding {final_encoding}")
