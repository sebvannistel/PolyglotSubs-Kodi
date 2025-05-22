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

import re
import time # Retained as it will be used by _wait_for_translated
# import tempfile # Removed as no longer creating temp files in build_download_request
# import os # Not directly used by this provider's logic now

# Imports for _post_download_fix_encoding (html, io) are made locally within that function as per snippet.
# chardet and charset_normalizer are also imported locally within that function.

# No 'log = logger.Logger.get_logger(__name__)' needed; use 'core.logger' directly.

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
    return getattr(core, "settings", {}).get(key, default)
# END OF MODIFICATION

# helper -------------------------------------
def _extract_ajax(link):
    m = re.search(r"'([^']*)',\s*'([^']*)',\s*'([^']*)'", link)
    return m.groups() if m else (None, None, None)

# START OF MODIFICATION: Added _wait_for_translated helper function
def _wait_for_translated(core, detail_url, lang_code, service_name, tries=80, delay=6): # MODIFIED: tries and delay defaults
    # core.logger.debug(f"[{service_name}] Starting polling for lang '{lang_code}' on {detail_url} (tries={tries}, delay={delay}s)") # REMOVED THIS LINE
    for attempt in range(tries):
        if attempt > 0:
             time.sleep(delay)
        try:
            page = _SC_SESSION.get(detail_url, timeout=10) # MODIFIED: use _SC_SESSION and removed explicit headers
            page.raise_for_status()
            soup = BeautifulSoup(page.text, 'html.parser')
            tag = soup.select_one(f'a[href$="-{lang_code}.srt" i]')
            if tag and tag.get('href'):
                found_url = urljoin(__subtitlecat_base_url, tag['href'])
                core.logger.debug(f"[{service_name}] Poll attempt {attempt+1}/{tries}: Found link for '{lang_code}': {found_url}")
                return found_url
            else:
                core.logger.debug(f"[{service_name}] Polling for '{lang_code}' - {attempt+1}/{tries}") # MODIFIED: log message
        except system_requests.exceptions.RequestException as e_req:
            core.logger.debug(f"[{service_name}] Poll attempt {attempt+1}/{tries}: Request error for {detail_url}: {e_req}")
        except Exception as e_parse:
            core.logger.debug(f"[{service_name}] Poll attempt {attempt+1}/{tries}: Error processing detail page {detail_url}: {e_parse}")
    core.logger.debug(f"[{service_name}] Polling finished for lang '{lang_code}' on {detail_url} after {tries} tries. Link not found.")
    return ''
# END OF MODIFICATION: Added _wait_for_translated helper function


# START OF MODIFICATION: Encoding fix helper
def _post_download_fix_encoding(core, service_name, raw_bytes, outfile):
    import html, io

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
                cn_match = _cn_function(raw_bytes).best()
                if cn_match and cn_match.encoding:
                    enc = cn_match.encoding
                    detected_source = f"charset-normalizer (override, chardet conf: {chardet_confidence if chardet_confidence is not None else 'N/A'})"
                    core.logger.debug(f"[{service_name}] Overridden by charset-normalizer: {enc} for {repr(outfile)}")
                else:
                    core.logger.debug(f"[{service_name}] Charset-normalizer did not provide an override. Sticking with chardet's: {enc} for {repr(outfile)}")
        elif _cn_function:
            core.logger.debug(f"[{service_name}] Chardet failed to detect. Using charset-normalizer for {repr(outfile)}.")
            cn_match = _cn_function(raw_bytes).best()
            if cn_match and cn_match.encoding:
                enc = cn_match.encoding
                detected_source = "charset-normalizer (chardet failed)"
            else:
                detected_source = "default (chardet and charset-normalizer failed)"
                core.logger.debug(f"[{service_name}] Charset-normalizer also failed. Using default {enc} for {repr(outfile)}.")
        else:
             detected_source = "default (chardet failed, charset-normalizer unavailable)"
             core.logger.debug(f"[{service_name}] Chardet failed and charset-normalizer unavailable. Using default {enc} for {repr(outfile)}.")
    elif _cn_function:
        core.logger.debug(f"[{service_name}] Chardet not available/used. Using charset-normalizer for {repr(outfile)}.")
        cn_match = _cn_function(raw_bytes).best()
        if cn_match and cn_match.encoding:
            enc = cn_match.encoding
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
    text = html.unescape(text)
    bom = _get_setting(core, 'force_bom', False) # Correctly uses _get_setting
    final_encoding = 'utf-8-sig' if bom else 'utf-8'
    final_bytes_to_write = text.encode(final_encoding)
    with io.open(outfile, 'wb') as fh:
        fh.write(final_bytes_to_write)
    core.logger.debug(f"[{service_name}] Successfully wrote processed subtitle to {repr(outfile)} with encoding {final_encoding}")
# END OF MODIFICATION: Encoding fix helper


# ---------------------------------------------------------------------------
# SEARCH REQUEST BUILDER
# ---------------------------------------------------------------------------
def build_search_requests(core, service_name, meta):
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
        'headers': {'User-Agent': __user_agent}, # Retained for this initial search as per previous logic
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
    results_table_body = soup.select_one('table.table.sub-table tbody')
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
        movie_page_full_url = urljoin(__subtitlecat_base_url, href)
        year_guard_fetched_soup = None
        if meta.year:
            if str(meta.year) not in row.text:
                core.logger.debug(f"[{service_name}] Year '{meta.year}' not in row text for '{movie_title_on_page}'. Attempting fallback: checking detail page title from {movie_page_full_url}.")
                try:
                    # Using _SC_SESSION for consistency, though original used system_requests here
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
                # Using _SC_SESSION for consistency
                detail_response = _SC_SESSION.get(movie_page_full_url, timeout=15)
                detail_response.raise_for_status()
                detail_soup = BeautifulSoup(detail_response.text, 'html.parser')
            except Exception as exc:
                core.logger.error(f"[{service_name}] Detail page fetch/parse failed for {movie_page_full_url}: {exc}")
                continue
        try:
            url_parts     = href.lstrip('/').split('/')
            original_id   = url_parts[-2]
            filename_base = url_parts[-1].replace('.html', '')
        except IndexError as e_url_parse:
            core.logger.error(f"[{service_name}] Could not parse ID/filename from relative URL '{href}': {e_url_parse}")
            continue
        language_entries = detail_soup.select('div.sub-single')
        if not language_entries:
            core.logger.debug(f"[{service_name}] No language entries ('div.sub-single') found on detail page: {movie_page_full_url}")
        for entry_div in language_entries:
            img_tag = entry_div.select_one('img.flag')
            if not img_tag:
                core.logger.debug(f"[{service_name}] No img.flag in language entry. Skipping.")
                continue
            sc_lang_code = img_tag.get('alt')
            if not sc_lang_code:
                core.logger.debug(f"[{service_name}] img.flag found but no alt attribute. Skipping.")
                continue
            lang_name_span = entry_div.select_one('span:nth-of-type(2)')
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
                        core.logger.debug(f"[{service_name}] Error converting lang code '{sc_lang_code}' (name: '{sc_lang_name_full}'): {e_lang_conv}. Using fallbacks: Full='{kodi_target_lang_full}', ISO2='{kodi_target_lang_2_letter}'. (This message will be shown once per problematic code for this provider run)")
                        seen_lang_conv_errors.add(sc_lang_code)
            if (_base_name(kodi_target_lang_full) not in wanted_languages_lower
                    and kodi_target_lang_2_letter not in wanted_iso2):
                continue
            patch_determined_href = None
            patch_kind_is_translate = False
            a_tag = entry_div.select_one('a[href$=".srt"]')
            if a_tag:
                _raw_href = a_tag.get('href')
                if _raw_href: patch_determined_href = _raw_href
                else: a_tag = None
            if patch_determined_href is None:
                btn = entry_div.select_one('button[onclick*="translate_from_server_folder"]')
                if not btn: continue
                _onclick_attr = btn.get('onclick')
                if not _onclick_attr:
                    core.logger.debug(f"[{service_name}] Translate button for '{sc_lang_name_full}' has no onclick. Skipping.")
                    continue
                lng, orig, folder = _extract_ajax(_onclick_attr)
                if not all([lng, orig, folder]):
                    core.logger.debug(f"[{service_name}] Failed to extract AJAX params for '{sc_lang_name_full}' from onclick. Skipping.")
                    continue
                try:
                    core.logger.debug(f"[{service_name}] Triggering server-side translation for '{sc_lang_name_full}' (file: {orig}, folder: {folder}, lang: {lng})")
                    # CRITICAL FIX 1: Use _SC_SESSION for translate.php call
                    _SC_SESSION.get(
                        f"{__subtitlecat_base_url}/translate.php",
                        params={'lng': lng, 'file': orig, 'folder': folder},
                        timeout=5)
                except system_requests.exceptions.Timeout:
                    core.logger.debug(f"[{service_name}] AJAX call for '{sc_lang_name_full}' timed out. Assuming server might process; will attempt poll.")
                except Exception as e_ajax:
                    core.logger.error(f"[{service_name}] AJAX call for '{sc_lang_name_full}' failed: {e_ajax}. Skipping entry.")
                    continue
                patch_kind_is_translate = True
            action_args_url = ""
            action_args_filename = ""
            if patch_determined_href:
                action_args_url = urljoin(__subtitlecat_base_url, patch_determined_href)
                action_args_filename = patch_determined_href.split('/')[-1]
            else:
                action_args_url = ""
                action_args_filename = f"{original_id}-{filename_base}-{sc_lang_code}.srt"
            results.append({
                'service_name': service_name, 'service': display_name_for_service,
                'lang': kodi_target_lang_full, 'name': f"{movie_title_on_page} ({sc_lang_name_full})",
                'rating': 0, 'lang_code': kodi_target_lang_2_letter, 'sync': 'false', 'impaired': 'false',
                'color': 'yellow' if patch_kind_is_translate else 'white',
                'action_args': {
                    'url': action_args_url, 'lang': kodi_target_lang_full, 'filename': action_args_filename,
                    'gzip': False, 'service_name': service_name, 'needs_poll': patch_kind_is_translate,
                    'detail_url': movie_page_full_url, 'lang_code': sc_lang_code}})
            core.logger.debug(f"[{service_name}] Added result '{action_args_filename}' for lang '{kodi_target_lang_full}' (Poll: {patch_kind_is_translate})")
    core.logger.debug(f"[{service_name}] Returning {len(results)} results after parsing all pages.")
    return results

# ---------------------------------------------------------------------------
# DOWNLOAD REQUEST BUILDER
# ---------------------------------------------------------------------------
# START OF MODIFICATION: build_download_request to use save_callback and return standard dict
def build_download_request(core, service_name, args):
    initial_download_url = args.get('url', '')
    _filename_from_args = args.get('filename')
    if _filename_from_args:
        filename_for_log = _filename_from_args
    elif initial_download_url:
        filename_for_log = initial_download_url.split('/')[-1]
    else:
        filename_for_log = args.get('lang_code', "unknown_lang") + "_subtitle_pending_poll"

    core.logger.debug(f"[{service_name}] Initializing download parameters for: {filename_for_log}, initial URL from args: '{initial_download_url}'")
    final_url = initial_download_url # This will be the remote HTTP/HTTPS URL

    if args.get('needs_poll'):
        if not final_url:
            core.logger.debug(f"[{service_name}] Polling required for '{filename_for_log}'. Detail URL: {args.get('detail_url')}, SC Lang Code: {args.get('lang_code')}")
            polled_url = _wait_for_translated(core,
                                              args['detail_url'],
                                              args['lang_code'],
                                              service_name)
            if polled_url:
                final_url = polled_url
                # Update args['url'] in case it's used by the core if save_callback is ignored
                args['url'] = final_url
                core.logger.debug(f"[{service_name}] Polling successful. Found URL for '{filename_for_log}': {final_url}")
            else:
                error_msg = f"[{service_name}] Translation for '{filename_for_log}' (lang: {args.get('lang_code')}) did not become available on {args.get('detail_url')} in time."
                core.logger.error(error_msg)
                raise Exception(error_msg)
        elif final_url:
            core.logger.debug(f"[{service_name}] 'needs_poll' is true but URL already present for '{filename_for_log}'. Using existing URL: {final_url}.")

    if not final_url:
        error_msg = f"[{service_name}] Final URL for '{filename_for_log}' is empty. This indicates an issue (initial URL from args: '{initial_download_url}', needs_poll: {args.get('needs_poll')})."
        core.logger.error(error_msg)
        raise ValueError(error_msg)

    # Define the _save callback. This will be called by a patched core.
    # The `path` argument to _save will be the final output file path provided by the core.
    def _save(path_from_core):
        _timeout = _get_setting(core, "http_timeout", 15)
        # `resp_for_save` is local to this `_save` function.
        resp_for_save = None
        core.logger.debug(f"[{service_name}] _save callback: Downloading from {final_url} to {repr(path_from_core)} with timeout {_timeout}s")
        try:
            # CRITICAL FIX 2: Use _SC_SESSION.get() for final download
            resp_for_save = _SC_SESSION.get(final_url, timeout=_timeout) # Removed headers as _SC_SESSION already has them
            resp_for_save.raise_for_status()
            raw_bytes = resp_for_save.content
            core.logger.debug(f"[{service_name}] _save callback: Download successful, {len(raw_bytes)} bytes received from {final_url}")

            _post_download_fix_encoding(core, service_name, raw_bytes, path_from_core)
            core.logger.debug(f"[{service_name}] _save callback: Processing complete for {repr(path_from_core)}")
            return True # Indicate success of the save_callback
        except system_requests.exceptions.Timeout:
            core.logger.error(f"[{service_name}] _save callback: Timeout during download from {final_url} for {repr(path_from_core)}")
            return False # Indicate failure
        except system_requests.exceptions.RequestException as e_req:
            core.logger.error(f"[{service_name}] _save callback: RequestException during download from {final_url} for {repr(path_from_core)}: {e_req}")
            return False # Indicate failure
        except Exception as e_proc:
            core.logger.error(f"[{service_name}] _save callback: Error during processing for {repr(path_from_core)} (from {final_url}): {e_proc}")
            return False # Indicate failure
        finally:
            if resp_for_save:
                resp_for_save.close() # Ensure the HTTP response is closed for this specific request.

    core.logger.debug(f"[{service_name}] Prepared download request for: {filename_for_log} from {final_url}. Returning standard dict with save_callback.")
    # Return all standard keys for the core, plus the save_callback.
    # If the core is not patched, it will use 'method', 'url', 'headers', 'stream' for its own download.
    # If patched, it should use 'save_callback(outfile_path)' and potentially ignore the other keys for actual download.
    return {
        'method': 'GET',
        'url': final_url, # This is the remote HTTP/HTTPS URL
        'headers': {'User-Agent': __user_agent}, # Retained for compatibility if core doesn't use save_callback
        'stream': True, # Standard practice
        'save_callback': _save
    }
# END OF MODIFICATION

#--- END OF FILE subtitlecat.py ---