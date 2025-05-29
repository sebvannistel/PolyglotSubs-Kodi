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
_SC_NEWLINE_MARKER_ = "\u2063SCNL\u2063" # ADDED for review 2.3 (preserves newlines)

from collections import Counter # Added for determining overall detected source language
# No 'log = logger.Logger.get_logger(__name__)' needed; use 'core.logger' directly.

# light-weight cache (detail_url, lang_code) ➜ final .srt URL
_TRANSLATED_CACHE = {}     # survives for the lifetime of the add-on (NOTE: Population mechanism via _wait_for_translated removed)

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

# Keep a persistent session across *all* calls in this provider
_SC_SESSION = system_requests.Session()
_SC_SESSION.headers.update({'User-Agent': __user_agent})

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
DEFAULT_TRANSLATION_FAILED_PLACEHOLDER = "[TRANSLATION UNAVAILABLE]" # ADDED: Default placeholder

# START OF REPLACEMENT _gtranslate_text_chunk
def _gtranslate_text_chunk(lines_to_translate, target_lang, core, service_name, recursion_depth=0):
    # lines_to_translate is a list of strings (logical lines from SRT, already tag-protected)
    # This function processes the entire received `lines_to_translate` list.
    # If it's a batch, it makes one API call. If that call is partial, it retries tail segments one-by-one.
    # If called with a single line, it processes that single line.

    if not lines_to_translate: # Handle empty list first
        return [], "auto"

    placeholder_str = _get_setting(core, "subtitlecat_translation_failed_placeholder", DEFAULT_TRANSLATION_FAILED_PLACEHOLDER)

    # +++ START OF RECURSION GUARD +++
    if recursion_depth >= MAX_PARTIAL_RETRIES:
        log_prefix_guard = f"(Depth {recursion_depth}, MAX_RETRIES_EXCEEDED) "
        # Ensure lines_to_translate is not empty before accessing lines_to_translate[0]
        first_line_preview_msg = f"'{str(lines_to_translate[0])[:50]}...'" # Safe, lines_to_translate is not empty here

        core.logger.error(f"[{service_name}] gtranslate: {log_prefix_guard}Max recursion depth ({MAX_PARTIAL_RETRIES}) reached. "
                         f"Using placeholders for {len(lines_to_translate)} line(s). First line preview: {first_line_preview_msg}")
        return [placeholder_str if line.strip() else "" for line in lines_to_translate], "auto"
    # +++ END OF RECURSION GUARD +++

    # Handle all-empty lines upfront (this check is after the recursion guard)
    if not any(line.strip() for line in lines_to_translate):
        # core.logger.debug(f"[{service_name}] gtranslate: All lines in chunk are empty, skipping translation.")
        return ["" for _ in lines_to_translate], "auto" # Return list of empty strings matching input length

    params_list_for_api_call = [
        ('client', 'gtx'),
        ('sl', 'auto'),
        ('tl', target_lang),
        ('dt', 't'),
        ('format', 'text') # Added to help preserve explicit line breaks if any are part of 'q'
    ]
    for line in lines_to_translate:
        # Send a space if line is empty or whitespace only, as Google might ignore empty 'q'
        params_list_for_api_call.append(('q', line if line.strip() else " "))

    MAX_RETRIES_HTTP = 3
    RETRY_DELAY_BASE_SECONDS = 2
    MAX_URL_LENGTH_FOR_GET = 1900
    API_TIMEOUT_SECONDS = 30 # MODIFIED: was 20

    translated_segments_for_this_call_final = None # Will hold the final list of translated/placeholder segments
    detected_lang_for_this_call = "auto"

    for attempt in range(MAX_RETRIES_HTTP + 1):
        r = None
        use_post = False
        log_prefix = f"(Depth {recursion_depth}, Attempt {attempt+1}/{MAX_RETRIES_HTTP+1}) "
        current_call_is_single_line = (len(lines_to_translate) == 1)

        try:
            # URL length check for GET vs POST
            query_string_for_check = urllib.parse.urlencode(params_list_for_api_call)
            potential_url_len = len(GOOGLE_TRANSLATE_URL) + 1 + len(query_string_for_check)
            if potential_url_len > MAX_URL_LENGTH_FOR_GET:
                use_post = True
        except Exception as e_url_len_check:
            core.logger.debug(f"[{service_name}] gtranslate: {log_prefix}Error during URL length check: {e_url_len_check}. Defaulting to GET.")
            use_post = False
        
        if _get_setting(core, "debug", False) and attempt == 0 : # Log only on first attempt of a batch/line
            first_q_preview = lines_to_translate[0][:60] if lines_to_translate else "N/A"
            method_used = "POST" if use_post else "GET"
            line_count_desc = f"{len(lines_to_translate)} segment(s)" if not current_call_is_single_line else "single segment"
            core.logger.debug(f"[{service_name}] gtranslate: {log_prefix}Translating {line_count_desc} to '{target_lang}' via {method_used}. First q: {first_q_preview}...")

        try:
            if use_post:
                post_data = urllib.parse.urlencode(params_list_for_api_call).encode('utf-8')
                headers_for_post = _SC_SESSION.headers.copy()
                headers_for_post['Content-Type'] = 'application/x-www-form-urlencoded;charset=utf-8'
                r = _SC_SESSION.post(GOOGLE_TRANSLATE_URL, data=post_data, headers=headers_for_post, timeout=API_TIMEOUT_SECONDS)
            else:
                r = _SC_SESSION.get(GOOGLE_TRANSLATE_URL, params=params_list_for_api_call, timeout=API_TIMEOUT_SECONDS)
            
            r.raise_for_status()
            response_json = r.json()

            if not isinstance(response_json, list):
                raise ValueError(f"gtranslate: Expected list response, got {type(response_json)}. Preview: {str(response_json)[:200]}")

            # --- Start: Parsing logic ---
            parsed_segments_from_api_response = []
            parsed_successfully_this_api_call_count = 0

            # response_json[j] contains data for lines_to_translate[j]
            # Each response_json[j] should be like: [ [["Translated text", "Original text", ...]], null, "src_lang_code", ... ]
            for j in range(len(lines_to_translate)): # Iterate up to the number of lines we sent
                translated_text_for_segment = None
                original_line_text = lines_to_translate[j]

                if j < len(response_json) and response_json[j] is not None:
                    segment_data_array = response_json[j]
                    if (segment_data_array and isinstance(segment_data_array, list) and
                        segment_data_array[0] and isinstance(segment_data_array[0], list) and
                        len(segment_data_array[0]) > 0 and segment_data_array[0][0] is not None):
                        translated_text_for_segment = str(segment_data_array[0][0])
                        parsed_successfully_this_api_call_count += 1
                    else: # Malformed segment data for this specific line
                        if _get_setting(core, "debug", False):
                            core.logger.debug(f"[{service_name}] gtranslate: {log_prefix}Malformed segment data for line '{original_line_text[:30]}...': {str(segment_data_array)[:100]}.")
                        # This segment is considered failed for this API call. Handled by mismatch logic below.
                        pass
                else: # Google's response was shorter than expected number of 'q' params
                    if _get_setting(core, "debug", False) and j < len(response_json) and response_json[j] is None: # Explicit null for a segment
                         core.logger.debug(f"[{service_name}] gtranslate: {log_prefix}Response was null for segment {j+1}/{len(lines_to_translate)}. Original: '{original_line_text[:30]}...'.")
                    # This (and subsequent ones) are missing. Handled by mismatch logic.
                    pass
                
                # Append what we got, even if it's None (placeholder for now)
                parsed_segments_from_api_response.append(translated_text_for_segment)


            # --- Language Detection for this call ---
            # Try to find language code: often after all translation blocks if all were successful.
            # Or sometimes at a fixed index like response_json[2] or response_json[8][0][0] in older formats.
            temp_detected_lang = "auto"
            expected_lang_code_idx = parsed_successfully_this_api_call_count # Index after actual translation blocks if all were parsed
            if parsed_successfully_this_api_call_count == len(lines_to_translate): # All segments might have been returned
                if len(response_json) > expected_lang_code_idx and isinstance(response_json[expected_lang_code_idx], str) and response_json[expected_lang_code_idx]:
                    candidate_lang = response_json[expected_lang_code_idx]
                    if 2 <= len(candidate_lang) <= 7 and (candidate_lang.isalnum() or '-' in candidate_lang) and candidate_lang != "auto":
                        temp_detected_lang = candidate_lang
            
            if temp_detected_lang == "auto": # Fallbacks
                if len(response_json) > 2 and isinstance(response_json[2], str) and response_json[2]:
                    temp_detected_lang = response_json[2]
                elif len(response_json) > 8 and isinstance(response_json[8], list) and response_json[8] and \
                     isinstance(response_json[8][0], list) and response_json[8][0] and \
                     isinstance(response_json[8][0][0], str) and response_json[8][0][0]:
                    temp_detected_lang = response_json[8][0][0]
            
            if temp_detected_lang != "auto":
                detected_lang_for_this_call = temp_detected_lang
            # --- End Language Detection ---

            # --- Handle Mismatches / Per-Line Retry ---
            if parsed_successfully_this_api_call_count == len(lines_to_translate):
                # Perfect match for this batch/single call. Ensure empty strings for originally empty lines.
                final_batch_results = []
                for i, translated_text in enumerate(parsed_segments_from_api_response):
                    if not lines_to_translate[i].strip(): # Original was empty/whitespace
                        final_batch_results.append("")
                    else:
                        final_batch_results.append(translated_text if translated_text is not None else placeholder_str) # Should not be None here
                translated_segments_for_this_call_final = final_batch_results
                break # Successful HTTP call and all segments processed/accounted for.

            elif parsed_successfully_this_api_call_count < len(lines_to_translate) and not current_call_is_single_line:
                # MISMATCH on a BATCH call: API returned fewer segments than 'q' params sent, or some were malformed.
                # We have `parsed_segments_from_api_response` which contains `None` for failed/missing segments.
                core.logger.debug(f"[{service_name}] gtranslate: {log_prefix}Batch API call returned {parsed_successfully_this_api_call_count} valid segments, expected {len(lines_to_translate)}. Attempting per-line retry for failed/missing segments.")
                
                results_after_per_line_retry = []
                num_failed_in_per_line_retry = 0

                for i, original_line_text in enumerate(lines_to_translate):
                    if i < len(parsed_segments_from_api_response) and parsed_segments_from_api_response[i] is not None:
                        # This segment was successfully translated in the batch
                        if not original_line_text.strip(): # Original was empty
                             results_after_per_line_retry.append("")
                        else:
                             results_after_per_line_retry.append(parsed_segments_from_api_response[i])
                    else:
                        # This segment failed in the batch or was missing; retry it singly.
                        if _get_setting(core, "debug", False):
                            core.logger.debug(f"[{service_name}] gtranslate: {log_prefix}Retrying failed/missing segment {i+1} individually: '{original_line_text[:30]}...'")
                        if i > 0 and (parsed_segments_from_api_response[i-1] is None or i >= parsed_successfully_this_api_call_count):
                            time.sleep(0.1) # Small polite delay if previous was also a retry or we are in the tail
                        
                        # Call _gtranslate_text_chunk for this single line.
                        # recursion_depth+1 to ensure MAX_PARTIAL_RETRIES is respected for overall problem depth.
                        single_line_translated_list, single_line_lang = _gtranslate_text_chunk(
                            [original_line_text], target_lang, core, service_name, recursion_depth + 1
                        )
                        
                        if single_line_translated_list and len(single_line_translated_list) == 1:
                            single_result = single_line_translated_list[0]
                            results_after_per_line_retry.append(single_result)
                            if single_result == placeholder_str:
                                num_failed_in_per_line_retry += 1
                            # Update overall detected language if this single line provided a non-auto one and current is auto
                            if single_line_lang and single_line_lang != "auto" and detected_lang_for_this_call == "auto":
                                detected_lang_for_this_call = single_line_lang
                        else: # Should not happen if single-line call returns placeholder on failure
                            core.logger.error(f"[{service_name}] gtranslate: {log_prefix}Per-line retry for '{original_line_text[:30]}...' unexpectedly did not return one segment. Using placeholder.") # MODIFIED TO .error
                            results_after_per_line_retry.append(placeholder_str)
                            num_failed_in_per_line_retry += 1
                
                if num_failed_in_per_line_retry > 0 and _get_setting(core, "debug", False):
                     core.logger.debug(f"[{service_name}] gtranslate: {log_prefix}Per-line retry phase completed. {num_failed_in_per_line_retry} segment(s) still failed and used placeholder.")
                
                translated_segments_for_this_call_final = results_after_per_line_retry
                break # Processed the batch, with per-line degradation for tail. Exit HTTP retry loop.
            
            elif current_call_is_single_line and parsed_successfully_this_api_call_count < 1:
                # Single line call failed to get a translation from API response.
                # This means the API returned something like [null] or [[]] for the single 'q'.
                core.logger.debug(f"[{service_name}] gtranslate: {log_prefix}Single line translation API response did not yield text for '{lines_to_translate[0][:30]}...'. This attempt will use placeholder.")
                # Fallback to placeholder will happen after loop if all HTTP attempts fail.
                # No break here, let HTTP retries try again for this single line.
                # If this *was* the last HTTP attempt, the except block will handle it.
                # We need to make sure `translated_segments_for_this_call_final` gets set to placeholder if all attempts fail.
                pass # Let the HTTP retry loop continue for this single line if attempts remain.

            elif parsed_successfully_this_api_call_count > len(lines_to_translate): # Should not happen
                core.logger.error(f"[{service_name}] gtranslate: {log_prefix}Got MORE segments ({parsed_successfully_this_api_call_count}) than expected ({len(lines_to_translate)}). Truncating.")
                # Ensure empty strings for originally empty lines.
                final_batch_results = []
                for i, translated_text in enumerate(parsed_segments_from_api_response[:len(lines_to_translate)]):
                    if not lines_to_translate[i].strip(): # Original was empty/whitespace
                        final_batch_results.append("")
                    else:
                        final_batch_results.append(translated_text if translated_text is not None else placeholder_str)
                translated_segments_for_this_call_final = final_batch_results
                break
            
            # If we are here, it means it was a single line call that DID get a translation,
            # or some other state. If translated_segments_for_this_call_final is set, we break.
            # This path should ideally be covered by the `parsed_successfully_this_api_call_count == len(lines_to_translate)`
            # for single line calls too.

            # This means the API call itself (HTTP) was successful, but parsing yielded an issue not yet fully resolved
            # (e.g. single line call, parsed_successfully_this_api_call_count = 0, but not last HTTP attempt).
            # Let the HTTP retry loop proceed if attempts remain.
            if attempt < MAX_RETRIES_HTTP:
                core.logger.debug(f"[{service_name}] gtranslate: {log_prefix}API call attempt {attempt+1} had issues but not fatal HTTP error. Will retry if attempts left.")
                # Delay before retrying this problematic batch/line
                delay = RETRY_DELAY_BASE_SECONDS * (2 ** attempt)
                time.sleep(delay)
                continue
            else: # Last HTTP attempt, and still not resolved (e.g. single line returned null content)
                core.logger.error(f"[{service_name}] gtranslate: {log_prefix}All HTTP attempts for this chunk failed to yield full translation. Using placeholders for failed segments.")
                # This state means even after HTTP retries, we couldn't get proper translation for all lines.
                # `parsed_segments_from_api_response` might have some `None`s.
                final_results_on_exhaustion = []
                for i, original_line in enumerate(lines_to_translate):
                    if i < len(parsed_segments_from_api_response) and parsed_segments_from_api_response[i] is not None:
                        if not original_line.strip(): final_results_on_exhaustion.append("")
                        else: final_results_on_exhaustion.append(parsed_segments_from_api_response[i])
                    else:
                        if not original_line.strip(): final_results_on_exhaustion.append("") # Empty remains empty
                        else: final_results_on_exhaustion.append(placeholder_str)
                translated_segments_for_this_call_final = final_results_on_exhaustion
                break # Exit HTTP retry loop.

        except system_requests.exceptions.HTTPError as http_err:
            status_code = http_err.response.status_code if http_err.response else "Unknown"
            response_text_preview = ""
            if http_err.response is not None and hasattr(http_err.response, 'text'):
                response_text_preview = http_err.response.text[:200]
            
            core.logger.debug(f"[{service_name}] gtranslate: {log_prefix}HTTPError {status_code} for chunk. Response: {response_text_preview}")
            if status_code == 413: # Payload too large
                 core.logger.error(f"[{service_name}] gtranslate: {log_prefix}HTTPError 413 (Payload Too Large). This should be prevented by caller. Using placeholders.")
                 translated_segments_for_this_call_final = [placeholder_str if line.strip() else "" for line in lines_to_translate]
                 break
            if status_code == 429 and attempt < MAX_RETRIES_HTTP: # Rate Limit
                delay = RETRY_DELAY_BASE_SECONDS * (2 ** attempt)
                core.logger.debug(f"[{service_name}] gtranslate: {log_prefix}HTTPError 429 (Rate Limit). Retrying in {delay}s...")
                time.sleep(delay)
                continue
            # Other HTTP errors, or 429 on last attempt
            if attempt < MAX_RETRIES_HTTP :
                delay = RETRY_DELAY_BASE_SECONDS * (2 ** attempt)
                time.sleep(delay)
                continue # Retry non-fatal HTTP errors
            else: # Last attempt
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
        except ValueError as e_json_or_parse: # Includes JSONDecodeError
            response_text_preview = r.text[:200] if r and hasattr(r, 'text') else "N/A"
            core.logger.debug(f"[{service_name}] gtranslate: {log_prefix}ValueError (e.g. JSONDecodeError): {e_json_or_parse}. Response: {response_text_preview}")
            if attempt < MAX_RETRIES_HTTP:
                delay = RETRY_DELAY_BASE_SECONDS * (2**attempt)
                time.sleep(delay)
                continue
            core.logger.error(f"[{service_name}] gtranslate: {log_prefix}ValueError after {MAX_RETRIES_HTTP+1} attempts. Using placeholders.")
            translated_segments_for_this_call_final = [placeholder_str if line.strip() else "" for line in lines_to_translate]
            break
        except Exception as e_unexp:
            response_text_preview = r.text[:200] if r and hasattr(r, 'text') else "N/A"
            core.logger.debug(f"[{service_name}] gtranslate: {log_prefix}Unexpected error: {e_unexp}. Response: {response_text_preview}")
            if attempt < MAX_RETRIES_HTTP:
                delay = RETRY_DELAY_BASE_SECONDS * (2**attempt)
                time.sleep(delay)
                continue
            core.logger.error(f"[{service_name}] gtranslate: {log_prefix}Unexpected error after {MAX_RETRIES_HTTP+1} attempts. Using placeholders.")
            translated_segments_for_this_call_final = [placeholder_str if line.strip() else "" for line in lines_to_translate]
            break
            
    if translated_segments_for_this_call_final is None:
        core.logger.error(f"[{service_name}] gtranslate: {log_prefix}Translation attempt loop completed without setting final segments. Critical logic error. Using placeholders.")
        translated_segments_for_this_call_final = [placeholder_str if line.strip() else "" for line in lines_to_translate]

    # Ensure the returned list has the same number of elements as the input
    if len(translated_segments_for_this_call_final) != len(lines_to_translate):
        core.logger.error(f"[{service_name}] gtranslate: {log_prefix}CRITICAL MISMATCH: Final segment count ({len(translated_segments_for_this_call_final)}) != input count ({len(lines_to_translate)}). Padding/truncating.")
        # This should ideally not happen with the new logic.
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
        'User-Agent': __user_agent,
        'Referer': movie_page_full_url or __subtitlecat_base_url,
        'Content-Type': 'application/x-www-form-urlencoded; charset=UTF-8',
        'X-Requested-With': 'XMLHttpRequest',
    }

    core.logger.debug(f"[{service_name}] Attempting to upload translated subtitle '{name_for_upload}' to {upload_url} for language '{target_sc_lang_code}', source lang '{detected_source_language_code}'. Referer: {headers['Referer']}")

    try:
        response = _SC_SESSION.post(upload_url, data=payload, headers=headers, timeout=30)
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
        'headers': {'User-Agent': __user_agent},
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
                    temp_detail_response = _SC_SESSION.get(movie_page_full_url, timeout=15)
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
                detail_response = _SC_SESSION.get(movie_page_full_url, timeout=15)
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
            try:
                shared_headers = {
                    'User-Agent': __user_agent,
                    'Referer': movie_page_full_url,
                    'Accept': 'application/json, */*'
                }
                core.logger.debug(f"[{service_name}] Attempting to fetch shared translation for '{constructed_filename}' from {shared_translation_url} (referer: {movie_page_full_url})")
                shared_response = _SC_SESSION.get(shared_translation_url, headers=shared_headers, timeout=shared_translation_timeout)

                if shared_response.status_code == 200 and shared_response.headers.get('content-type', '').startswith('application/json'):
                    json_response = shared_response.json()
                    shared_srt_text = json_response.get("text")
                    shared_srt_lang = json_response.get("language")

                    if shared_srt_text and isinstance(shared_srt_text, str) and shared_srt_text.strip():
                        core.logger.debug(f"[{service_name}] Found shared translation for '{constructed_filename}' (lang: {shared_srt_lang or 'N/A'})")

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
                            'service_name': service_name, 'service': display_name_for_service,
                            'lang': kodi_target_lang_full, 'name': f"{movie_title_on_page} ({sc_lang_name_full}) [Shared]",
                            'rating': 0, 'lang_code': kodi_target_lang_2_letter, 'sync': 'false', 'impaired': 'false',
                            'color': item_color_shared,
                            'action_args': action_args_shared
                        })
                        core.logger.debug(f"[{service_name}] Added result for shared translation: '{constructed_filename}'")
                        shared_translation_found_and_used = True
                    else:
                        core.logger.debug(f"[{service_name}] Shared translation response for '{constructed_filename}' was empty or invalid. JSON: {str(json_response)[:200]}")
                elif shared_response.status_code == 200:
                     core.logger.debug(f"[{service_name}] Shared translation for '{constructed_filename}' returned status 200 but non-JSON content-type: {shared_response.headers.get('content-type', '')}. Body: {shared_response.text[:200]}")
                else:
                    core.logger.debug(f"[{service_name}] Failed to fetch shared translation for '{constructed_filename}'. Status: {shared_response.status_code}, Body: {shared_response.text[:200]}")

            except system_requests.exceptions.RequestException as req_exc_shared:
                core.logger.error(f"[{service_name}] RequestException fetching shared translation for '{constructed_filename}': {req_exc_shared}")
            except ValueError as val_err_shared: # Catches JSONDecodeError
                core.logger.error(f"[{service_name}] ValueError (JSON decode) fetching shared translation for '{constructed_filename}': {val_err_shared}")
            except Exception as e_shared:
                core.logger.error(f"[{service_name}] Unexpected error fetching shared translation for '{constructed_filename}': {e_shared}")

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
            cached_url = _TRANSLATED_CACHE.get(cache_key)
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


    def _save_from_subtitlecat_url(path_from_core, url_to_download):
        _timeout = _get_setting(core, "http_timeout", 15)
        resp_for_save = None
        core.logger.debug(f"[{service_name}] _save_from_subtitlecat_url: Downloading from {url_to_download} to {repr(path_from_core)} with timeout {_timeout}s")
        try:
            resp_for_save = _SC_SESSION.get(url_to_download, headers={'User-Agent': __user_agent}, timeout=_timeout, stream=True)
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
        original_srt_text_content = "" # To store original srt text for error reporting

        try:
            core.logger.debug(f"[{service_name}] Downloading original SRT from: {original_srt_url}")
            dl_timeout = _get_setting(core, "http_timeout", 20)
            original_srt_response = _SC_SESSION.get(original_srt_url, timeout=dl_timeout)
            original_srt_response.raise_for_status()
            original_srt_text_content = original_srt_response.text # Assuming UTF-8 from Subtitlecat
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
            source_indices_map_for_api_texts = [] 

            for original_idx, line_content in enumerate(all_logical_lines_original_protected):
                if not logical_line_metadata[original_idx]['is_all_tag_logical_line']:
                    texts_to_translate_for_api.append(line_content)
                    source_indices_map_for_api_texts.append(original_idx)
            
            core.logger.debug(f"[{service_name}] Found {len(texts_to_translate_for_api)} actual text lines requiring translation API calls.")

            all_translated_pure_text_lines_from_google = [] # This will store results from _gtranslate_text_chunk
            all_detected_source_langs_overall = []

            current_api_batch_lines_for_google = []
            current_api_batch_char_count = 0
            
            api_char_limit = GOOGLE_API_Q_PARAM_CHAR_LIMIT
            api_line_limit = MAX_LINES_PER_API_CALL_CONFIG
            batch_delay_setting = _get_setting(core, "subtitlecat_translation_batch_delay", DEFAULT_BATCH_DELAY_SECONDS)

            if not texts_to_translate_for_api:
                 core.logger.debug(f"[{service_name}] No text lines to translate after filtering all-tag lines. Skipping API calls.")
            else:
                for i, protected_text_line_for_google in enumerate(texts_to_translate_for_api):
                    line_char_count = len(protected_text_line_for_google)
                    potential_new_char_count = current_api_batch_char_count + line_char_count + (1 if current_api_batch_lines_for_google else 0)

                    if current_api_batch_lines_for_google and \
                    (potential_new_char_count > api_char_limit or len(current_api_batch_lines_for_google) >= api_line_limit):
                        core.logger.debug(f"[{service_name}] Processing API batch of {len(current_api_batch_lines_for_google)} lines, {current_api_batch_char_count} chars.")
                        
                        translated_segments, detected_lang_from_chunk = _gtranslate_text_chunk(
                            current_api_batch_lines_for_google, target_gtranslate_lang, core, service_name
                        )
                        
                        # _gtranslate_text_chunk should now always return a list of the same length
                        if len(translated_segments) != len(current_api_batch_lines_for_google):
                            core.logger.error(f"[{service_name}] CRITICAL MISMATCH: _gtranslate_text_chunk returned {len(translated_segments)}, expected {len(current_api_batch_lines_for_google)}. This indicates an issue in _gtranslate_text_chunk's padding/error handling.")
                            # Attempt to self-correct length for safety, though _gtranslate_text_chunk should prevent this
                            corrected_segments = [placeholder_str if line.strip() else "" for line in current_api_batch_lines_for_google] # Default to all placeholders
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
                        current_api_batch_lines_for_google, target_gtranslate_lang, core, service_name
                    )

                    if len(translated_segments) != len(current_api_batch_lines_for_google):
                        core.logger.error(f"[{service_name}] CRITICAL MISMATCH (final batch): _gtranslate_text_chunk returned {len(translated_segments)}, expected {len(current_api_batch_lines_for_google)}. This indicates an issue in _gtranslate_text_chunk's padding/error handling.")
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
                        
                        # If the line is a placeholder, don't restore tags or unescape
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
                 core.logger.error(f"[{service_name}] Mismatch: Processed {current_translated_text_idx} translated lines, but API processing yielded {len(all_translated_pure_text_lines_from_google)}. Some translations might be unused or placeholders inserted incorrectly.")

            flat_line_cursor = 0
            for srt_idx_rebuild, srt_item_rebuild in enumerate(parsed_subs):
                num_logical_lines_in_this_srt_item = srt_item_rebuild.content.count('\n') + 1
                end_slice = min(flat_line_cursor + num_logical_lines_in_this_srt_item, len(final_flat_processed_logical_lines))
                new_content_lines_for_srt_item = final_flat_processed_logical_lines[flat_line_cursor : end_slice]
                
                if len(new_content_lines_for_srt_item) != num_logical_lines_in_this_srt_item:
                    core.logger.error(f"[{service_name}] Mismatch during SRT item reconstruction for srt_idx {srt_idx_rebuild}. Expected {num_logical_lines_in_this_srt_item} lines, got {len(new_content_lines_for_srt_item)}. Padding with empty strings.")
                    # Pad with empty strings to maintain structure
                    padding_count = num_logical_lines_in_this_srt_item - len(new_content_lines_for_srt_item)
                    if padding_count > 0:
                        new_content_lines_for_srt_item.extend([""] * padding_count)

                parsed_subs[srt_idx_rebuild].content = "\n".join(new_content_lines_for_srt_item)
                flat_line_cursor += num_logical_lines_in_this_srt_item
            
            if flat_line_cursor != len(final_flat_processed_logical_lines):
                 core.logger.error(f"[{service_name}] Mismatch: Processed {flat_line_cursor} flat lines for SRT reconstruction, but had {len(final_flat_processed_logical_lines)} total. SRT structure might be incorrect.")

            overall_detected_source_lang = "auto"
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
                     core.logger.error(f"[{service_name}] Could not determine target Subtitlecat language code for upload (args['lang_code'] missing). Aborting upload.")
                else:
                    overall_detected_source_lang_for_upload = overall_detected_source_lang
                    if overall_detected_source_lang_for_upload == "auto" or not overall_detected_source_lang_for_upload:
                        core.logger.debug(f"[{service_name}] Original language for upload is '{overall_detected_source_lang_for_upload}'. Defaulting to 'en' for Subtitlecat upload.")
                        overall_detected_source_lang_for_upload = "en" 

                    new_url_from_sc = _upload_translation_to_subtitlecat(
                        core, service_name, final_translated_srt_str,
                        target_sc_lang_code_for_upload, sc_original_filename_stem,      
                        overall_detected_source_lang_for_upload, args.get('detail_url')          
                    )
            else:
                core.logger.debug(f"[{service_name}] Uploading client-translated subtitle is disabled by setting.")

            if new_url_from_sc:
                core.logger.debug(f"[{service_name}] Upload successful. Callback will download from: {new_url_from_sc}")
                cache_key_lang = args.get('lang_code', target_gtranslate_lang).lower()
                _TRANSLATED_CACHE[(args.get('detail_url'), cache_key_lang)] = new_url_from_sc
                core.logger.debug(f"[{service_name}] Stored translated URL in _TRANSLATED_CACHE for key ({args.get('detail_url')}, {cache_key_lang})")
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

    else:
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