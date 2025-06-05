#--- START OF FILE subtitlecat.py ---

# C:\...\a4kSubtitles-SubtitlecatMod\a4kSubtitles\services\subtitlecat.py
# -*- coding: utf-8 -*-
# SubtitleCat provider for a4kSubtitles

# Upstream logger core.logger only exposes .debug() & .error().
# All .info() / .warning() calls have been changed to .debug() for compatibility.

# from a4kSubtitles.lib import utils as a4k_utils # Removed as per instruction (unused)
import requests as system_requests
from bs4 import BeautifulSoup
import urllib.parse
from urllib.parse import urljoin # Added for robust URL building

import re, time # Retained as it will be used by client-side translation rate limiting
from functools import lru_cache                # ← simple cache
from rapidfuzz import fuzz                    # ← fuzzy title match
# import tempfile # Removed as no longer creating temp files in build_download_request
# import os # Not directly used by this provider's logic now

# Imports for _post_download_fix_encoding (html, io) are made locally within that function as per snippet.
# chardet and charset_normalizer are also imported locally within that function.

# START OF ADDITIONS FOR CLIENT-SIDE TRANSLATION
import srt # For parsing/composing SRT files (MODIFIED IMPORT)
import html # For unescaping HTML entities (used in translation preparation)
# urllib.parse.quote_plus is used via urllib.parse.quote_plus
# END OF ADDITIONS FOR CLIENT-SIDE TRANSLATION

# START OF ADDITIONS FOR AIOHTTP AND ASYNC OPERATIONS
_AIOHTTP_AVAILABLE = False
try:
    import asyncio
    import aiohttp
    _AIOHTTP_AVAILABLE = True
except ImportError:
    # asyncio might still be available if aiohttp is not (Python 3.7+),
    # but the async translation path relies on aiohttp.
    asyncio = None # Ensure it's None if aiohttp import failed, to simplify checks
    aiohttp = None
    # No core.logger available at module import time to log this fallback.
    # If needed, it can be logged when _get_setting(core, "debug", False) is first accessible.
# END OF ADDITIONS FOR AIOHTTP AND ASYNC OPERATIONS

import threading # Added for thread-safe counter
import sys # ADDED for sys.platform (conditional event loop policy)
import concurrent.futures # ADDED for ThreadPoolExecutor

# _SC_NEWLINE_MARKER_ REMOVED as it's unused

from collections import Counter # Added for determining overall detected source language
from collections import OrderedDict # ADDED for SimpleLRUCache implementation

# No 'log = logger.Logger.get_logger(__name__)' needed; use 'core.logger' directly.

# MODIFIED: Changed _TRANSLATED_CACHE to use SimpleLRUCache for thread-safety.
# LRU Cache (detail_url, lang_code) ➜ final .srt URL (e.g., after successful client translation & upload)
# _TRANSLATED_CACHE = {}     # survives for the lifetime of the add-on (NOTE: Population mechanism via _wait_for_translated removed)
_TRANSLATED_CACHE = None # Will be initialized to SimpleLRUCache below, after class definition

# ADDED: SimpleLRUCache class
class SimpleLRUCache:
    def __init__(self, maxsize=128):
        # MODIFICATION: Added maxsize validation as per review suggestion
        if not isinstance(maxsize, int) or maxsize <= 0:
            raise ValueError("maxsize must be a positive integer")
        self._cache = OrderedDict()
        self._maxsize = maxsize
        self._lock = threading.Lock() # Lock for thread-safe access to the cache itself

    def get(self, key, default=None):
        with self._lock:
            if key not in self._cache:
                return default
            # Move the accessed item to the end to mark it as recently used
            value = self._cache.pop(key)
            self._cache[key] = value
            return value

    def __setitem__(self, key, value):
        with self._lock:
            if key in self._cache:
                # Move the existing item to the end
                self._cache.pop(key)
            elif len(self._cache) >= self._maxsize:
                # Remove the least recently used item (from the beginning)
                self._cache.popitem(last=False)
            # self_cache_key = key # Ensure we use the original key for assignment # MODIFICATION: Removed redundant variable
            self._cache[key] = value

    # MODIFICATION: Added __getitem__ as per review suggestion
    def __getitem__(self, key):
        with self._lock:
            if key not in self._cache:
                raise KeyError(key)
            # Move the accessed item to the end to mark it as recently used
            value = self._cache.pop(key)
            self._cache[key] = value
            return value

    # MODIFICATION: Added __contains__ as per review suggestion
    def __contains__(self, key):
        with self._lock:
            return key in self._cache

# Initialize _TRANSLATED_CACHE here now that SimpleLRUCache is defined
_TRANSLATED_CACHE = SimpleLRUCache(maxsize=64) # survives for the lifetime of the add-on

# ADDED: Cache for client-side translated content (if not uploaded or upload fails)
# Key: (original_srt_url, target_gtranslate_lang_code), Value: {'srt_content': '...', 'detected_source_lang': '...'}
_CLIENT_TRANSLATED_CONTENT_CACHE = SimpleLRUCache(maxsize=128)


#######################################################################
# 1. helper ­- title similarity
#######################################################################
# Relaxed fuzzy matching with punctuation & camel-case preprocessing
_CLEAN_PUNC = re.compile(r"[._-]")
_CLEAN_CAMEL = re.compile(r"(?<=[a-z])(?=[A-Z])")

def _is_title_close(wanted: str, got: str) -> bool:
    # Raw input
    w_raw = wanted or ""
    g_raw = got or ""

    # 1) Insert spaces at camel-case boundaries
    w_tmp = _CLEAN_CAMEL.sub(" ", w_raw)
    g_tmp = _CLEAN_CAMEL.sub(" ", g_raw)

    # 2) Replace dots/underscores/hyphens with spaces
    w_spaced = _CLEAN_PUNC.sub(" ", w_tmp)
    g_spaced = _CLEAN_PUNC.sub(" ", g_tmp)

    # 3) Lowercase and collapse whitespace
    clean_w = " ".join(w_spaced.lower().split())
    clean_g = " ".join(g_spaced.lower().split())

    tokens_w = clean_w.split()
    tokens_g = clean_g.split()

    # 4) Short-title guard: allow at most one extra token for two-word titles
    if len(tokens_w) < 3 and abs(len(tokens_w) - len(tokens_g)) > 1:
        return False

    # Final fuzzy check at 70% threshold (was 75, changed as per review comment implicitly accepting 70)
    return fuzz.token_set_ratio(clean_w, clean_g) >= 70


__subtitlecat_base_url = "https://www.subtitlecat.com"
__user_agent = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
    "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/91.0.4472.124 "
    "Safari/537.36 a4kSubtitles-SubtitlecatMod/1.0.1" # Ensure your addon version is reflected if desired
)

# MODIFICATION: Use threading.local() for requests.Session
_thread_local_session_storage = threading.local()

def _get_session():
    """
    Retrieves or creates a requests.Session instance for the current thread.
    The session is initialized with the common User-Agent.
    """
    if not hasattr(_thread_local_session_storage, 'session'):
        session = system_requests.Session()
        session.headers.update({'User-Agent': __user_agent})
        _thread_local_session_storage.session = session
    return _thread_local_session_storage.session

# _SC_SESSION = system_requests.Session() # MODIFICATION: Replaced with thread-local approach
# _SC_SESSION.headers.update({'User-Agent': __user_agent}) # MODIFICATION: Moved to _get_session()
# _SC_SESSION_LOCK = threading.Lock() # MODIFICATION: Removed as sessions are now thread-local

# START OF MODIFICATION: Added regional language map
__kodi_regional_lang_map = {
    # site_lang_code.lower(): (kodi_english_name, kodi_iso_639_1_code)
    "pt-br": ("Portuguese (Brazil)", "pt"),
    "es-419": ("Spanish", "es"),
    "sr-me": ("Serbian", "sr"),
}
# END OF MODIFICATION: Added regional language map

# START OF MODIFICATION: Added _get_setting helper
def _get_setting(core, key, default=None):
    # Ensure core and core.settings are not None before accessing
    if core and hasattr(core, 'settings') and core.settings is not None:
        return core.settings.get(key, default)
    return default
# END OF MODIFICATION

# helper -------------------------------------
# _extract_ajax function removed as per plan.

# _wait_for_translated function REMOVED as per review (dead code for new workflow)


# START OF MODIFICATION: Encoding fix helper
def _post_download_fix_encoding(core, service_name, raw_bytes, outfile):
    import html, io # html import is here locally

    _cd_module = None
    _cn_function = None
    _use_charset_normalizer_first = False # Flag to prioritize charset-normalizer

    try:
        from charset_normalizer import from_bytes as _cn_imported
        _cn_function = _cn_imported
        _use_charset_normalizer_first = True
        # core.logger.debug(f"[{service_name}] charset-normalizer imported successfully.") # Redundant if next log shows usage
    except ImportError:
        # core.logger.debug(f"[{service_name}] charset-normalizer not available. Will try chardet.")
        try:
            import chardet as _cd_imported
            _cd_module = _cd_imported
            # core.logger.debug(f"[{service_name}] chardet imported successfully.")
        except ImportError:
             # core.logger.debug(f"[{service_name}] Neither charset-normalizer nor chardet available.")
             pass # Both failed

    enc = 'utf-8' # Default encoding
    detected_source = "default (no detectors available or both failed import)"

    if _use_charset_normalizer_first and _cn_function:
        # core.logger.debug(f"[{service_name}] Attempting detection with charset-normalizer for {repr(outfile)}.")
        cn_matches = list(_cn_function(raw_bytes)) # Convert generator to list
        if cn_matches and cn_matches[0].encoding: # Access best match if list not empty
            enc = cn_matches[0].encoding
            # Confidence attribute might not always exist or be named 'confidence'
            cn_confidence = getattr(cn_matches[0], 'confidence', 'N/A')
            detected_source = f"charset-normalizer (confidence: {cn_confidence})"
            core.logger.debug(f"[{service_name}] Detected by charset-normalizer: {enc} (confidence: {cn_confidence}) for {repr(outfile)}")
        elif _cd_module: # Fallback to chardet if charset-normalizer failed or didn't yield
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
        else: # charset-normalizer failed, chardet not available
            detected_source = "default (charset-normalizer failed, chardet unavailable)"
            core.logger.debug(f"[{service_name}] charset-normalizer failed and chardet unavailable. Using default {enc} for {repr(outfile)}.")

    elif _cd_module: # Only chardet was available and successfully imported
        # core.logger.debug(f"[{service_name}] charset-normalizer not available/used. Using chardet for {repr(outfile)}.")
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
    # else: Neither detector was available, detected_source and enc remain defaults

    core.logger.debug(f"[{service_name}] Final encoding for decoding: '{enc}' (Source: {detected_source}) for {repr(outfile)}")
    if enc is None: # Should be rare with defaults, but safety check
        core.logger.debug(f"[{service_name}] Encoding resolved to None despite checks. Using 'utf-8' for {repr(outfile)}.")
        enc = 'utf-8'

    text = raw_bytes.decode(enc, errors='replace')
    text = html.unescape(text) # html.unescape used here
    bom = _get_setting(core, 'force_bom', False) # Correctly uses _get_setting
    final_encoding = 'utf-8-sig' if bom else 'utf-8'
    final_bytes_to_write = text.encode(final_encoding)
    with io.open(outfile, 'wb') as fh:
        fh.write(final_bytes_to_write)
    core.logger.debug(f"[{service_name}] Successfully wrote processed subtitle to {repr(outfile)} with encoding {final_encoding}")
# END OF MODIFICATION: Encoding fix helper


# START OF DEFINITIONS FOR CLIENT-SIDE TRANSLATION
GOOGLE_TRANSLATE_URL = "https://translate.googleapis.com/translate_a/single"
# Constants for client-side translation batching by build_download_request
GOOGLE_API_Q_PARAM_CHAR_LIMIT = 500  # MODIFIED: Max char length for all 'q' params combined (was 480)
MAX_LINES_PER_API_CALL_CONFIG = 20   # MODIFIED: Max number of logical lines per API call (was 40)
DEFAULT_BATCH_DELAY_SECONDS = 0.25   # Default delay between API calls made by build_download_request
MAX_PARTIAL_RETRIES = 2              # Max depth for recursive calls in _gtranslate_text_chunk if it were to implement batch splitting itself.
                                     # Note: Current per-line retry is a degradation, not recursive batch splitting.
DEFAULT_TRANSLATION_FAILED_PLACEHOLDER = "@@SUBTITLECAT_TRANSLATION_UNAVAILABLE@@" # ADDED: Default placeholder (MODIFIED for uniqueness)

# START OF ADDITIONS FOR GOOGLE API THROTTLING / COUNTER
_COUNTER_LOCK = threading.Lock()
GOOGLE_API_REQUEST_COUNT = 0 # Global counter for requests to Google Translate API
_LAST_THROTTLE_RESET_TIME = time.monotonic() # For timer-based reset
GOOGLE_API_REQUEST_LIMIT_DEFAULT = 90
GOOGLE_API_THROTTLE_SLEEP_SECONDS_DEFAULT = 60
GOOGLE_API_COUNTER_RESET_INTERVAL_SECONDS = 3600 # Reset counter every 1 hour

def _inc_api_counter_with_reset(core, service_name, log_prefix_throttle=""):
    """Increments the global API request counter thread-safely, checks for throttling,
    and handles periodic reset of the counter.
    Returns: (current_count, should_throttle_bool, throttle_duration_if_true)
    """
    global GOOGLE_API_REQUEST_COUNT, _LAST_THROTTLE_RESET_TIME
    with _COUNTER_LOCK:
        now = time.monotonic()
        if (now - _LAST_THROTTLE_RESET_TIME) > GOOGLE_API_COUNTER_RESET_INTERVAL_SECONDS:
            if GOOGLE_API_REQUEST_COUNT > 0 : # Only log if it was active
                core.logger.debug(f"[{service_name}] gtranslate: {log_prefix_throttle}Resetting Google API request counter (was {GOOGLE_API_REQUEST_COUNT}) after {GOOGLE_API_COUNTER_RESET_INTERVAL_SECONDS // 60} minutes.")
            GOOGLE_API_REQUEST_COUNT = 0
            _LAST_THROTTLE_RESET_TIME = now
        
        GOOGLE_API_REQUEST_COUNT += 1
        current_count = GOOGLE_API_REQUEST_COUNT
        
        # MODIFIED: Fetch limits from settings
        request_limit = int(_get_setting(core, "subtitlecat_google_api_request_limit", GOOGLE_API_REQUEST_LIMIT_DEFAULT))
        throttle_sleep_duration = int(_get_setting(core, "subtitlecat_google_api_throttle_sleep", GOOGLE_API_THROTTLE_SLEEP_SECONDS_DEFAULT))

        if request_limit > 0 and current_count > 0 and (current_count % request_limit == 0):
            core.logger.debug(f"[{service_name}] gtranslate: {log_prefix_throttle}(Throttle, Count: {current_count}) API request limit ({request_limit}) reached. Signaling throttle for {throttle_sleep_duration}s.")
            return current_count, True, throttle_sleep_duration
        return current_count, False, 0
# END OF ADDITIONS FOR GOOGLE API THROTTLING / COUNTER


# START OF SYNCHRONOUS HELPER FUNCTION FOR SINGLE LINE TRANSLATION (ThreadPoolExecutor target)
def _gtranslate_single_line_sync(line_to_translate, source_lang_override, target_lang, core, service_name, placeholder_str, recursion_depth_for_single_line, log_prefix_parent):
    """
    Translates a single line synchronously using requests.Session.
    Handles its own simple HTTP retries for this single line.
    The recursion_depth_for_single_line is passed from the caller to respect overall depth limits.
    """
    if recursion_depth_for_single_line >= MAX_PARTIAL_RETRIES:
        core.logger.error(f"[{service_name}] gtranslate: (SyncSingle, Depth {recursion_depth_for_single_line}) Max recursion depth reached for line '{line_to_translate[:30]}...'. Using placeholder.")
        return placeholder_str if line_to_translate.strip() else "", "auto"

    if not line_to_translate.strip():
        return "", "auto"

    params_single_line = [
        ('client', 'gtx'),
        ('sl', source_lang_override),
        ('tl', target_lang),
        ('dt', 't'),
        ('format', 'text'),
        ('q', line_to_translate)
    ]

    MAX_RETRIES_HTTP_SINGLE = 2
    API_TIMEOUT_SECONDS_SINGLE = 20
    RETRY_DELAY_BASE_SECONDS_SINGLE = 1
    detected_lang_single = "auto"

    for attempt in range(MAX_RETRIES_HTTP_SINGLE + 1):
        log_prefix_single = f"{log_prefix_parent} (SyncSingle Attempt {attempt+1}/{MAX_RETRIES_HTTP_SINGLE+1}) "
        
        _, should_throttle, throttle_duration = _inc_api_counter_with_reset(core, service_name, log_prefix_single)
        if should_throttle:
            time.sleep(throttle_duration)

        r_text_for_debug = "N/A"
        r = None # Initialize r to None for each attempt
        try:
            # Determine if POST is needed (though less likely for single lines)
            use_post = False
            MAX_URL_LENGTH_FOR_GET = 1900 
            query_string_for_check = urllib.parse.urlencode(params_single_line)
            potential_url_len = len(GOOGLE_TRANSLATE_URL) + 1 + len(query_string_for_check)
            if potential_url_len > MAX_URL_LENGTH_FOR_GET:
                use_post = True

            current_session = _get_session()
            if use_post:
                post_data = query_string_for_check.encode('utf-8')
                headers_for_post = current_session.headers.copy()
                headers_for_post['Content-Type'] = 'application/x-www-form-urlencoded;charset=utf-8'
                r = current_session.post(GOOGLE_TRANSLATE_URL, data=post_data, headers=headers_for_post, timeout=API_TIMEOUT_SECONDS_SINGLE)
            else:
                r = current_session.get(GOOGLE_TRANSLATE_URL, params=params_single_line, timeout=API_TIMEOUT_SECONDS_SINGLE)
            
            r_text_for_debug = r.text # Store before potential r.close() in finally
            r.raise_for_status()
            response_json = r.json()

            if not isinstance(response_json, list):
                raise ValueError(f"Expected list response, got {type(response_json)}")

            if (response_json and response_json[0] and isinstance(response_json[0], list) and
                    len(response_json[0]) > 0 and response_json[0][0] and
                    response_json[0][0][0] is not None):
                translated_text = str(response_json[0][0][0])
                
                if len(response_json) > 2 and isinstance(response_json[2], str) and response_json[2]:
                    detected_lang_single = response_json[2]
                elif len(response_json) > 8 and isinstance(response_json[8], list) and response_json[8] and \
                     isinstance(response_json[8][0], list) and response_json[8][0] and \
                     isinstance(response_json[8][0][0], str) and response_json[8][0][0]:
                    detected_lang_single = response_json[8][0][0]
                
                return translated_text, detected_lang_single # Successful, exit loop and function
            else:
                if _get_setting(core, "debug", False):
                    core.logger.debug(f"[{service_name}] gtranslate: {log_prefix_single}Malformed/empty segment for '{line_to_translate[:30]}...'. Response: {str(response_json)[:100]}. Full text: {r_text_for_debug[:200]}")
                # Fall through to retry logic if attempts remain

        except system_requests.exceptions.HTTPError as http_err:
            status_code = http_err.response.status_code if hasattr(http_err, 'response') and http_err.response is not None else "Unknown"
            if _get_setting(core, "debug", False):
                core.logger.debug(f"[{service_name}] gtranslate: {log_prefix_single}HTTPError {status_code} for '{line_to_translate[:30]}...'. Response: {r_text_for_debug[:200]}")
            if status_code == 429 and attempt < MAX_RETRIES_HTTP_SINGLE:
                delay = RETRY_DELAY_BASE_SECONDS_SINGLE * (2 ** attempt)
                time.sleep(delay)
                continue # Retry
        except system_requests.exceptions.Timeout:
            if _get_setting(core, "debug", False):
                 core.logger.debug(f"[{service_name}] gtranslate: {log_prefix_single}Timeout for '{line_to_translate[:30]}...'")
        except Exception as e: # Catch other exceptions
            if _get_setting(core, "debug", False):
                core.logger.debug(f"[{service_name}] gtranslate: {log_prefix_single}Error for '{line_to_translate[:30]}...': {e}. Response text: {r_text_for_debug[:200]}")
        finally: # This finally is for the try block inside the loop
            if r:
                r.close()
        
        # If we reached here, it means the try block didn't return successfully
        # or an exception was caught and handled (or fell through to here)
        if attempt < MAX_RETRIES_HTTP_SINGLE:
            delay = RETRY_DELAY_BASE_SECONDS_SINGLE * (2 ** attempt)
            time.sleep(delay)
            continue # Continue to the next attempt in the for loop
        
    # If the loop completes without a successful return, it means all retries failed
    core.logger.error(f"[{service_name}] gtranslate: {log_prefix_single}All {MAX_RETRIES_HTTP_SINGLE+1} attempts failed for single line '{line_to_translate[:30]}...'. Using placeholder.")
    return placeholder_str, "auto"
# END OF SYNCHRONOUS HELPER FUNCTION

# START OF REPLACEMENT _gtranslate_text_chunk
def _gtranslate_text_chunk(lines_to_translate, target_lang, core, service_name, recursion_depth=0):
    if not lines_to_translate:
        return [], "auto"

    placeholder_str = _get_setting(core, "subtitlecat_translation_failed_placeholder", DEFAULT_TRANSLATION_FAILED_PLACEHOLDER)

    if recursion_depth >= MAX_PARTIAL_RETRIES: # Max depth for this function itself
        log_prefix_guard = f"(Depth {recursion_depth}, MAX_RETRIES_EXCEEDED) "
        first_line_preview_msg = f"'{str(lines_to_translate[0])[:50]}...'" if lines_to_translate else "N/A"
        core.logger.error(f"[{service_name}] gtranslate: {log_prefix_guard}Max recursion depth ({MAX_PARTIAL_RETRIES}) for chunk processing. First: {first_line_preview_msg}. Using placeholders.")
        return [placeholder_str if line.strip() else "" for line in lines_to_translate], "auto"

    if not any(line.strip() for line in lines_to_translate):
        return ["" for _ in lines_to_translate], "auto"

    source_lang_override = _get_setting(core, "subtitlecat_source_lang_override", "auto").strip().lower()
    if not source_lang_override:
        source_lang_override = "auto"

    # --- STRATEGY CHANGE: Join lines into a single query string ---
    # Replace empty/whitespace-only lines with a single space to preserve their position
    # during split, but avoid sending truly empty strings to Google.
    prepared_lines_for_join = [line if line.strip() else " " for line in lines_to_translate]
    joined_query_text = "\n".join(prepared_lines_for_join)
    
    params_for_api_call = [
        ('client', 'gtx'),
        ('sl', source_lang_override),
        ('tl', target_lang),
        ('dt', 't'),        # Request translation
        ('format', 'text'), # Ensure newlines are preserved (though often default for dt=t)
        ('q', joined_query_text)
    ]
    # --- END OF STRATEGY CHANGE ---

    MAX_RETRIES_HTTP = 3
    RETRY_DELAY_BASE_SECONDS = 2
    MAX_URL_LENGTH_FOR_GET = 1900 
    API_TIMEOUT_SECONDS = 30

    translated_segments_for_this_call_final = None
    detected_lang_for_this_call = "auto"
    
    if recursion_depth == 0:
        _, should_throttle, throttle_duration = _inc_api_counter_with_reset(core, service_name, f"(BatchNLJoinThrottle, Depth {recursion_depth}) ")
        if should_throttle:
            time.sleep(throttle_duration)

    for attempt in range(MAX_RETRIES_HTTP + 1):
        r = None
        use_post = False
        log_prefix = f"(NLJoin Depth {recursion_depth}, Attempt {attempt+1}/{MAX_RETRIES_HTTP+1}) "

        if attempt > 0 or recursion_depth > 0:
            _, should_throttle_retry, throttle_duration_retry = _inc_api_counter_with_reset(core, service_name, log_prefix)
            if should_throttle_retry:
                time.sleep(throttle_duration_retry)
        
        try:
            # Use POST if the joined query text makes the URL too long for GET
            # Estimate query string length (rough, as urlencode adds overhead)
            # A more precise check would be `len(urllib.parse.urlencode(params_for_api_call))`
            # but 'q' is the dominant part.
            # Add some buffer for other params.
            potential_url_len_estimate = len(GOOGLE_TRANSLATE_URL) + len(urllib.parse.quote(joined_query_text)) + 100 
            if potential_url_len_estimate > MAX_URL_LENGTH_FOR_GET:
                use_post = True
        except Exception as e_url_len_check:
            core.logger.debug(f"[{service_name}] gtranslate: {log_prefix}Error during URL length check: {e_url_len_check}. Defaulting to GET.")
            use_post = False
        
        if _get_setting(core, "debug", False) and attempt == 0:
            method_used = "POST" if use_post else "GET"
            line_count_desc = f"{len(lines_to_translate)} lines joined"
            sl_info = f"(sl={source_lang_override})" if source_lang_override != "auto" else ""
            core.logger.debug(f"[{service_name}] gtranslate: {log_prefix}Translating {line_count_desc} to '{target_lang}' {sl_info} via {method_used} (single 'q'). Joined query len: {len(joined_query_text)} chars.")

        try:
            current_session = _get_session()
            if use_post:
                # For POST, params are sent in the body, URL encoded
                post_data = urllib.parse.urlencode(params_for_api_call).encode('utf-8')
                headers_for_post = current_session.headers.copy()
                headers_for_post['Content-Type'] = 'application/x-www-form-urlencoded;charset=utf-8'
                r = current_session.post(GOOGLE_TRANSLATE_URL, data=post_data, headers=headers_for_post, timeout=API_TIMEOUT_SECONDS)
            else:
                r = current_session.get(GOOGLE_TRANSLATE_URL, params=params_for_api_call, timeout=API_TIMEOUT_SECONDS)
            
            r.raise_for_status()
            response_content_type = r.headers.get('Content-Type', '').lower()
            if 'application/json' in response_content_type or 'text/javascript' in response_content_type:
                response_json = r.json()
            else:
                raise ValueError(f"gtranslate: Unexpected content type '{response_content_type}'. Body: {r.text[:200]}")

            if not isinstance(response_json, list):
                raise ValueError(f"gtranslate: Expected list response, got {type(response_json)}. Preview: {str(response_json)[:200]}")

            # --- PARSING LOGIC FOR SINGLE 'q' (newline-joined) RESPONSE ---
            # Based on `"".join(chunk[0] for chunk in response_json[0])` then `split('\n')`
            
            full_translated_text_blob = ""
            if (response_json and isinstance(response_json[0], list)):
                for chunk in response_json[0]:
                    if chunk and isinstance(chunk, list) and chunk[0] is not None:
                        full_translated_text_blob += str(chunk[0])
                    # else: a fragment was None or not a list, skip it.
            
            if not full_translated_text_blob.strip() and joined_query_text.strip():
                # API returned empty for a non-empty query, could be an issue.
                if _get_setting(core, "debug", False):
                    core.logger.debug(f"[{service_name}] gtranslate: {log_prefix}API returned empty translation blob for non-empty joined query. Response: {str(response_json)[:200]}")
                # Let it proceed to split, will likely result in count mismatch and fallback.
            
            translated_lines_after_split = full_translated_text_blob.split('\n')
            
            # Detected language extraction
            temp_sl_detected = "auto"
            if len(response_json) > 2 and isinstance(response_json[2], str) and response_json[2]:
                 candidate_lang = response_json[2]
                 if 2 <= len(candidate_lang) <= 7 and (candidate_lang.isalnum() or '-' in candidate_lang) and candidate_lang != "auto":
                    temp_sl_detected = candidate_lang
            if temp_sl_detected == "auto" and len(response_json) > 8: # Fallback from py-googletrans
                try: # try-except for robustness on potentially varied response structures
                    if isinstance(response_json[8], list) and response_json[8] and \
                       isinstance(response_json[8][0], list) and response_json[8][0] and \
                       isinstance(response_json[8][0][0], str) and response_json[8][0][0]:
                        candidate_lang = response_json[8][0][0]
                        if 2 <= len(candidate_lang) <= 7 and (candidate_lang.isalnum() or '-' in candidate_lang) and candidate_lang != "auto":
                           temp_sl_detected = candidate_lang
                except (IndexError, TypeError): pass # Ignore if structure doesn't match
            if temp_sl_detected != "auto":
                detected_lang_for_this_call = temp_sl_detected


            if len(translated_lines_after_split) == len(lines_to_translate):
                translated_segments_for_this_call_final = []
                for i, translated_line in enumerate(translated_lines_after_split):
                    # If the original line sent to join was just " " (placeholder for empty), result is ""
                    if prepared_lines_for_join[i] == " ": 
                        translated_segments_for_this_call_final.append("")
                    else:
                        translated_segments_for_this_call_final.append(translated_line)
                
                if _get_setting(core, "debug", False):
                    core.logger.debug(f"[{service_name}] gtranslate: {log_prefix}Newline-joined batch of {len(lines_to_translate)} lines translated successfully in one API call. Split count matched.")
                break # Successful translation of the whole chunk
            else:
                # Count mismatch: Fallback to per-line (only if not already in recursion for per-line)
                core.logger.warning(f"[{service_name}] gtranslate: {log_prefix}Newline-joined batch returned {len(translated_lines_after_split)} lines, expected {len(lines_to_translate)}. Response JSON[0] preview: {str(response_json[0])[:150] if response_json and response_json[0] else 'N/A'}.")
                if recursion_depth == 0: # Only trigger full per-line fallback if this is the first attempt for the chunk
                    core.logger.debug(f"[{service_name}] gtranslate: {log_prefix}Falling back to per-line translation for {len(lines_to_translate)} lines.")
                    
                    # Using ThreadPoolExecutor for per-line fallback
                    results_after_per_line_fallback = [None] * len(lines_to_translate)
                    lines_to_process_concurrently_map = {i: line for i, line in enumerate(lines_to_translate) if line.strip()}
                    
                    num_failed_in_fallback = 0
                    detected_langs_from_fallback = []

                    if lines_to_process_concurrently_map:
                        concurrent_limit = int(_get_setting(core, "subtitlecat_concurrent_google_retries", 5))
                        max_workers = min(concurrent_limit, len(lines_to_process_concurrently_map))
                        if max_workers <= 0: max_workers = 1
                        
                        core.logger.debug(f"[{service_name}] gtranslate: {log_prefix}Submitting {len(lines_to_process_concurrently_map)} single lines to ThreadPoolExecutor for fallback (max_workers={max_workers}).")
                        future_to_idx = {}
                        with concurrent.futures.ThreadPoolExecutor(max_workers=max_workers) as executor:
                            for original_idx, line_text_to_retry in lines_to_process_concurrently_map.items():
                                future = executor.submit(
                                    _gtranslate_single_line_sync,
                                    line_text_to_retry, source_lang_override, target_lang,
                                    core, service_name, placeholder_str,
                                    recursion_depth + 1, # Increment recursion depth for these single calls
                                    log_prefix
                                )
                                future_to_idx[future] = original_idx
                            
                            for i, line_text in enumerate(lines_to_translate): # Fill in blanks for non-stripped lines first
                                if not line_text.strip():
                                    results_after_per_line_fallback[i] = ""

                            for future in concurrent.futures.as_completed(future_to_idx):
                                original_idx = future_to_idx[future]
                                try:
                                    translated_text_single, single_lang_detected = future.result()
                                    results_after_per_line_fallback[original_idx] = translated_text_single
                                    if translated_text_single == placeholder_str:
                                        num_failed_in_fallback += 1
                                    if single_lang_detected and single_lang_detected != "auto":
                                        detected_langs_from_fallback.append(single_lang_detected)
                                except Exception as exc_future:
                                    core.logger.error(f"[{service_name}] gtranslate: {log_prefix}ThreadPool fallback task for idx {original_idx} errored: {exc_future}. Using placeholder.")
                                    results_after_per_line_fallback[original_idx] = placeholder_str
                                    num_failed_in_fallback += 1
                        
                        # Consolidate detected languages from fallback if main detection was 'auto'
                        if detected_lang_for_this_call == "auto" and detected_langs_from_fallback:
                            counts = Counter(dl for dl in detected_langs_from_fallback if dl != "auto")
                            if counts: detected_lang_for_this_call = counts.most_common(1)[0][0]

                        if num_failed_in_fallback > 0 and _get_setting(core, "debug", False):
                             core.logger.debug(f"[{service_name}] gtranslate: {log_prefix}Per-line fallback (ThreadPool) completed. {num_failed_in_fallback} still failed.")
                    else: # No lines with content to process
                         for i, line_text in enumerate(lines_to_translate):
                            if not line_text.strip(): results_after_per_line_fallback[i] = ""
                            else: results_after_per_line_fallback[i] = placeholder_str # Should not happen if map is empty

                    translated_segments_for_this_call_final = results_after_per_line_fallback
                    break # Break from main attempt loop, fallback has completed or used placeholders.
                else: # Already in a recursive call, or some other retry logic; don't infinitely recurse fallback.
                      # Let the main retry loop handle this attempt's failure.
                    if attempt < MAX_RETRIES_HTTP:
                        core.logger.debug(f"[{service_name}] gtranslate: {log_prefix}Newline-joined batch count mismatch on retry attempt {attempt+1}. Will retry full chunk if attempts left.")
                        delay = RETRY_DELAY_BASE_SECONDS * (2 ** attempt)
                        time.sleep(delay)
                        continue
                    else: # Fallback failed on last attempt
                        core.logger.error(f"[{service_name}] gtranslate: {log_prefix}Newline-joined batch count mismatch on final attempt. Using placeholders.")
                        translated_segments_for_this_call_final = [placeholder_str if line.strip() else "" for line in lines_to_translate]
                        break
            # --- END OF PARSING LOGIC FOR SINGLE 'q' ---

        except system_requests.exceptions.HTTPError as http_err:
            status_code = http_err.response.status_code if hasattr(http_err, 'response') and http_err.response is not None else "Unknown"
            response_text_preview = http_err.response.text[:200] if hasattr(http_err, 'response') and http_err.response and hasattr(http_err.response, 'text') else "N/A"
            core.logger.debug(f"[{service_name}] gtranslate: {log_prefix}HTTPError {status_code} for chunk. Response: {response_text_preview}")
            if status_code == 413: 
                 core.logger.error(f"[{service_name}] gtranslate: {log_prefix}HTTPError 413 (Payload Too Large). Using placeholders.")
                 translated_segments_for_this_call_final = [placeholder_str if line.strip() else "" for line in lines_to_translate]
                 break 
            if status_code == 429 and attempt < MAX_RETRIES_HTTP: 
                delay = RETRY_DELAY_BASE_SECONDS * (2 ** attempt) + int(_get_setting(core, "subtitlecat_google_api_throttle_sleep", 60) / 2) 
                core.logger.debug(f"[{service_name}] gtranslate: {log_prefix}HTTPError 429 (Rate Limit). Retrying in {delay}s...")
                time.sleep(delay)
                continue
            if attempt < MAX_RETRIES_HTTP :
                delay = RETRY_DELAY_BASE_SECONDS * (2 ** attempt)
                time.sleep(delay)
                continue
            else: 
                core.logger.error(f"[{service_name}] gtranslate: {log_prefix}HTTPError {status_code}: {http_err} after {MAX_RETRIES_HTTP+1} attempts. Using placeholders.")
                translated_segments_for_this_call_final = [placeholder_str if line.strip() else "" for line in lines_to_translate]
                break
        except system_requests.exceptions.Timeout as e_timeout:
            core.logger.debug(f"[{service_name}] gtranslate: {log_prefix}Timeout: {e_timeout}")
            if attempt < MAX_RETRIES_HTTP:
                delay = RETRY_DELAY_BASE_SECONDS * (2**attempt)
                time.sleep(delay)
                continue
            core.logger.error(f"[{service_name}] gtranslate: {log_prefix}Timeout after {MAX_RETRIES_HTTP+1} attempts. Using placeholders.")
            translated_segments_for_this_call_final = [placeholder_str if line.strip() else "" for line in lines_to_translate]
            break
        except ValueError as e_json_or_parse: 
            response_text_preview = r.text[:200] if r and hasattr(r, 'text') else "N/A"
            core.logger.debug(f"[{service_name}] gtranslate: {log_prefix}ValueError (e.g. JSONDecodeError/ContentType): {e_json_or_parse}. Response: {response_text_preview}")
            if attempt < MAX_RETRIES_HTTP:
                delay = RETRY_DELAY_BASE_SECONDS * (2**attempt)
                time.sleep(delay)
                continue
            core.logger.error(f"[{service_name}] gtranslate: {log_prefix}ValueError after {MAX_RETRIES_HTTP+1} attempts. Using placeholders.")
            translated_segments_for_this_call_final = [placeholder_str if line.strip() else "" for line in lines_to_translate]
            break
        except Exception as e_unexp: 
            response_text_preview = r.text[:200] if r and hasattr(r, 'text') else "N/A"
            core.logger.debug(f"[{service_name}] gtranslate: {log_prefix}Unexpected error during API interaction: {e_unexp}. Response: {response_text_preview}")
            if attempt < MAX_RETRIES_HTTP:
                delay = RETRY_DELAY_BASE_SECONDS * (2**attempt)
                time.sleep(delay)
                continue
            core.logger.error(f"[{service_name}] gtranslate: {log_prefix}Unexpected error after {MAX_RETRIES_HTTP+1} attempts. Using placeholders.")
            translated_segments_for_this_call_final = [placeholder_str if line.strip() else "" for line in lines_to_translate]
            break
        finally:
            if r:
                r.close()
            
    if translated_segments_for_this_call_final is None:
        core.logger.error(f"[{service_name}] gtranslate: (FinalFallbackNL) Translation attempt loop completed without setting final segments. Using placeholders.")
        translated_segments_for_this_call_final = [placeholder_str if line.strip() else "" for line in lines_to_translate]

    if len(translated_segments_for_this_call_final) != len(lines_to_translate):
        core.logger.error(f"[{service_name}] gtranslate: (FinalLengthCheckNL) CRITICAL MISMATCH: Final segment count ({len(translated_segments_for_this_call_final)}) != input count ({len(lines_to_translate)}). Padding/truncating.")
        if len(translated_segments_for_this_call_final) < len(lines_to_translate):
            padding = [placeholder_str if lines_to_translate[i].strip() else "" for i in range(len(translated_segments_for_this_call_final), len(lines_to_translate))]
            translated_segments_for_this_call_final.extend(padding)
        else:
            translated_segments_for_this_call_final = translated_segments_for_this_call_final[:len(lines_to_translate)]
            
    return translated_segments_for_this_call_final, detected_lang_for_this_call
# END OF REPLACEMENT _gtranslate_text_chunk
# END OF DEFINITIONS FOR CLIENT-SIDE TRANSLATION

# START OF IMAGE FIX #3: Helpers for tag protection (module-level)
# MODIFICATION: Point 4 - Handle digit transliteration in placeholders
_PLACEHOLDER_SENTINEL_PREFIX = "\u2063@@SCPTAG_hexidx_"
_PLACEHOLDER_SUFFIX = "_hexidx_SCP@@"
# MODIFIED REGEX for improved tag attribute handling
__TAG_REGEX_FOR_PROTECTION = re.compile(r'(<(?:"[^"]*"|\'[^\']*\'|[^>"\'])*>|{(?:"[^"]*"|\'[^\']*\'|[^}\'"])*})')

# Text cleaning for control characters (ZWSP, LRM, RLM)
# Add more if needed. \u200c (ZWNJ), \ufeff (BOM as ZWNBSP) could also be candidates.
_CONTROL_CHARS_TO_CLEAN = '\u200b\u200e\u200f'
_CLEAN_CTRL_TRANSLATION_TABLE = str.maketrans('', '', _CONTROL_CHARS_TO_CLEAN)


def _protect_subtitle_tags(text_line):
    """Replaces tags with placeholders and returns the new text, the list of tags,
    and a boolean indicating if the line was purely tags.
    MODIFICATION 2.3: Handles all-tag lines."""
    stripped_line_no_tags = __TAG_REGEX_FOR_PROTECTION.sub('', text_line).strip()
    if not stripped_line_no_tags:
        return text_line, [], True

    tags_found = []
    def _replacer(match):
        tag = match.group(1)
        tags_found.append(tag)
        # MODIFICATION: Point 4 - Use hex-encoded index in placeholder
        placeholder_idx_str = hex(len(tags_found)-1)[2:] # [2:] to remove "0x"
        return f"{_PLACEHOLDER_SENTINEL_PREFIX}{placeholder_idx_str}{_PLACEHOLDER_SUFFIX}"

    processed_text = __TAG_REGEX_FOR_PROTECTION.sub(_replacer, text_line)
    return processed_text, tags_found, False

def _restore_subtitle_tags(text_line_with_placeholders, tags_list):
    """Replaces placeholders in the text with their original tag strings."""
    for i in range(len(tags_list) - 1, -1, -1):
        original_tag_content = tags_list[i]
        # MODIFICATION: Point 4 - Use hex-encoded index in placeholder
        placeholder_idx_str = hex(i)[2:] # [2:] to remove "0x"
        placeholder = f"{_PLACEHOLDER_SENTINEL_PREFIX}{placeholder_idx_str}{_PLACEHOLDER_SUFFIX}"
        text_line_with_placeholders = text_line_with_placeholders.replace(placeholder, original_tag_content)
    return text_line_with_placeholders
# END OF IMAGE FIX #3: Helpers

# START OF FUNCTION _upload_translation_to_subtitlecat
def _upload_translation_to_subtitlecat(core, service_name, translated_srt_content_str, target_sc_lang_code, original_filename_stem_from_sc, detected_source_language_code, movie_page_full_url):
    upload_url = "https://www.subtitlecat.com/upload_subtitles.php"

    name_for_upload = original_filename_stem_from_sc
    if original_filename_stem_from_sc.endswith("-orig.srt"):
        name_for_upload = original_filename_stem_from_sc[:-len("-orig.srt")] + ".srt"
    elif original_filename_stem_from_sc.endswith("-orig"):
        name_for_upload = original_filename_stem_from_sc[:-len("-orig")] + ".srt"
    else:
        if not original_filename_stem_from_sc.endswith(".srt"):
            name_for_upload = f"{original_filename_stem_from_sc}.srt"
            core.logger.debug(f"[{service_name}] original_filename_stem_from_sc ('{original_filename_stem_from_sc}') did not end with -orig or -orig.srt. Appended .srt: '{name_for_upload}'")


    payload = {
        'filename': name_for_upload,
        'content': translated_srt_content_str,
        'language': target_sc_lang_code,
        'orig_language': detected_source_language_code,
    }

    headers = {
        'User-Agent': __user_agent, # This is fine, as it's part of the headers dict passed to session.post
        'Referer': movie_page_full_url or __subtitlecat_base_url,
        'Content-Type': 'application/x-www-form-urlencoded; charset=UTF-8',
        'X-Requested-With': 'XMLHttpRequest',
    }

    core.logger.debug(f"[{service_name}] Attempting to upload translated subtitle '{name_for_upload}' to {upload_url} for language '{target_sc_lang_code}', source lang '{detected_source_language_code}'. Referer: {headers['Referer']}")

    try:
        # MODIFICATION: Use thread-local session and remove lock
        # with _SC_SESSION_LOCK: # ADDED LOCK
        response = _get_session().post(upload_url, data=payload, headers=headers, timeout=30) # headers will merge with session headers
        response.raise_for_status()

        json_response = response.json()
        if core.settings and core.settings.get("debug", False):
             core.logger.debug(f"[{service_name}] Upload response from Subtitlecat: {str(json_response)[:500]}")
        elif not core.settings:
             core.logger.debug(f"[{service_name}] Upload response from Subtitlecat (details omitted, core.settings unavailable). Echo: {json_response.get('echo')}")


        if json_response.get("echo") == "ok" and json_response.get("url"):
            returned_path = json_response["url"]
            if returned_path.startswith("/"):
                 new_srt_url_on_sc = urljoin(__subtitlecat_base_url, returned_path.lstrip('/'))
            else:
                 new_srt_url_on_sc = urljoin(__subtitlecat_base_url, returned_path)

            core.logger.debug(f"[{service_name}] Successfully uploaded translated subtitle. New URL: {new_srt_url_on_sc}")
            return new_srt_url_on_sc
        else:
            core.logger.error(f"[{service_name}] Subtitlecat upload failed or returned unexpected response. Echo: {json_response.get('echo')}, URL: {json_response.get('url')}, Message: {json_response.get('message')}")
            return None

    except system_requests.exceptions.Timeout:
        core.logger.error(f"[{service_name}] Timeout during subtitle upload to {upload_url}.")
        return None
    except system_requests.exceptions.RequestException as e:
        core.logger.error(f"[{service_name}] RequestException during subtitle upload: {e}")
        return None
    except ValueError as e_json: # Catches JSONDecodeError
        response_text_preview = response.text[:200] if 'response' in locals() and hasattr(response, 'text') else 'N/A'
        core.logger.error(f"[{service_name}] JSONDecodeError parsing Subtitlecat upload response: {e_json}. Response text: {response_text_preview}")
        return None
    except Exception as e_unexp:
        core.logger.error(f"[{service_name}] Unexpected error during subtitle upload: {e_unexp}")
        return None
# END OF FUNCTION _upload_translation_to_subtitlecat


# ---------------------------------------------------------------------------
# SEARCH REQUEST BUILDER
# ---------------------------------------------------------------------------
def build_search_requests(core, service_name, meta):
    if not _AIOHTTP_AVAILABLE and _get_setting(core, "debug", False): # Log aiohttp fallback if debug is on
        core.logger.debug(f"[{service_name}] aiohttp library not available. Async translation features will use synchronous fallbacks.")

    if meta.languages:
        normalized_kodi_langs = []
        for kodi_lang in meta.languages:
            sc_lang = __kodi_regional_lang_map.get(kodi_lang.lower(), (None, kodi_lang))[1]
            normalized_kodi_langs.append(sc_lang)
        meta.languages = normalized_kodi_langs
        core.logger.debug(f"[{service_name}] Normalized meta.languages for search: {meta.languages}")

    core.logger.debug(f"[{service_name}] Building search requests for: {meta}")
    query_title = meta.tvshow if meta.is_tvshow else meta.title
    if not query_title:
        core.logger.debug(f"[{service_name}] No title found in meta. Aborting search for this provider.")
        return []
    search_query_parts = [query_title]
    if meta.year:
        search_query_parts.append(str(meta.year))
    search_term = " ".join(search_query_parts)
    encoded_query = urllib.parse.quote_plus(search_term)
    search_url = f"{__subtitlecat_base_url}/index.php?search={encoded_query}&d=1"
    core.logger.debug(f"[{service_name}] Search URL: {search_url}")
    return [{
        'method': 'GET',
        'url': search_url,
        'headers': {'User-Agent': __user_agent}, # Note: This search request is not made with _get_session() by this provider directly, it's passed to the core.
    }]

# ---------------------------------------------------------------------------
# SEARCH RESPONSE PARSER
# ---------------------------------------------------------------------------
def parse_search_response(core, service_name, meta, response):
    core.logger.debug(f"[{service_name}] Parsing search response. Status: {response.status_code}, URL: {response.url if response else 'N/A'}")
    results = []
    if response.status_code != 200:
        core.logger.error(f"[{service_name}] Search request failed (status {response.status_code}) – {response.url}")
        return results
    try:
        soup = BeautifulSoup(response.text, 'html.parser')
    except Exception as exc:
        core.logger.error(f"[{service_name}] BeautifulSoup error for search response: {exc}")
        return results
    display_name_for_service = getattr(
        core.services.get(service_name), "display_name", service_name
    )
    results_table_body = soup.select_one('div.subtitles table tbody')
    if not results_table_body:
        results_table_body = soup.find('tbody')
        if not results_table_body:
             core.logger.debug(f"[{service_name}] A.1: Main results table body not found on {response.url}")
             return results
    rows = results_table_body.find_all('tr')
    core.logger.debug(f"[{service_name}] Found {len(rows)} potential movie rows on search page: {response.url}")

    wanted_languages_lower = {lang.lower() for lang in meta.languages}
    wanted_iso2 = {core.utils.get_lang_id(l, core.kodi.xbmc.ISO_639_1).lower()
                   for l in meta.languages
                   if core.utils.get_lang_id(l, core.kodi.xbmc.ISO_639_1)}

    def _base_name(name: str) -> str:
        return re.split(r'[ (]', name, 1)[0].lower()
    seen_lang_conv_errors = set()

    shared_translation_url = "https://www.subtitlecat.com/get_shared_translation.php"
    shared_translation_timeout = _get_setting(core, "http_timeout", 10)

    for row in rows:
        link_tag = row.select_one('td:first-child > a')
        if not link_tag:
            core.logger.debug(f"[{service_name}] No link tag in a row. Skipping.")
            continue
        href = link_tag.get('href', "")
        if not (href.lstrip('/').startswith('subs/') and href.endswith('.html')):
            core.logger.debug(f"[{service_name}] Link href '{href}' doesn't match expected pattern. Skipping.")
            continue
        movie_title_on_page = link_tag.get_text(strip=True) or "Unknown Title"

        if not _is_title_close(meta.title, movie_title_on_page):
            core.logger.debug(f"[{service_name}] Title '{movie_title_on_page}' (from search result row) not close enough to wanted title '{meta.title}'. Skipping this row.")
            continue

        movie_page_full_url = urljoin(__subtitlecat_base_url, href)
        year_guard_fetched_soup = None
        if meta.year:
            if meta.year and str(int(meta.year) - 1) not in row.text and str(meta.year) not in row.text:
                core.logger.debug(f"[{service_name}] Year '{meta.year}' (or '{int(meta.year) -1 }') not in row text for '{movie_title_on_page}'. Attempting fallback: checking detail page title from {movie_page_full_url}.")
                try:
                    # MODIFICATION: Use thread-local session and remove lock
                    # with _SC_SESSION_LOCK: # ADDED LOCK
                    temp_detail_response = _get_session().get(movie_page_full_url, timeout=15)
                    temp_detail_response.raise_for_status()
                    temp_detail_soup_for_year_check = BeautifulSoup(temp_detail_response.text, 'html.parser')
                    title_tag_element = temp_detail_soup_for_year_check.find('title')
                    detail_page_title_text = title_tag_element.get_text(strip=True) if title_tag_element else ""
                    if str(meta.year) not in detail_page_title_text:
                        core.logger.debug(f"[{service_name}] Year '{meta.year}' also not in detail page title ('{detail_page_title_text}'). Skipping row for '{movie_title_on_page}'.")
                        continue
                    else:
                        core.logger.debug(f"[{service_name}] Year '{meta.year}' found in detail page title for '{movie_title_on_page}'. Proceeding with this row.")
                        year_guard_fetched_soup = temp_detail_soup_for_year_check
                except system_requests.exceptions.RequestException as e_req_fallback:
                    core.logger.debug(f"[{service_name}] Fallback year check: Request error for {movie_page_full_url}: {e_req_fallback}. Skipping row for '{movie_title_on_page}'.")
                    continue
                except Exception as e_parse_fallback:
                    core.logger.debug(f"[{service_name}] Fallback year check: Error processing detail page {movie_page_full_url} for title: {e_parse_fallback}. Skipping row for '{movie_title_on_page}'.")
                    continue
        if (meta.is_tvshow
            and hasattr(meta, "episode") and meta.episode is not None
            and hasattr(meta, "season")  and meta.season  is not None
            and f"S{meta.season:02d}E{meta.episode:02d}" not in row.text):
            continue
        core.logger.debug(f"[{service_name}] Processing movie link: '{movie_title_on_page}' -> {movie_page_full_url}")
        detail_soup = None
        if year_guard_fetched_soup:
            core.logger.debug(f"[{service_name}] Reusing detail page soup for {movie_page_full_url} (obtained during year guard fallback).")
            detail_soup = year_guard_fetched_soup
        else:
            try:
                # MODIFICATION: Use thread-local session and remove lock
                # with _SC_SESSION_LOCK: # ADDED LOCK
                detail_response = _get_session().get(movie_page_full_url, timeout=15)
                detail_response.raise_for_status()
                detail_soup = BeautifulSoup(detail_response.text, 'html.parser')
            except Exception as exc:
                core.logger.error(f"[{service_name}] Detail page fetch/parse failed for {movie_page_full_url}: {exc}")
                continue
        try:
            filename_parts = href.split('/')
            filename_base_from_href = filename_parts[-1].replace('.html', '') if filename_parts else "subtitle"
            original_id_from_href = filename_parts[-2] if len(filename_parts) > 1 else "id"

        except IndexError as e_url_parse:
            core.logger.error(f"[{service_name}] Could not parse ID/filename from relative URL '{href}': {e_url_parse}")
            filename_base_from_href = "subtitle"
            original_id_from_href = "id"

        language_entries = detail_soup.select('div.all-sub div.row > div[class*="col-"] > div.sub-single')
        if not language_entries:
            core.logger.debug(f"[{service_name}] No language entries ('div.all-sub div.row > div[class*=\"col-\"] > div.sub-single') found on detail page: {movie_page_full_url}")
        for entry_div in language_entries:
            img_tag = entry_div.select_one('span:first-child > img[alt]')
            if not img_tag:
                core.logger.debug(f"[{service_name}] No 'span:first-child > img[alt]' in language entry. Skipping.")
                continue
            sc_lang_code = img_tag.get('alt')
            if not sc_lang_code:
                core.logger.debug(f"[{service_name}] 'span:first-child > img[alt]' found but no alt attribute. Skipping.")
                continue
            lang_name_span = entry_div.select_one('span:first-child + span')
            sc_lang_name_full = sc_lang_code
            if lang_name_span:
                temp_name = lang_name_span.get_text(strip=True)
                if temp_name:
                    sc_lang_name_full = temp_name

            kodi_target_lang_full = sc_lang_name_full
            kodi_target_lang_2_letter = sc_lang_code.split('-')[0].lower()

            sc_lang_code_lower = sc_lang_code.lower()
            if sc_lang_code.lower().startswith('zh-'):
                kodi_target_lang_full = 'Chinese'
                kodi_target_lang_2_letter = 'zh'
            elif sc_lang_code_lower in __kodi_regional_lang_map:
                map_full_name, map_iso_code = __kodi_regional_lang_map[sc_lang_code_lower]
                kodi_target_lang_full = map_full_name
                kodi_target_lang_2_letter = map_iso_code
            else:
                try:
                    converted_full_name = core.utils.get_lang_id(sc_lang_code, core.kodi.xbmc.ENGLISH_NAME)
                    if converted_full_name:
                        kodi_target_lang_full = converted_full_name
                    converted_iso2_code = core.utils.get_lang_id(kodi_target_lang_full, core.kodi.xbmc.ISO_639_1)
                    if converted_iso2_code:
                         kodi_target_lang_2_letter = converted_iso2_code.lower()
                except Exception as e_lang_conv:
                    if sc_lang_code not in seen_lang_conv_errors:
                        core.logger.debug(f"[{service_name}] Error converting lang code '{sc_lang_code}' (name: '{sc_lang_name_full}'): {e_lang_conv}. Using fallbacks: Full='{kodi_target_lang_full}', ISO2='{kodi_target_lang_2_letter}'.")
                        seen_lang_conv_errors.add(sc_lang_code)

            if (_base_name(kodi_target_lang_full) not in wanted_languages_lower
                    and kodi_target_lang_2_letter not in wanted_iso2):
                continue

            constructed_filename = f"{original_id_from_href}-{filename_base_from_href}-{sc_lang_code}.srt"

            shared_translation_found_and_used = False
            if _get_setting(core, "subtitlecat_include_shared", True):
                try:
                    shared_headers = {
                        'User-Agent': __user_agent,  # This is fine
                        'Referer': movie_page_full_url,
                        'Accept': 'application/json, */*'
                    }
                    core.logger.debug(
                        f"[{service_name}] Attempting to fetch shared translation for '{constructed_filename}' from {shared_translation_url} (referer: {movie_page_full_url})"
                    )
                    # MODIFICATION: Use thread-local session and remove lock
                    # with _SC_SESSION_LOCK: # ADDED LOCK
                    shared_response = _get_session().get(
                        shared_translation_url,
                        headers=shared_headers,
                        timeout=shared_translation_timeout
                    )

                    if shared_response.status_code == 200 and shared_response.headers.get('content-type', '').startswith('application/json'):
                        json_response = shared_response.json()
                        shared_srt_text = json_response.get("text")
                        shared_srt_lang = json_response.get("language")

                        if shared_srt_text and isinstance(shared_srt_text, str) and shared_srt_text.strip():
                            core.logger.debug(
                                f"[{service_name}] Found shared translation for '{constructed_filename}' (lang: {shared_srt_lang or 'N/A'})"
                            )

                            action_args_shared = {
                                'method_type': 'SHARED_TRANSLATION_CONTENT',
                                'srt_content': shared_srt_text,
                                'filename': constructed_filename,
                                'lang': kodi_target_lang_full,
                                'service_name': service_name,
                                'detail_url': movie_page_full_url,
                                'lang_code': sc_lang_code,
                            }
                            item_color_shared = 'cyan'

                            results.append({
                                'service_name': service_name,
                                'service': display_name_for_service,
                                'lang': kodi_target_lang_full,
                                'name': f"{movie_title_on_page} ({sc_lang_name_full}) [Shared]",
                                'rating': 0,
                                'lang_code': kodi_target_lang_2_letter,
                                'sync': 'false',
                                'impaired': 'false',
                                'color': item_color_shared,
                                'action_args': action_args_shared
                            })
                            core.logger.debug(
                                f"[{service_name}] Added result for shared translation: '{constructed_filename}'"
                            )
                            shared_translation_found_and_used = True
                        else:
                            core.logger.debug(
                                f"[{service_name}] Shared translation response for '{constructed_filename}' was empty or invalid. JSON: {str(json_response)[:200]}"
                            )
                    elif shared_response.status_code == 200:  # Already a .debug call, body preview is fine
                        core.logger.debug(
                            f"[{service_name}] Shared translation for '{constructed_filename}' returned status 200 but non-JSON content-type: {shared_response.headers.get('content-type', '')}. Body: {shared_response.text[:200]}"
                        )
                    else:  # Already a .debug call, body preview is fine
                        core.logger.debug(
                            f"[{service_name}] Failed to fetch shared translation for '{constructed_filename}'. Status: {shared_response.status_code}, Body: {shared_response.text[:200]}"
                        )

                except system_requests.exceptions.RequestException as req_exc_shared:
                    core.logger.error(
                        f"[{service_name}] RequestException fetching shared translation for '{constructed_filename}': {req_exc_shared}"
                    )
                except ValueError as val_err_shared:  # Catches JSONDecodeError
                    core.logger.error(
                        f"[{service_name}] ValueError (JSON decode) fetching shared translation for '{constructed_filename}': {val_err_shared}"
                    )
                except Exception as e_shared:
                    core.logger.error(
                        f"[{service_name}] Unexpected error fetching shared translation for '{constructed_filename}': {e_shared}"
                    )

            if shared_translation_found_and_used:
                continue

            action_args = {
                'url': '', 'lang': kodi_target_lang_full,
                'filename': constructed_filename,
                'gzip': False, 'service_name': service_name,
                'detail_url': movie_page_full_url,
                'lang_code': sc_lang_code,
                'needs_poll': False,
                'needs_client_side_translation': False
            }
            item_color = 'white'

            patch_determined_href = None
            a_tag = entry_div.select_one('a.green-link[href*=".srt"]')
            if not a_tag:
                a_tag = entry_div.select_one(r'a[href$=".srt"], a[href*=".srt?download="]')
            if a_tag:
                _raw_href = a_tag.get('href')
                if _raw_href: patch_determined_href = _raw_href

            normalized_sc_lang_for_cache_lookup = sc_lang_code
            if sc_lang_code:
                normalized_sc_lang_for_cache_lookup = __kodi_regional_lang_map.get(
                    sc_lang_code.lower(), (None, sc_lang_code)
                )[1]

            cache_key = (movie_page_full_url, normalized_sc_lang_for_cache_lookup.lower())
            cached_url = _TRANSLATED_CACHE.get(cache_key) # Using .get() from SimpleLRUCache
            if cached_url:
                patch_determined_href = cached_url
                core.logger.debug(f"[{service_name}] Using cached translated URL (from _TRANSLATED_CACHE): {cached_url} for {sc_lang_name_full} on {movie_page_full_url}")

            if patch_determined_href:
                action_args['url'] = urljoin(__subtitlecat_base_url, patch_determined_href)
            else:
                btn = entry_div.select_one('button.yellow-link[onclick*="translate_from_server_folder"]')
                if not btn:
                    btn = entry_div.select_one('button[onclick*="translate_from_server_folder"]')

                if btn:
                    _onclick_attr = btn.get('onclick')
                    if not _onclick_attr:
                        core.logger.debug(f"[{service_name}] Translate button for '{sc_lang_name_full}' has no onclick. Skipping.")
                        continue

                    target_translation_lang = sc_lang_code
                    derived_folder_path = f"/subs/{original_id_from_href}/"
                    derived_orig_filename_stem = f"{filename_base_from_href}-orig"
                    source_srt_filename = f"{derived_orig_filename_stem}.srt"
                    source_srt_url = urljoin(__subtitlecat_base_url, derived_folder_path + source_srt_filename)

                    core.logger.debug(f"[{service_name}] Client translation needed: target_lang='{target_translation_lang}', source_url='{source_srt_url}'")

                    action_args.update({
                        'needs_client_side_translation': True,
                        'original_srt_url': source_srt_url,
                        'target_translation_lang': target_translation_lang, # This is SC lang code (e.g. 'en', 'pt-br')
                        'url': '', # No direct download URL yet
                    })
                    item_color = 'yellow'
                else:
                    core.logger.debug(f"[{service_name}] No download link or translate button for '{sc_lang_name_full}'. Skipping.")
                    continue

            results.append({
                'service_name': service_name, 'service': display_name_for_service,
                'lang': kodi_target_lang_full, 'name': f"{movie_title_on_page} ({sc_lang_name_full})",
                'rating': 0, 'lang_code': kodi_target_lang_2_letter, 'sync': 'false', 'impaired': 'false',
                'color': item_color,
                'action_args': action_args
            })
            core.logger.debug(f"[{service_name}] Added result '{action_args['filename']}' for lang '{kodi_target_lang_full}' (ClientTranslate: {action_args['needs_client_side_translation']}, URL: {action_args['url']})")

    core.logger.debug(f"[{service_name}] Returning {len(results)} results after parsing.")
    return results

# ---------------------------------------------------------------------------
# DOWNLOAD REQUEST BUILDER
# ---------------------------------------------------------------------------
def build_download_request(core, service_name, args):
    _filename_from_args = args.get('filename', 'unknown_subtitle.srt')
    core.logger.debug(f"[{service_name}] Building download request for: {_filename_from_args}, Args: {str(args)[:500]}")
    
    placeholder_str = _get_setting(core, "subtitlecat_translation_failed_placeholder", DEFAULT_TRANSLATION_FAILED_PLACEHOLDER)

    if args.get('needs_client_side_translation') and _get_setting(core, "debug", False):
        source_lang_override_setting = _get_setting(core, "subtitlecat_source_lang_override", "auto").strip().lower()
        if source_lang_override_setting and source_lang_override_setting != "auto":
            core.logger.debug(f"[{service_name}] Client-side translation: Using source language override '{source_lang_override_setting}' from settings.")
        else:
            core.logger.debug(f"[{service_name}] Client-side translation: Using automatic source language detection (sl=auto).")

    def _save_from_subtitlecat_url(path_from_core, url_to_download):
        _timeout = _get_setting(core, "http_timeout", 15)
        resp_for_save = None
        core.logger.debug(f"[{service_name}] _save_from_subtitlecat_url: Downloading from {url_to_download} to {repr(path_from_core)} with timeout {_timeout}s")
        try:
            # MODIFICATION: Use thread-local session and remove lock
            # with _SC_SESSION_LOCK: # ADDED LOCK
            # Headers passed here will be merged with session's default headers (like User-Agent)
            resp_for_save = _get_session().get(url_to_download, timeout=_timeout, stream=True)
            resp_for_save.raise_for_status()
            raw_bytes = resp_for_save.content
            core.logger.debug(f"[{service_name}] _save_from_subtitlecat_url: Download successful, {len(raw_bytes)} bytes received.")

            _post_download_fix_encoding(core, service_name, raw_bytes, path_from_core)
            core.logger.debug(f"[{service_name}] _save_from_subtitlecat_url: Processing complete for {repr(path_from_core)}")
            return True
        except system_requests.exceptions.Timeout:
            core.logger.error(f"[{service_name}] _save_from_subtitlecat_url: Timeout during download from {url_to_download} for {repr(path_from_core)}")
            return False
        except system_requests.exceptions.RequestException as e_req:
            core.logger.error(f"[{service_name}] _save_from_subtitlecat_url: RequestException for {url_to_download}: {e_req}")
            return False
        except Exception as e_proc:
            core.logger.error(f"[{service_name}] _save_from_subtitlecat_url: Error processing {url_to_download}: {e_proc}")
            return False
        finally:
            if resp_for_save:
                resp_for_save.close()

    if args.get('needs_client_side_translation'):
        core.logger.debug(f"[{service_name}] Starting client-side translation for '{_filename_from_args}'")
        original_srt_url = args['original_srt_url']
        target_gtranslate_lang = args['target_translation_lang'] 
        
        final_translated_srt_str = None
        overall_detected_source_lang = "auto"
        original_srt_text_content = "NOT_FETCHED_DUE_TO_CACHE_HIT" 

        # REFINED: Conditional event loop policy setting
        if _AIOHTTP_AVAILABLE and asyncio and sys.platform.startswith("win") and _get_setting(core, "force_selector_loop", False):
            try:
                # ProactorEventLoopPolicy is default on Win >=3.8 and an attribute of asyncio module.
                # SelectorEventLoopPolicy is an attribute of asyncio module on Win >=3.7.
                # We only want to switch if it's currently Proactor.
                if sys.version_info >= (3, 8) and hasattr(asyncio, 'WindowsProactorEventLoopPolicy'): # Check Proactor exists
                    current_policy = asyncio.get_event_loop_policy()
                    if isinstance(current_policy, asyncio.WindowsProactorEventLoopPolicy):
                        if hasattr(asyncio, 'WindowsSelectorEventLoopPolicy'): # Check Selector exists
                            asyncio.set_event_loop_policy(asyncio.WindowsSelectorEventLoopPolicy())
                            core.logger.debug(f"[{service_name}] Applied WindowsSelectorEventLoopPolicy (was Proactor) due to 'force_selector_loop' setting.")
                        # else: # Not strictly needed to log this, but could be for deep debug
                        #    core.logger.warning(f"[{service_name}] Cannot switch from Proactor: WindowsSelectorEventLoopPolicy not found on asyncio module.")
                # else: # Not Python 3.8+ or Proactor policy not available on asyncio module for various reasons
                #    core.logger.debug(f"[{service_name}] Not on Python 3.8+ or Proactor policy not available/not current. No check/change made for Proactor to Selector.")
            except Exception as e_policy:
                core.logger.error(f"[{service_name}] Failed to apply/check WindowsSelectorEventLoopPolicy: {e_policy}")

        # REMOVED: Event loop management (event_loop_for_this_job, loop_created_by_bdr) as it's no longer used here.
        
        cache_key_content = (original_srt_url, target_gtranslate_lang)
        cached_content_data = _CLIENT_TRANSLATED_CONTENT_CACHE.get(cache_key_content)
        
        try: # This try block no longer needs a finally for loop cleanup
            if cached_content_data:
                core.logger.debug(f"[{service_name}] Using cached client-translated SRT content for {original_srt_url} to {target_gtranslate_lang}.")
                final_translated_srt_str = cached_content_data['srt_content']
                overall_detected_source_lang = cached_content_data['detected_source_lang']
            else:
                core.logger.debug(f"[{service_name}] Downloading original SRT from: {original_srt_url}")
                dl_timeout = _get_setting(core, "http_timeout", 20)
                # MODIFICATION: Use thread-local session and remove lock
                # with _SC_SESSION_LOCK: # ADDED LOCK
                original_srt_response = _get_session().get(original_srt_url, timeout=dl_timeout)
                original_srt_response.raise_for_status()
                original_srt_text_content = original_srt_response.text 
                original_srt_response.close() 
                core.logger.debug(f"[{service_name}] Downloaded original SRT content ({len(original_srt_text_content)} chars).")

                parsed_subs = list(srt.parse(original_srt_text_content))
                core.logger.debug(f"[{service_name}] Parsed {len(parsed_subs)} subtitle items from original SRT.")
                
                contains_any_tags_globally = False
                all_logical_lines_original_protected = []
                logical_line_metadata = [] 

                for srt_idx, srt_item in enumerate(parsed_subs):
                    original_logical_lines_for_srt_item = srt_item.content.split('\n')
                    for logical_line_idx, logical_line_content in enumerate(original_logical_lines_for_srt_item):
                        protected_text, tags_map, is_all_tag_line = _protect_subtitle_tags(logical_line_content)
                        if tags_map:
                            contains_any_tags_globally = True
                        all_logical_lines_original_protected.append(protected_text)
                        logical_line_metadata.append({
                            'original_srt_item_idx': srt_idx,
                            'original_logical_line_idx_within_srt_item': logical_line_idx,
                            'tags_map_for_this_logical_line': tags_map,
                            'is_all_tag_logical_line': is_all_tag_line
                        })
                core.logger.debug(f"[{service_name}] Prepared {len(all_logical_lines_original_protected)} logical lines for translation processing.")

                texts_to_translate_for_api = []
                for original_idx, line_content in enumerate(all_logical_lines_original_protected):
                    if not logical_line_metadata[original_idx]['is_all_tag_logical_line']:
                        cleaned_line = line_content.translate(_CLEAN_CTRL_TRANSLATION_TABLE)
                        texts_to_translate_for_api.append(cleaned_line)
                
                core.logger.debug(f"[{service_name}] Found {len(texts_to_translate_for_api)} actual text lines requiring translation API calls (after cleaning and tag filtering).")

                all_translated_pure_text_lines_from_google = [] 
                all_detected_source_langs_overall = []

                current_api_batch_lines_for_google = []
                current_api_batch_char_count = 0
                
                api_char_limit = GOOGLE_API_Q_PARAM_CHAR_LIMIT
                api_line_limit = MAX_LINES_PER_API_CALL_CONFIG
                batch_delay_setting = _get_setting(core, "subtitlecat_translation_batch_delay", DEFAULT_BATCH_DELAY_SECONDS)

                if not texts_to_translate_for_api:
                     core.logger.debug(f"[{service_name}] No text lines to translate after filtering. Skipping API calls.")
                else:
                    for i, protected_text_line_for_google in enumerate(texts_to_translate_for_api):
                        line_char_count = len(protected_text_line_for_google)
                        potential_new_char_count = current_api_batch_char_count + line_char_count + (1 if current_api_batch_lines_for_google else 0)

                        if current_api_batch_lines_for_google and \
                        (potential_new_char_count > api_char_limit or len(current_api_batch_lines_for_google) >= api_line_limit):
                            core.logger.debug(f"[{service_name}] Processing API batch of {len(current_api_batch_lines_for_google)} lines, {current_api_batch_char_count} chars.")
                            
                            translated_segments, detected_lang_from_chunk = _gtranslate_text_chunk(
                                current_api_batch_lines_for_google, target_gtranslate_lang, core, service_name, 0
                            )
                            
                            if len(translated_segments) != len(current_api_batch_lines_for_google):
                                core.logger.error(f"[{service_name}] CRITICAL MISMATCH: _gtranslate_text_chunk returned {len(translated_segments)}, expected {len(current_api_batch_lines_for_google)}. Correcting.")
                                corrected_segments = [placeholder_str if line.strip() else "" for line in current_api_batch_lines_for_google]
                                for k_idx in range(min(len(translated_segments), len(corrected_segments))):
                                    corrected_segments[k_idx] = translated_segments[k_idx]
                                all_translated_pure_text_lines_from_google.extend(corrected_segments)
                            else:
                                all_translated_pure_text_lines_from_google.extend(translated_segments)
                            
                            if detected_lang_from_chunk and detected_lang_from_chunk != "auto":
                                all_detected_source_langs_overall.append(detected_lang_from_chunk)
                            
                            current_api_batch_lines_for_google = []
                            current_api_batch_char_count = 0
                            
                            if batch_delay_setting > 0 and i < len(texts_to_translate_for_api): 
                                time.sleep(batch_delay_setting)

                        current_api_batch_lines_for_google.append(protected_text_line_for_google)
                        current_api_batch_char_count += line_char_count
                        if len(current_api_batch_lines_for_google) > 1: 
                            current_api_batch_char_count += 1 
                    
                    if current_api_batch_lines_for_google:
                        core.logger.debug(f"[{service_name}] Processing final API batch of {len(current_api_batch_lines_for_google)} lines, {current_api_batch_char_count} chars.")
                        translated_segments, detected_lang_from_chunk = _gtranslate_text_chunk(
                            current_api_batch_lines_for_google, target_gtranslate_lang, core, service_name, 0
                        )

                        if len(translated_segments) != len(current_api_batch_lines_for_google):
                            core.logger.error(f"[{service_name}] CRITICAL MISMATCH (final batch): _gtranslate_text_chunk returned {len(translated_segments)}, expected {len(current_api_batch_lines_for_google)}. Correcting.")
                            corrected_segments = [placeholder_str if line.strip() else "" for line in current_api_batch_lines_for_google]
                            for k_idx in range(min(len(translated_segments), len(corrected_segments))):
                                    corrected_segments[k_idx] = translated_segments[k_idx]
                            all_translated_pure_text_lines_from_google.extend(corrected_segments)
                        else:
                            all_translated_pure_text_lines_from_google.extend(translated_segments)

                        if detected_lang_from_chunk and detected_lang_from_chunk != "auto":
                            all_detected_source_langs_overall.append(detected_lang_from_chunk)
                
                final_flat_processed_logical_lines = [""] * len(all_logical_lines_original_protected)
                current_translated_text_idx = 0

                for original_idx, original_protected_line_val in enumerate(all_logical_lines_original_protected):
                    meta_for_line = logical_line_metadata[original_idx]
                    if meta_for_line['is_all_tag_logical_line']:
                        final_flat_processed_logical_lines[original_idx] = original_protected_line_val
                    else:
                        if current_translated_text_idx < len(all_translated_pure_text_lines_from_google):
                            translated_line_from_google = all_translated_pure_text_lines_from_google[current_translated_text_idx]
                            
                            if translated_line_from_google == placeholder_str:
                                final_flat_processed_logical_lines[original_idx] = placeholder_str
                            else:
                                restored_line = translated_line_from_google
                                if contains_any_tags_globally and meta_for_line['tags_map_for_this_logical_line']:
                                    restored_line = _restore_subtitle_tags(translated_line_from_google, meta_for_line['tags_map_for_this_logical_line'])
                                final_flat_processed_logical_lines[original_idx] = html.unescape(restored_line)
                            current_translated_text_idx += 1
                        else:
                            core.logger.error(f"[{service_name}] Mismatch during final reconstruction. Expected translated text for original_idx {original_idx} but ran out. Using placeholder.")
                            final_flat_processed_logical_lines[original_idx] = placeholder_str if all_logical_lines_original_protected[original_idx].strip() else ""
                
                if current_translated_text_idx != len(all_translated_pure_text_lines_from_google): 
                     core.logger.error(f"[{service_name}] Mismatch: Processed {current_translated_text_idx} translated lines from google, but API processing yielded {len(all_translated_pure_text_lines_from_google)} lines for {len(texts_to_translate_for_api)} inputs.")

                flat_line_cursor = 0
                for srt_idx_rebuild, srt_item_rebuild in enumerate(parsed_subs):
                    num_logical_lines_in_this_srt_item = srt_item_rebuild.content.count('\n') + 1
                    end_slice = min(flat_line_cursor + num_logical_lines_in_this_srt_item, len(final_flat_processed_logical_lines))
                    new_content_lines_for_srt_item = final_flat_processed_logical_lines[flat_line_cursor : end_slice]
                    
                    if len(new_content_lines_for_srt_item) != num_logical_lines_in_this_srt_item:
                        core.logger.error(f"[{service_name}] Mismatch during SRT item reconstruction for srt_idx {srt_idx_rebuild}. Expected {num_logical_lines_in_this_srt_item} lines, got {len(new_content_lines_for_srt_item)}. Padding.")
                        padding_count = num_logical_lines_in_this_srt_item - len(new_content_lines_for_srt_item)
                        if padding_count > 0:
                            new_content_lines_for_srt_item.extend([""] * padding_count)

                    parsed_subs[srt_idx_rebuild].content = "\n".join(new_content_lines_for_srt_item)
                    flat_line_cursor += num_logical_lines_in_this_srt_item
                
                if flat_line_cursor != len(final_flat_processed_logical_lines):
                     core.logger.error(f"[{service_name}] Mismatch: Processed {flat_line_cursor} flat lines for SRT reconstruction, but had {len(final_flat_processed_logical_lines)} total.")

                if all_detected_source_langs_overall:
                    counts = Counter(all_detected_source_langs_overall)
                    if counts:
                        overall_detected_source_lang = counts.most_common(1)[0][0]
                core.logger.debug(f"[{service_name}] Overall detected source language from API calls: {overall_detected_source_lang}")

                final_translated_srt_str = srt.compose(parsed_subs)
                core.logger.debug(f"[{service_name}] Successfully composed translated SRT string ({len(final_translated_srt_str)} chars).")

            new_url_from_sc = None
            if _get_setting(core, 'subtitlecat_upload_translations', False):
                core.logger.debug(f"[{service_name}] Uploading client-translated subtitle is enabled.")
                sc_original_filename_stem = "unknown_stem"
                try:
                    parsed_url_path = urllib.parse.urlparse(original_srt_url).path
                    sc_original_filename_stem = urllib.parse.unquote(parsed_url_path.split('/')[-1])
                    if not sc_original_filename_stem and '/' in parsed_url_path:
                         sc_original_filename_stem = urllib.parse.unquote(parsed_url_path.split('/')[-2])
                    if sc_original_filename_stem.lower().endswith(".srt"):
                        sc_original_filename_stem = sc_original_filename_stem[:-4]
                    core.logger.debug(f"[{service_name}] Extracted sc_original_filename_stem for upload: {sc_original_filename_stem}")
                except Exception as e_parse_stem:
                    core.logger.error(f"[{service_name}] Error parsing original_srt_url for filename stem: {e_parse_stem}. Using default '{sc_original_filename_stem}'.")

                target_sc_lang_code_for_upload = args.get('lang_code') 
                if not target_sc_lang_code_for_upload:
                     core.logger.error(f"[{service_name}] Could not determine target Subtitlecat language code for upload. Aborting upload.")
                else:
                    overall_detected_source_lang_for_upload = overall_detected_source_lang
                    if overall_detected_source_lang_for_upload == "auto" or not overall_detected_source_lang_for_upload:
                        core.logger.debug(f"[{service_name}] Original language for upload is '{overall_detected_source_lang_for_upload}'. Defaulting to 'en'.")
                        overall_detected_source_lang_for_upload = "en" 

                    new_url_from_sc = _upload_translation_to_subtitlecat(
                        core, service_name, final_translated_srt_str,
                        target_sc_lang_code_for_upload, sc_original_filename_stem,      
                        overall_detected_source_lang_for_upload, args.get('detail_url')          
                    )
            else:
                core.logger.debug(f"[{service_name}] Uploading client-translated subtitle is disabled by setting.")

            if not new_url_from_sc and not cached_content_data: 
                core.logger.debug(f"[{service_name}] Storing client-translated content in _CLIENT_TRANSLATED_CONTENT_CACHE for key: {cache_key_content}")
                _CLIENT_TRANSLATED_CONTENT_CACHE[cache_key_content] = {
                    'srt_content': final_translated_srt_str,
                    'detected_source_lang': overall_detected_source_lang
                }

            if new_url_from_sc:
                core.logger.debug(f"[{service_name}] Upload successful. Callback will download from: {new_url_from_sc}")
                cache_key_lang = args.get('lang_code', target_gtranslate_lang).lower() 
                # Using __setitem__ from SimpleLRUCache for _TRANSLATED_CACHE
                _TRANSLATED_CACHE[(args.get('detail_url'), cache_key_lang)] = new_url_from_sc
                core.logger.debug(f"[{service_name}] Stored translated URL in _TRANSLATED_CACHE for key ({args.get('detail_url')}, {cache_key_lang})")
                if _get_setting(core, 'subtitlecat_notify_upload', True):
                    core.kodi.notification('Subtitle uploaded to Subtitlecat')
                return {
                    'method': 'REQUEST_CALLBACK',
                    'save_callback': lambda path: _save_from_subtitlecat_url(path, new_url_from_sc),
                    'filename': _filename_from_args,
                }
            else:
                core.logger.debug(f"[{service_name}] Upload failed or disabled. Using locally translated SRT content directly.")
                def _save_client_translated_srt(path_from_core):
                    try:
                        import io 
                        bom = _get_setting(core, 'force_bom', False)
                        final_encoding = 'utf-8-sig' if bom else 'utf-8'
                        with io.open(path_from_core, 'w', encoding=final_encoding) as f:
                            f.write(final_translated_srt_str) 
                        core.logger.debug(f"[{service_name}] Client-translated SRT saved to '{path_from_core}' with encoding '{final_encoding}'.")
                        return True
                    except Exception as e_save:
                        core.logger.error(f"[{service_name}] Failed to save client-translated SRT to '{path_from_core}': {e_save}")
                        return False
                return {
                    'method': 'CLIENT_SIDE_TRANSLATED', 
                    'url': args['original_srt_url'], 
                    'save_callback': _save_client_translated_srt,
                    'filename': _filename_from_args,
                }

        except system_requests.exceptions.RequestException as e_req:
            core.logger.error(f"[{service_name}] Client-side translation: Network error downloading original SRT {original_srt_url}: {e_req}")
            raise
        except srt.SRTParseError as e_srt:
            core.logger.error(f"[{service_name}] Client-side translation: SRT parsing error for {original_srt_url}: {e_srt}. Content preview: {original_srt_text_content[:200] if isinstance(original_srt_text_content, str) else 'N/A'}")
            raise
        except Exception as e_pipeline:
            core.logger.error(f"[{service_name}] Client-side translation pipeline failed for '{_filename_from_args}': {e_pipeline}")
            import traceback
            core.logger.error(traceback.format_exc())
            raise
        # REMOVED: finally block that was cleaning up event_loop_for_this_job


    elif args.get('method_type') == 'SHARED_TRANSLATION_CONTENT':
        core.logger.debug(f"[{service_name}] Using shared translation content for '{args.get('filename')}'")
        srt_content_to_save = args.get('srt_content', '')

        def _save_shared_srt(path_from_core):
            try:
                current_srt_text_str = ""
                if isinstance(srt_content_to_save, bytes):
                    core.logger.debug(f"[{service_name}] Shared SRT content was bytes, decoding as UTF-8.")
                    current_srt_text_str = srt_content_to_save.decode('utf-8', errors='replace')
                else:
                    current_srt_text_str = str(srt_content_to_save)

                temp_unescaped_srt_text = html.unescape(current_srt_text_str)
                temp_bytes_for_fixing = temp_unescaped_srt_text.encode('utf-8') 

                _post_download_fix_encoding(core, service_name, temp_bytes_for_fixing, path_from_core)

                core.logger.debug(f"[{service_name}] Shared SRT content successfully processed and saved to '{path_from_core}'")
                return True
            except Exception as e_save:
                core.logger.error(f"[{service_name}] Failed to save shared SRT content to '{path_from_core}': {e_save}")
                return False

        return {
            'method': 'REQUEST_CALLBACK',
            'save_callback': _save_shared_srt,
            'filename': args.get('filename'),
        }

    else: # Standard direct download path
        core.logger.debug(f"[{service_name}] Proceeding with standard download for '{_filename_from_args}'.")
        final_url_for_direct_dl = args.get('url', '')

        if not final_url_for_direct_dl:
            error_msg = f"[{service_name}] Final URL for '{_filename_from_args}' is empty. (Args: {str(args)[:200]}). Cannot download."
            core.logger.error(error_msg)
            raise ValueError(error_msg) 

        core.logger.debug(f"[{service_name}] Prepared direct download request for '{_filename_from_args}' from {final_url_for_direct_dl}.")
        return {
            'method': 'REQUEST_CALLBACK',
            'save_callback': lambda path: _save_from_subtitlecat_url(path, final_url_for_direct_dl),
            'filename': _filename_from_args,
        }
# END OF MODIFICATION

#--- END OF FILE subtitlecat.py ---