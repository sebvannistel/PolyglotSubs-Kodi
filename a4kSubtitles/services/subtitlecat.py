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

import re, time # Retained as it will be used by _wait_for_translated and client-side translation rate limiting
from functools import lru_cache                # ← simple cache
from rapidfuzz import fuzz                    # ← fuzzy title match
# import tempfile # Removed as no longer creating temp files in build_download_request
# import os # Not directly used by this provider's logic now

# Imports for _post_download_fix_encoding (html, io) are made locally within that function as per snippet.
# chardet and charset_normalizer are also imported locally within that function.

# START OF ADDITIONS FOR CLIENT-SIDE TRANSLATION
import srt # For parsing/composing SRT files
import html # For unescaping HTML entities (used in translation preparation)
# urllib.parse.quote_plus is used via urllib.parse.quote_plus
# END OF ADDITIONS FOR CLIENT-SIDE TRANSLATION

# No 'log = logger.Logger.get_logger(__name__)' needed; use 'core.logger' directly.

# light-weight cache (detail_url, lang_code) ➜ final .srt URL
_TRANSLATED_CACHE = {}     # survives for the lifetime of the add-on

#######################################################################
# 1. helper ­- title similarity
#######################################################################
# ≥85 % token_set_ratio ≈ “same movie”, order unimportant
def _is_title_close(wanted: str, got: str) -> bool:
    return fuzz.token_set_ratio(
        (wanted or "").lower(),
        (got or "").lower()
    ) >= 78 # MODIFIED FROM 85 to 78 as per patch

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
    "es-419": ("Spanish", "es"), # Note: 'es-419' is typically a Kodi code. If SubtitleCat uses 'es-419', this map handles it.
                                 # If Kodi sends 'es-419' and we want to map it to 'es' for SubtitleCat,
                                 # this map might be used if 'es-419' is what `kodi_lang.lower()` becomes.
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

# START OF REPLACEMENT: _wait_for_translated replaced with "Take-away code"
def _wait_for_translated(core, detail_url, lang_code, service_name,
                         tries=80, delay=3):
    for attempt in range(tries):
        # START OF PATCH: Add small back-off before the first poll, use existing logic for subsequent
        if attempt == 0:
            time.sleep(1) # Small delay before the very first poll attempt
        elif attempt > 0: # Original logic for subsequent attempts
            time.sleep(min(delay * (2 ** max(0, attempt-30)), 30))
        # END OF PATCH

        try:
            page = _SC_SESSION.get(
                detail_url,
                timeout=10,
                headers={'Cache-Control': 'no-cache'} # Point 2: HTML caching by Cloudflare
            )
            page.raise_for_status()
            soup = BeautifulSoup(page.text, 'html.parser')

            href = None
            variants = [lang_code,
                        core.utils.get_lang_id(lang_code,
                                               core.kodi.xbmc.ENGLISH_NAME),
                        lang_code.split('-')[0]]
            variants = [v.lower() for v in variants if v]

            patterns = [
                rf'-({v}).*?\.srt' for v in variants
            ] + [
                rf'_{v}.*?\.srt' for v in variants
            ] + [
                rf'/{v}/.*?\.srt' for v in variants
            ]

            for pat in patterns:
                tag = soup.find('a', href=re.compile(pat, re.I))
                if tag:
                    href = tag['href']
                    core.logger.debug(f"[{service_name}] Pattern '{pat}' hit: {href}")
                    break

            if not href:
                # last-chance fallback: first *new* .srt link
                # MODIFIED Fallback pattern as per patch
                tag = soup.find('a', href=re.compile(rf'(-|_)({lang_code})(\.|_)', re.I))
                if tag:
                    href = tag['href']
                    core.logger.debug(f"[{service_name}] Fallback link: {href}")

            if href:
                # MODIFIED found_url construction as per patch
                from requests.utils import requote_uri # Added as per patch
                found_url = requote_uri(urljoin(__subtitlecat_base_url, href))
                # Cache key uses lang_code (normalized) as per "Take-away code"
                cache_key = (detail_url, lang_code.lower())
                _TRANSLATED_CACHE[cache_key] = found_url
                return found_url

            core.logger.debug(f"[{service_name}] Polling for '{lang_code}' "
                              f"- {attempt+1}/{tries}")

        except system_requests.exceptions.RequestException as req_exc:
            core.logger.debug(f"[{service_name}] Poll {attempt+1}/{tries} "
                              f"RequestException: {req_exc}")
        except Exception as exc:
            core.logger.debug(f"[{service_name}] Poll {attempt+1}/{tries} "
                              f"failed with unexpected error: {exc}")

    return ''
# END OF REPLACEMENT: _wait_for_translated replaced with "Take-away code"


# START OF MODIFICATION: Encoding fix helper
def _post_download_fix_encoding(core, service_name, raw_bytes, outfile):
    import html, io # html import is here locally

    _cd_module = None
    _cn_function = None
    _use_chardet_logic = False
    try:
        import chardet as _cd_imported
        _cd_module = _cd_imported
        _use_chardet_logic = True
    except ImportError:
        try:
            from charset_normalizer import from_bytes as _cn_imported
            _cn_function = _cn_imported
        except ImportError:
             pass

    enc = 'utf-8'
    detected_source = "default (no detectors available or both failed import)"
    if _use_chardet_logic and _cd_module:
        guess = _cd_module.detect(raw_bytes)
        chardet_confidence = guess.get('confidence') if guess else 0.0
        chardet_enc_value = guess['encoding'] if guess else None
        if chardet_enc_value:
            enc = chardet_enc_value
            confidence_is_good = chardet_confidence is None or chardet_confidence >= 0.5
            detected_source = f"chardet (confidence: {chardet_confidence if chardet_confidence is not None else 'N/A'})"
            core.logger.debug(f"[{service_name}] Initial detection by chardet: {enc} (confidence: {chardet_confidence if chardet_confidence is not None else 'N/A'}) for {repr(outfile)}")
            if not confidence_is_good and _cn_function:
                core.logger.debug(f"[{service_name}] Chardet confidence ({chardet_confidence}) is low. Attempting charset-normalizer override for {repr(outfile)}.")
                cn_match = list(_cn_function(raw_bytes)) # Convert generator to list
                if cn_match and cn_match[0].encoding: # Access best match if list not empty
                    enc = cn_match[0].encoding
                    detected_source = f"charset-normalizer (override, chardet conf: {chardet_confidence if chardet_confidence is not None else 'N/A'})"
                    core.logger.debug(f"[{service_name}] Overridden by charset-normalizer: {enc} for {repr(outfile)}")
                else:
                    core.logger.debug(f"[{service_name}] Charset-normalizer did not provide an override. Sticking with chardet's: {enc} for {repr(outfile)}")
        elif _cn_function:
            core.logger.debug(f"[{service_name}] Chardet failed to detect. Using charset-normalizer for {repr(outfile)}.")
            cn_match = list(_cn_function(raw_bytes)) # Convert generator to list
            if cn_match and cn_match[0].encoding: # Access best match if list not empty
                enc = cn_match[0].encoding
                detected_source = "charset-normalizer (chardet failed)"
            else:
                detected_source = "default (chardet and charset-normalizer failed)"
                core.logger.debug(f"[{service_name}] Charset-normalizer also failed. Using default {enc} for {repr(outfile)}.")
        else:
             detected_source = "default (chardet failed, charset-normalizer unavailable)"
             core.logger.debug(f"[{service_name}] Chardet failed and charset-normalizer unavailable. Using default {enc} for {repr(outfile)}.")
    elif _cn_function:
        core.logger.debug(f"[{service_name}] Chardet not available/used. Using charset-normalizer for {repr(outfile)}.")
        cn_match = list(_cn_function(raw_bytes)) # Convert generator to list
        if cn_match and cn_match[0].encoding: # Access best match if list not empty
            enc = cn_match[0].encoding
            detected_source = "charset-normalizer (primary)"
        else:
            detected_source = "default (charset-normalizer failed)"
            core.logger.debug(f"[{service_name}] Charset-normalizer (primary) failed. Using default {enc} for {repr(outfile)}.")
    else:
        core.logger.debug(f"[{service_name}] Neither chardet nor charset-normalizer was usable. Defaulting to {enc} for {repr(outfile)}. Subtitles might be garbled.")

    core.logger.debug(f"[{service_name}] Final encoding for decoding: '{enc}' (Source: {detected_source}) for {repr(outfile)}")
    if enc is None:
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

def _gtranslate_text_chunk(text_chunk, target_lang, core, service_name):
    if not text_chunk.strip():
        core.logger.debug(f"[{service_name}] gtranslate: Empty chunk provided, skipping translation.")
        return ""

    payload = {
        'client': 'gtx',
        'sl': 'auto',
        'tl': target_lang,
        'dt': 't',
        'q': text_chunk
    }
    # Log part of the text_chunk for debugging, not the full URL as it's now a POST
    # MODIFICATION 2.5: Truncate log preview further
    core.logger.debug(f"[{service_name}] gtranslate: Translating chunk to '{target_lang}'. Chunk preview: {text_chunk[:60]}...")

    try:
        r = _SC_SESSION.post(GOOGLE_TRANSLATE_URL, data=payload, timeout=20)
        r.raise_for_status() 

        response_json = r.json()

        if not response_json or not isinstance(response_json, list) or not response_json[0]:
            core.logger.error(f"[{service_name}] gtranslate: Unexpected JSON response structure from Google Translate: {str(response_json)[:200]}")
            return ""

        translated_parts = []
        for part_list in response_json[0]:
            if part_list and isinstance(part_list, list) and part_list[0] is not None:
                translated_parts.append(part_list[0])
        
        return "".join(translated_parts)

    except system_requests.exceptions.Timeout:
        core.logger.error(f"[{service_name}] gtranslate: Timeout during translation request to {GOOGLE_TRANSLATE_URL}.")
        return ""
    except system_requests.exceptions.RequestException as e:
        core.logger.error(f"[{service_name}] gtranslate: RequestException: {e} for URL {GOOGLE_TRANSLATE_URL}.")
        return ""
    except ValueError as e_json: 
        core.logger.error(f"[{service_name}] gtranslate: JSONDecodeError: {e_json}. Response text: {r.text[:200] if 'r' in locals() else 'N/A'}")
        return ""
    except Exception as e_unexp:
        core.logger.error(f"[{service_name}] gtranslate: Unexpected error: {e_unexp} for URL {GOOGLE_TRANSLATE_URL}.")
        return ""
# END OF DEFINITIONS FOR CLIENT-SIDE TRANSLATION

# START OF IMAGE FIX #3: Helpers for tag protection (module-level)
# MODIFICATION 2.2: Placeholder constants
_PLACEHOLDER_SENTINEL_PREFIX = "\u2063@@SCPTAG" # INVISIBLE SEPARATOR + prefix
_PLACEHOLDER_SUFFIX = "SCP@@"
# MODIFIED REGEX for improved tag attribute handling
__TAG_REGEX_FOR_PROTECTION = re.compile(r"(<(?:"[^"]*"|'[^']*'|[^>"'])*>|{(?:"[^"]*"|'[^']*'|[^}"'])*})")

def _protect_subtitle_tags(text_line):
    """Replaces tags with placeholders and returns the new text and the list of tags.
    MODIFICATION 2.3: Handles all-tag lines."""
    # Check if the line is effectively all tags after stripping non-tag content
    stripped_line_no_tags = __TAG_REGEX_FOR_PROTECTION.sub('', text_line).strip()
    if not stripped_line_no_tags: # If empty after removing tags and stripping
        # This is an all-tag line. Return it as is, with no placeholders/tags to restore.
        return text_line, [] # Return original line, and empty list of tags
    
    tags_found = []
    def _replacer(match):
        tag = match.group(1)
        tags_found.append(tag)
        # MODIFICATION 2.2: Using new placeholder format
        return f"{_PLACEHOLDER_SENTINEL_PREFIX}{len(tags_found)-1}{_PLACEHOLDER_SUFFIX}"
    
    processed_text = __TAG_REGEX_FOR_PROTECTION.sub(_replacer, text_line)
    return processed_text, tags_found

def _restore_subtitle_tags(text_line_with_placeholders, tags_list):
    """Replaces placeholders in the text with their original tag strings."""
    for i in range(len(tags_list) - 1, -1, -1):
        original_tag_content = tags_list[i]
        # MODIFICATION 2.2: Using new placeholder format
        placeholder = f"{_PLACEHOLDER_SENTINEL_PREFIX}{i}{_PLACEHOLDER_SUFFIX}"
        text_line_with_placeholders = text_line_with_placeholders.replace(placeholder, original_tag_content)
    return text_line_with_placeholders
# END OF IMAGE FIX #3: Helpers


# ---------------------------------------------------------------------------
# SEARCH REQUEST BUILDER
# ---------------------------------------------------------------------------
def build_search_requests(core, service_name, meta):
    # --- Start of Fix 3 application ---
    if meta.languages:
        normalized_kodi_langs = []
        for kodi_lang in meta.languages:
            sc_lang = __kodi_regional_lang_map.get(kodi_lang.lower(), (None, kodi_lang))[1]
            normalized_kodi_langs.append(sc_lang)
        meta.languages = normalized_kodi_langs
        core.logger.debug(f"[{service_name}] Normalized meta.languages for search: {meta.languages}")
    # --- End of Fix 3 application ---

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

    # Define shared translation URL
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

            # Attempt to fetch shared translation first
            shared_translation_found_and_used = False
            try:
                shared_headers = {
                    'User-Agent': __user_agent,
                    'Referer': movie_page_full_url, 
                    'Accept': 'application/json, */*' 
                }
                core.logger.debug(f"[{service_name}] Attempting to fetch shared translation for '{constructed_filename}' from {shared_translation_url} (referer: {movie_page_full_url})")
                # Using _SC_SESSION for consistency, as it holds the user-agent and any potential session cookies.
                shared_response = _SC_SESSION.get(shared_translation_url, headers=shared_headers, timeout=shared_translation_timeout)
                
                if shared_response.status_code == 200 and shared_response.headers.get('content-type', '').startswith('application/json'):
                    json_response = shared_response.json()
                    shared_srt_text = json_response.get("text")
                    shared_srt_lang = json_response.get("language") # Optional for logging

                    if shared_srt_text and isinstance(shared_srt_text, str) and shared_srt_text.strip():
                        core.logger.debug(f"[{service_name}] Found shared translation for '{constructed_filename}' (lang: {shared_srt_lang or 'N/A'})")
                        
                        action_args_shared = {
                            'method_type': 'SHARED_TRANSLATION_CONTENT', # New type
                            'srt_content': shared_srt_text,
                            'filename': constructed_filename,
                            'lang': kodi_target_lang_full,
                            'service_name': service_name,
                            'detail_url': movie_page_full_url, # For reference
                            'lang_code': sc_lang_code, # Original SC lang code
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
            except ValueError as val_err_shared: # For JSON decoding errors
                core.logger.error(f"[{service_name}] ValueError (JSON decode) fetching shared translation for '{constructed_filename}': {val_err_shared}")
            except Exception as e_shared:
                core.logger.error(f"[{service_name}] Unexpected error fetching shared translation for '{constructed_filename}': {e_shared}")

            if shared_translation_found_and_used:
                continue 

            # If shared translation not found or failed, proceed with existing logic
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
                core.logger.debug(f"[{service_name}] Using cached translated URL: {cached_url} for {sc_lang_name_full} on {movie_page_full_url}")

            if patch_determined_href: 
                action_args['url'] = urljoin(__subtitlecat_base_url, patch_determined_href)
            else:
                btn = entry_div.select_one('button.yellow-link[onclick*="translate_from_server_folder"]')
                if not btn: # Fallback if the class changes or is missing
                    btn = entry_div.select_one('button[onclick*="translate_from_server_folder"]')
                if btn:
                    _onclick_attr = btn.get('onclick')
                    if not _onclick_attr:
                        core.logger.debug(f"[{service_name}] Translate button for '{sc_lang_name_full}' has no onclick. Skipping.")
                        continue
                    
                    # Parameters derived from already extracted page data
                    # original_id_from_href and filename_base_from_href are from the main movie page URL.
                    # sc_lang_code is from the alt attribute of the flag image for this language entry.
                    target_translation_lang = sc_lang_code # This is what was passed as the first param to translate_from_server_folder

                    derived_folder_path = "/subs/%s/" % original_id_from_href
                    derived_orig_filename_stem = filename_base_from_href + "-orig" # Matches the typical pattern for source files
                    
                    # Construct the source URL for the original subtitle file
                    source_srt_filename = derived_orig_filename_stem + '.srt'
                    source_srt_url = urljoin(__subtitlecat_base_url, derived_folder_path + source_srt_filename)
                    
                    core.logger.debug(f"[{service_name}] Derived for client translation: target_lang='{target_translation_lang}', source_url='{source_srt_url}'")

                    action_args.update({
                        'needs_client_side_translation': True,
                        'original_srt_url': source_srt_url,
                        'target_translation_lang': target_translation_lang, 
                        'needs_poll': False, 
                        'url': '', 
                        # 'lang_code': sc_lang_code, # Already in action_args
                        # 'filename': constructed_filename, # Already in action_args
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
    original_sc_lang_code = args.get('lang_code', '') 
    sc_lang_for_polling = original_sc_lang_code 

    if original_sc_lang_code:
        sc_lang_for_polling = __kodi_regional_lang_map.get(
            original_sc_lang_code.lower(), (None, original_sc_lang_code)
        )[1]
        if sc_lang_for_polling != original_sc_lang_code:
            core.logger.debug(f"[{service_name}] Normalized SubtitleCat lang_code '{original_sc_lang_code}' to '{sc_lang_for_polling}' for polling (if applicable).")

    _filename_from_args = args.get('filename', 'unknown_subtitle.srt')
    core.logger.debug(f"[{service_name}] Building download request for: {_filename_from_args}, Args: {args}")

    if args.get('needs_client_side_translation'):
        # MODIFICATION: core.logger.info -> core.logger.debug
        core.logger.debug(f"[{service_name}] Starting client-side translation for '{_filename_from_args}'")
        original_srt_url = args['original_srt_url']
        target_gtranslate_lang = args['target_translation_lang'] 
        
        try:
            core.logger.debug(f"[{service_name}] Downloading original SRT from: {original_srt_url}")
            dl_timeout = _get_setting(core, "http_timeout", 20) 
            original_srt_response = _SC_SESSION.get(original_srt_url, timeout=dl_timeout)
            original_srt_response.raise_for_status()
            original_srt_text = original_srt_response.text
            core.logger.debug(f"[{service_name}] Downloaded original SRT content ({len(original_srt_text)} chars).")

            parsed_subs = list(srt.parse(original_srt_text))
            core.logger.debug(f"[{service_name}] Parsed {len(parsed_subs)} subtitle items from original SRT.")

            # MODIFICATION 2.3: Prepare translatable_items_info, skipping all-tag lines
            # MODIFICATION: Changed order of html.unescape and _protect_subtitle_tags
            translatable_items_info = []
            for sub_item_idx, sub_item in enumerate(parsed_subs):
                # 1. Prepare line for tag protection (newlines to spaces)
                line_for_tag_protection = sub_item.content.replace('\n', ' ')
                
                # 2. Protect tags
                protected_text_with_placeholders, tags_map_for_item = _protect_subtitle_tags(line_for_tag_protection)
                
                # Check if it was an all-tag line
                # (original line_for_tag_protection returned, and tags_map_for_item is empty)
                if not tags_map_for_item and protected_text_with_placeholders == line_for_tag_protection:
                    # All-tag line, content preserved in parsed_subs[sub_item_idx].content
                    # It's not added to translatable_items_info, so not part of chunks.
                    pass
                else:
                    # This item needs translation
                    translatable_items_info.append({
                        'original_idx': sub_item_idx, 
                        'map': tags_map_for_item,
                        # 3. Use protected_text_with_placeholders for chunks
                        'protected_text': protected_text_with_placeholders 
                    })
            
            core.logger.debug(f"[{service_name}] Identified {len(translatable_items_info)} translatable subtitle items (excluding all-tag lines).")

            chunks = []
            # MODIFICATION 2.1: Chunk size adjusted
            block_size_chars = 1500
            original_segments_for_chunks_count = [] # Stores count of original segments from translatable_items_info per chunk
            
            current_chunk_buffer = ""
            current_chunk_segment_count = 0
            
            # Build chunks using protected_text from translatable_items_info
            for item_data in translatable_items_info: # Iterate over translatable items only
                segment_text_for_chunk = item_data['protected_text']
                # Check URL encoding length if concerned, for now simple length check
                if len(current_chunk_buffer) + len(segment_text_for_chunk) + 1 > block_size_chars and current_chunk_buffer:
                    chunks.append(current_chunk_buffer)
                    original_segments_for_chunks_count.append(current_chunk_segment_count)
                    current_chunk_buffer = ""
                    current_chunk_segment_count = 0
                current_chunk_buffer += segment_text_for_chunk + "␟" # Use a rare separator
                current_chunk_segment_count += 1

            if current_chunk_buffer: 
                chunks.append(current_chunk_buffer)
                original_segments_for_chunks_count.append(current_chunk_segment_count)

            core.logger.debug(f"[{service_name}] Split translatable items into {len(chunks)} chunks for translation.")
            
            current_TII_pointer = 0 # Pointer into translatable_items_info (conceptual `translated_srt_item_pointer`)
            
            for i, text_chunk_to_translate in enumerate(chunks): # i is chunk index
                core.logger.debug(f"[{service_name}] Translating chunk {i+1}/{len(chunks)}...")
                # MODIFICATION 2.1: Rate limit between chunk posts
                if i > 0: # No sleep before the first chunk request
                    time.sleep(0.4)
                
                translated_chunk_content = _gtranslate_text_chunk(text_chunk_to_translate, target_gtranslate_lang, core, service_name)
                
                translated_segments_in_chunk = translated_chunk_content.split("␟")
                if translated_segments_in_chunk and translated_segments_in_chunk[-1] == "": # Remove potential trailing empty segment
                    translated_segments_in_chunk = translated_segments_in_chunk[:-1]

                # This is the number of original segments from translatable_items_info that formed this chunk
                num_original_segments_this_chunk = original_segments_for_chunks_count[i] 
                
                # MODIFICATION: core.logger.warning -> core.logger.debug
                if len(translated_segments_in_chunk) != num_original_segments_this_chunk:
                    core.logger.debug(f"[{service_name}] Mismatch in segment count for translated chunk {i+1}. Expected {num_original_segments_this_chunk} original segments for this chunk, got {len(translated_segments_in_chunk)} translated segments. Translation quality may be affected.")

                # Iterate over each segment returned by Google for this chunk
                # k_zip is the index within the current translated_segments_in_chunk
                for k_zip, translated_segment_text_raw in enumerate(translated_segments_in_chunk):
                    # target_TII_idx is the effective destination slot in translatable_items_info
                    # based on Fix #4's pointer logic (current_TII_pointer + k_zip)
                    target_TII_idx = current_TII_pointer + k_zip 

                    if target_TII_idx < len(translatable_items_info):
                        # Normal case: This translated segment maps to a designated translatable item
                        info_for_this_segment = translatable_items_info[target_TII_idx]
                        original_sub_idx_to_update = info_for_this_segment['original_idx']
                        tags_to_restore = info_for_this_segment['map']
                        
                        # 5. Restore tags
                        text_with_restored_tags = _restore_subtitle_tags(translated_segment_text_raw, tags_to_restore)
                        # 6. Unescape HTML entities
                        final_content_for_srt = html.unescape(text_with_restored_tags)
                        # 7. Set final content
                        parsed_subs[original_sub_idx_to_update].content = final_content_for_srt
                    else:
                        # MODIFICATION 2.4: Overshoot - More translated segments than available translatable_items_info slots overall
                        if len(translatable_items_info) > 0:
                            # Append to the content of the *very last item in translatable_items_info*
                            last_TII_item_info = translatable_items_info[-1]
                            final_cue_original_idx = last_TII_item_info['original_idx']
                            # Use the map of this last item for restoring tags of the overshot segment
                            map_for_overshoot_segment = last_TII_item_info['map']
                            
                            # Apply same post-translation processing for overshot segments
                            text_with_restored_tags_overshoot = _restore_subtitle_tags(translated_segment_text_raw, map_for_overshoot_segment)
                            final_content_for_srt_overshoot = html.unescape(text_with_restored_tags_overshoot)
                            
                            parsed_subs[final_cue_original_idx].content += " " + final_content_for_srt_overshoot # Append with a space
                            core.logger.debug(f"[{service_name}] Overshoot (2.4): Appended segment to content of original sub idx {final_cue_original_idx}.")
                        else:
                            # This case (overshoot with no translatable items) should be rare.
                            # MODIFICATION: core.logger.warning -> core.logger.debug
                            core.logger.debug(f"[{service_name}] Overshoot (2.4): No translatable items to append to. Discarding segment: {translated_segment_text_raw[:60]}")
                
                # Advance current_TII_pointer by the number of segments Google returned for *this* chunk (Fix #4 behavior)
                current_TII_pointer += len(translated_segments_in_chunk) 
                
                if current_TII_pointer >= len(translatable_items_info) and len(translatable_items_info) > 0 : # Check if all translatable items have been 'pointed to'
                    if i < len(chunks) -1 : # If there were more chunks but we've notionally processed all translatable item slots
                         # MODIFICATION: core.logger.warning -> core.logger.debug
                         core.logger.debug(f"[{service_name}] All translatable item slots considered; subsequent chunks (if any) will primarily cause overshoot appends to the final cue.")
                    # Continue processing remaining chunks, as they might still contain segments that need to be appended due to overshoot
                    # The original break was: break # Break from the outer loop over chunks
                    # Keeping the break, as Fix #4 original code also had a similar break condition logic.
                    # This means if pointer exceeds items, remaining *chunks* are skipped. Overshoot for *current* chunk is handled above.
                    break 
            
            # Final logging for pointer state relative to translatable items
            if len(chunks) > 0: # Only if translation attempt was made
                if current_TII_pointer < len(translatable_items_info):
                     # MODIFICATION: core.logger.warning -> core.logger.debug
                     core.logger.debug(f"[{service_name}] Final TII pointer ({current_TII_pointer}) is less than total translatable items ({len(translatable_items_info)}). Some items might not have received translations if Google returned fewer segments than expected overall.")
                elif current_TII_pointer > len(translatable_items_info) and len(translatable_items_info) > 0:
                     # MODIFICATION: core.logger.info -> core.logger.debug
                     core.logger.debug(f"[{service_name}] Final TII pointer ({current_TII_pointer}) overshot total translatable items ({len(translatable_items_info)}). Overshoot logic (2.4) should have appended to the last item.")


            final_translated_srt_str = srt.compose(parsed_subs)
            core.logger.debug(f"[{service_name}] Successfully composed translated SRT string ({len(final_translated_srt_str)} chars).")

            def _save_client_translated_srt(path_from_core):
                try:
                    import io 
                    bom = _get_setting(core, 'force_bom', False)
                    final_encoding = 'utf-8-sig' if bom else 'utf-8'
                    with io.open(path_from_core, 'w', encoding=final_encoding) as f:
                        f.write(final_translated_srt_str)
                    # MODIFICATION: core.logger.info -> core.logger.debug
                    core.logger.debug(f"[{service_name}] Client-translated SRT saved to '{path_from_core}' with encoding '{final_encoding}'.")
                    return True
                except Exception as e_save:
                    core.logger.error(f"[{service_name}] Failed to save client-translated SRT to '{path_from_core}': {e_save}")
                    return False
            
            # MODIFICATION 2.6: This path already bypasses _post_download_fix_encoding. No change needed here for 2.6.
            return {
                'method': 'CLIENT_SIDE_TRANSLATED',
                'url': original_srt_url, # For reference
                'save_callback': _save_client_translated_srt,
                'filename': _filename_from_args,
            }
        except system_requests.exceptions.RequestException as e_req: 
            core.logger.error(f"[{service_name}] Client-side translation: Network error downloading original SRT {original_srt_url}: {e_req}")
            raise 
        except srt.SRTParseError as e_srt: 
            core.logger.error(f"[{service_name}] Client-side translation: SRT parsing error for {original_srt_url}: {e_srt}")
            raise
        except Exception as e_pipeline: 
            core.logger.error(f"[{service_name}] Client-side translation pipeline failed for '{_filename_from_args}': {e_pipeline}")
            raise 
    
    elif args.get('method_type') == 'SHARED_TRANSLATION_CONTENT':
        core.logger.debug(f"[{service_name}] Using shared translation content for '{args.get('filename')}'")
        srt_content_to_save = args.get('srt_content', '') 

        def _save_shared_srt(path_from_core):
            try:
                import io, html 
                
                current_srt_text_str = ""
                if isinstance(srt_content_to_save, bytes):
                    core.logger.debug(f"[{service_name}] Shared SRT content was bytes, decoding as UTF-8.")
                    current_srt_text_str = srt_content_to_save.decode('utf-8', errors='replace')
                else:
                    current_srt_text_str = str(srt_content_to_save)
                
                temp_unscaped_srt_text = html.unescape(current_srt_text_str)
                temp_bytes_for_fixing = temp_unscaped_srt_text.encode('utf-8') 

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

    # Standard download logic (direct URL or needs_poll)
    else: 
        core.logger.debug(f"[{service_name}] Proceeding with standard download/polling for '{_filename_from_args}'.")
        initial_download_url = args.get('url', '')
        final_url = initial_download_url
        if args.get('needs_poll'):
        if not final_url: 
            core.logger.debug(f"[{service_name}] Polling required for '{_filename_from_args}'. Detail URL: {args.get('detail_url')}, Polling Lang Code: {sc_lang_for_polling}")
            polled_url = _wait_for_translated(core,
                                              args['detail_url'],
                                              sc_lang_for_polling, 
                                              service_name)
            if polled_url:
                final_url = polled_url
                args['url'] = final_url 
                core.logger.debug(f"[{service_name}] Polling successful. Found URL for '{_filename_from_args}': {final_url}")
            else:
                error_msg = f"[{service_name}] Translation poll for '{_filename_from_args}' (lang for poll: {sc_lang_for_polling}) did not become available on {args.get('detail_url')} in time."
                core.logger.error(error_msg)
                raise Exception(error_msg) 
        elif final_url:
            core.logger.debug(f"[{service_name}] 'needs_poll' is true but URL '{final_url}' already present for '{_filename_from_args}'. Using existing URL without polling.")

    if not final_url:
        error_msg = f"[{service_name}] Final URL for '{_filename_from_args}' is empty after processing. (Initial URL: '{initial_download_url}', NeedsPoll: {args.get('needs_poll')}). Cannot download."
        core.logger.error(error_msg)
        raise ValueError(error_msg)

    def _save_from_subtitlecat_url(path_from_core):
        _timeout = _get_setting(core, "http_timeout", 15)
        resp_for_save = None
        core.logger.debug(f"[{service_name}] _save_from_subtitlecat_url: Downloading from {final_url} to {repr(path_from_core)} with timeout {_timeout}s")
        try:
            resp_for_save = _SC_SESSION.get(final_url, timeout=_timeout)
            resp_for_save.raise_for_status()
            raw_bytes = resp_for_save.content
            core.logger.debug(f"[{service_name}] _save_from_subtitlecat_url: Download successful, {len(raw_bytes)} bytes received.")

            _post_download_fix_encoding(core, service_name, raw_bytes, path_from_core) 
            core.logger.debug(f"[{service_name}] _save_from_subtitlecat_url: Processing complete for {repr(path_from_core)}")
            return True
        except system_requests.exceptions.Timeout:
            core.logger.error(f"[{service_name}] _save_from_subtitlecat_url: Timeout during download from {final_url} for {repr(path_from_core)}")
            return False
        except system_requests.exceptions.RequestException as e_req:
            core.logger.error(f"[{service_name}] _save_from_subtitlecat_url: RequestException for {final_url}: {e_req}")
            return False
        except Exception as e_proc:
            core.logger.error(f"[{service_name}] _save_from_subtitle_url: Error processing {final_url}: {e_proc}")
            return False
        finally:
            if resp_for_save:
                resp_for_save.close()

    core.logger.debug(f"[{service_name}] Prepared direct download request for '{_filename_from_args}' from {final_url}.")
    return {
        'method': 'GET', 
        'url': final_url,
        'headers': {'User-Agent': __user_agent}, 
        'stream': True, 
        'save_callback': _save_from_subtitlecat_url,
        'filename': _filename_from_args, 
    }
# END OF MODIFICATION

#--- END OF FILE subtitlecat.py ---