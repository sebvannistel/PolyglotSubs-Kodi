import html
import re
import sys
import time
import urllib.parse
from collections import Counter
from urllib.parse import urljoin

import requests as system_requests
import srt
from bs4 import BeautifulSoup

from . import headless_bridge
from .translation import (
    _AIOHTTP_AVAILABLE,
    _CHUNK_SEP,
    _CLEAN_CTRL_TRANSLATION_TABLE,
    _CLIENT_TRANSLATED_CONTENT_CACHE,
    _TRANSLATED_CACHE,
    DEFAULT_BATCH_DELAY_SECONDS,
    DEFAULT_TRANSLATION_FAILED_PLACEHOLDER,
    GOOGLE_API_Q_PARAM_CHAR_LIMIT,
    MAX_LINES_PER_API_CALL_CONFIG,
    _gtranslate_text_chunk,
    _protect_subtitle_tags,
    _restore_subtitle_tags,
    _upload_translation_to_subtitlecat,
    asyncio,
)
from .utils import (
    KODI_REGIONAL_LANG_MAP,
    SC_BASE_URL,
    SC_USER_AGENT,
    _get_session,
    _get_setting,
    _is_title_close,
    _post_download_fix_encoding,
)


def build_search_requests(core, service_name, meta):
    """
    Builds the search requests for the subtitlecat service.

    Args:
        core (module): The core module.
        service_name (str): The name of the service.
        meta (dict): The metadata of the video.

    Returns:
        list: A list of search requests.
    """
    if not _AIOHTTP_AVAILABLE and _get_setting(
        core, "debug", False
    ):  # Log aiohttp fallback if debug is on
        core.logger.debug(
            f"[{service_name}] aiohttp library not available. Async translation features will use synchronous fallbacks."
        )

    if meta.languages:
        normalized_kodi_langs = []
        for kodi_lang in meta.languages:
            sc_lang = KODI_REGIONAL_LANG_MAP.get(
                kodi_lang.lower(), (None, kodi_lang)
            )[1]
            normalized_kodi_langs.append(sc_lang)
        meta.languages = normalized_kodi_langs
        core.logger.debug(
            f"[{service_name}] Normalized meta.languages for search: {meta.languages}"
        )

    core.logger.debug(f"[{service_name}] Building search requests for: {meta}")
    query_title = meta.tvshow if meta.is_tvshow else meta.title
    if not query_title:
        core.logger.debug(
            f"[{service_name}] No title found in meta. Aborting search for this provider."
        )
        return []
    search_query_parts = [query_title]
    if meta.year:
        search_query_parts.append(str(meta.year))
    search_term = " ".join(search_query_parts)
    encoded_query = urllib.parse.quote_plus(search_term)
    search_url = f"{SC_BASE_URL}/index.php?search={encoded_query}&d=1"
    core.logger.debug(f"[{service_name}] Search URL: {search_url}")
    return [
        {
            "method": "GET",
            "url": search_url,
            "headers": {
                "User-Agent": SC_USER_AGENT
            },  # Note: This search request is not made with _get_session() by this provider directly, it's passed to the core.
        }
    ]


# ---------------------------------------------------------------------------
# SEARCH RESPONSE PARSER
# ---------------------------------------------------------------------------
def parse_search_response(core, service_name, meta, response):
    """
    Parses the search response from the subtitlecat service.

    Args:
        core (module): The core module.
        service_name (str): The name of the service.
        meta (dict): The metadata of the video.
        response (requests.Response): The response from the service.

    Returns:
        list: A list of subtitle results.
    """
    core.logger.debug(
        f"[{service_name}] Parsing search response. Status: {response.status_code}, URL: {response.url if response else 'N/A'}"
    )
    results = []
    if response.status_code != 200:
        core.logger.error(
            f"[{service_name}] Search request failed (status {response.status_code}) – {response.url}"
        )
        return results
    try:
        soup = BeautifulSoup(response.text, "html.parser")
    except Exception as exc:
        core.logger.error(
            f"[{service_name}] BeautifulSoup error for search response: {exc}"
        )
        return results
    display_name_for_service = getattr(
        core.services.get(service_name), "display_name", service_name
    )
    results_table_body = soup.select_one("div.subtitles table tbody")
    if not results_table_body:
        results_table_body = soup.find("tbody")
        if not results_table_body:
            core.logger.debug(
                f"[{service_name}] A.1: Main results table body not found on {response.url}"
            )
            return results
    rows = results_table_body.find_all("tr")
    core.logger.debug(
        f"[{service_name}] Found {len(rows)} potential movie rows on search page: {response.url}"
    )

    wanted_languages_lower = {lang.lower() for lang in meta.languages}
    wanted_iso2 = {
        core.utils.get_lang_id(language, core.kodi.xbmc.ISO_639_1).lower()
        for language in meta.languages
        if core.utils.get_lang_id(language, core.kodi.xbmc.ISO_639_1)
    }

    def _base_name(name: str) -> str:
        return re.split(r"[ (]", name, 1)[0].lower()

    seen_lang_conv_errors = set()

    shared_translation_url = "https://www.subtitlecat.com/get_shared_translation.php"
    shared_translation_timeout = _get_setting(core, "http_timeout", 10)

    for row in rows:
        link_tag = row.select_one("td:first-child > a")
        if not link_tag:
            core.logger.debug(f"[{service_name}] No link tag in a row. Skipping.")
            continue
        href = link_tag.get("href", "")
        if not (href.lstrip("/").startswith("subs/") and href.endswith(".html")):
            core.logger.debug(
                f"[{service_name}] Link href '{href}' doesn't match expected pattern. Skipping."
            )
            continue
        movie_title_on_page = link_tag.get_text(strip=True) or "Unknown Title"

        if not _is_title_close(meta.title, movie_title_on_page):
            core.logger.debug(
                f"[{service_name}] Title '{movie_title_on_page}' (from search result row) not close enough to wanted title '{meta.title}'. Skipping this row."
            )
            continue

        movie_page_full_url = urljoin(SC_BASE_URL, href)
        year_guard_fetched_soup = None
        if meta.year:
            if (
                meta.year
                and str(int(meta.year) - 1) not in row.text
                and str(meta.year) not in row.text
            ):
                core.logger.debug(
                    f"[{service_name}] Year '{meta.year}' (or '{int(meta.year) - 1}') not in row text for "
                    f"'{movie_title_on_page}'. Attempting fallback: checking detail page title from "
                    f"{movie_page_full_url}."
                )
                try:
                    # MODIFICATION: Use thread-local session and remove lock
                    # with _SC_SESSION_LOCK: # ADDED LOCK
                    temp_detail_response = _get_session().get(
                        movie_page_full_url, timeout=15
                    )
                    temp_detail_response.raise_for_status()
                    temp_detail_soup_for_year_check = BeautifulSoup(
                        temp_detail_response.text, "html.parser"
                    )
                    title_tag_element = temp_detail_soup_for_year_check.find("title")
                    detail_page_title_text = (
                        title_tag_element.get_text(strip=True)
                        if title_tag_element
                        else ""
                    )
                    if str(meta.year) not in detail_page_title_text:
                        core.logger.debug(
                            f"[{service_name}] Year '{meta.year}' also not in detail page title "
                            f"('{detail_page_title_text}'). Skipping row for '{movie_title_on_page}'."
                        )
                        continue
                    else:
                        core.logger.debug(
                            f"[{service_name}] Year '{meta.year}' found in detail page title for "
                            f"'{movie_title_on_page}'. Proceeding with this row."
                        )
                        year_guard_fetched_soup = temp_detail_soup_for_year_check
                except system_requests.exceptions.RequestException as e_req_fallback:
                    core.logger.debug(
                        f"[{service_name}] Fallback year check: Request error for {movie_page_full_url}: {e_req_fallback}. Skipping row for '{movie_title_on_page}'."
                    )
                    continue
                except Exception as e_parse_fallback:
                    core.logger.debug(
                        f"[{service_name}] Fallback year check: Error processing detail page "
                        f"{movie_page_full_url} for title: {e_parse_fallback}. "
                        f"Skipping row for '{movie_title_on_page}'."
                    )
                    continue
        if (
            meta.is_tvshow
            and hasattr(meta, "episode")
            and meta.episode is not None
            and hasattr(meta, "season")
            and meta.season is not None
            and f"S{meta.season:02d}E{meta.episode:02d}" not in row.text
        ):
            continue
        core.logger.debug(
            f"[{service_name}] Processing movie link: '{movie_title_on_page}' -> {movie_page_full_url}"
        )
        detail_soup = None
        if year_guard_fetched_soup:
            core.logger.debug(
                f"[{service_name}] Reusing detail page soup for {movie_page_full_url} (obtained during year guard fallback)."
            )
            detail_soup = year_guard_fetched_soup
        else:
            try:
                # MODIFICATION: Use thread-local session and remove lock
                # with _SC_SESSION_LOCK: # ADDED LOCK
                detail_response = _get_session().get(movie_page_full_url, timeout=15)
                detail_response.raise_for_status()
                detail_soup = BeautifulSoup(detail_response.text, "html.parser")
            except Exception as exc:
                core.logger.error(
                    f"[{service_name}] Detail page fetch/parse failed for {movie_page_full_url}: {exc}"
                )
                continue
        try:
            filename_parts = href.split("/")
            filename_base_from_href = (
                filename_parts[-1].replace(".html", "")
                if filename_parts
                else "subtitle"
            )
            original_id_from_href = (
                filename_parts[-2] if len(filename_parts) > 1 else "id"
            )

        except IndexError as e_url_parse:
            core.logger.error(
                f"[{service_name}] Could not parse ID/filename from relative URL '{href}': {e_url_parse}"
            )
            filename_base_from_href = "subtitle"
            original_id_from_href = "id"

        language_entries = detail_soup.select(
            'div.all-sub div.row > div[class*="col-"] > div.sub-single'
        )
        if not language_entries:
            core.logger.debug(
                f"[{service_name}] No language entries ('div.all-sub div.row > div[class*=\"col-\"] > div.sub-single') found on detail page: {movie_page_full_url}"
            )
        for entry_div in language_entries:
            img_tag = entry_div.select_one("span:first-child > img[alt]")
            if not img_tag:
                core.logger.debug(
                    f"[{service_name}] No 'span:first-child > img[alt]' in language entry. Skipping."
                )
                continue
            sc_lang_code = img_tag.get("alt")
            if not sc_lang_code:
                core.logger.debug(
                    f"[{service_name}] 'span:first-child > img[alt]' found but no alt attribute. Skipping."
                )
                continue
            lang_name_span = entry_div.select_one("span:first-child + span")
            sc_lang_name_full = sc_lang_code
            if lang_name_span:
                temp_name = lang_name_span.get_text(strip=True)
                if temp_name:
                    sc_lang_name_full = temp_name

            kodi_target_lang_full = sc_lang_name_full
            kodi_target_lang_2_letter = sc_lang_code.split("-")[0].lower()

            sc_lang_code_lower = sc_lang_code.lower()
            if sc_lang_code.lower().startswith("zh-"):
                kodi_target_lang_full = "Chinese"
                kodi_target_lang_2_letter = "zh"
            elif sc_lang_code_lower in KODI_REGIONAL_LANG_MAP:
                map_full_name, map_iso_code = KODI_REGIONAL_LANG_MAP[
                    sc_lang_code_lower
                ]
                kodi_target_lang_full = map_full_name
                kodi_target_lang_2_letter = map_iso_code
            else:
                try:
                    converted_full_name = core.utils.get_lang_id(
                        sc_lang_code, core.kodi.xbmc.ENGLISH_NAME
                    )
                    if converted_full_name:
                        kodi_target_lang_full = converted_full_name
                    converted_iso2_code = core.utils.get_lang_id(
                        kodi_target_lang_full, core.kodi.xbmc.ISO_639_1
                    )
                    if converted_iso2_code:
                        kodi_target_lang_2_letter = converted_iso2_code.lower()
                except Exception as e_lang_conv:
                    if sc_lang_code not in seen_lang_conv_errors:
                        core.logger.debug(
                            f"[{service_name}] Error converting lang code '{sc_lang_code}' "
                            f"(name: '{sc_lang_name_full}'): {e_lang_conv}. "
                            f"Using fallbacks: Full='{kodi_target_lang_full}', "
                            f"ISO2='{kodi_target_lang_2_letter}'."
                        )
                        seen_lang_conv_errors.add(sc_lang_code)

            if (
                _base_name(kodi_target_lang_full) not in wanted_languages_lower
                and kodi_target_lang_2_letter not in wanted_iso2
            ):
                continue

            constructed_filename = (
                f"{original_id_from_href}-{filename_base_from_href}-{sc_lang_code}.srt"
            )

            shared_translation_found_and_used = False
            try:
                shared_headers = {
                    "User-Agent": SC_USER_AGENT,  # This is fine
                    "Referer": movie_page_full_url,
                    "Accept": "application/json, */*",
                }
                core.logger.debug(
                    f"[{service_name}] Attempting to fetch shared translation for '{constructed_filename}' from {shared_translation_url} (referer: {movie_page_full_url})"
                )
                # MODIFICATION: Use thread-local session and remove lock
                # with _SC_SESSION_LOCK: # ADDED LOCK
                shared_response = _get_session().get(
                    shared_translation_url,
                    headers=shared_headers,
                    timeout=shared_translation_timeout,
                )

                if shared_response.status_code == 200 and shared_response.headers.get(
                    "content-type", ""
                ).startswith("application/json"):
                    json_response = shared_response.json()
                    shared_srt_text = json_response.get("text")
                    shared_srt_lang = json_response.get("language")

                    if (
                        shared_srt_text
                        and isinstance(shared_srt_text, str)
                        and shared_srt_text.strip()
                    ):
                        core.logger.debug(
                            f"[{service_name}] Found shared translation for '{constructed_filename}' (lang: {shared_srt_lang or 'N/A'})"
                        )

                        action_args_shared = {
                            "method_type": "SHARED_TRANSLATION_CONTENT",
                            "srt_content": shared_srt_text,
                            "filename": constructed_filename,
                            "lang": kodi_target_lang_full,
                            "service_name": service_name,
                            "detail_url": movie_page_full_url,
                            "lang_code": sc_lang_code,
                        }
                        item_color_shared = "cyan"

                        results.append(
                            {
                                "service_name": service_name,
                                "service": display_name_for_service,
                                "lang": kodi_target_lang_full,
                                "name": f"{movie_title_on_page} ({sc_lang_name_full}) [Shared]",
                                "rating": 0,
                                "lang_code": kodi_target_lang_2_letter,
                                "sync": "false",
                                "impaired": "false",
                                "color": item_color_shared,
                                "action_args": action_args_shared,
                            }
                        )
                        core.logger.debug(
                            f"[{service_name}] Added result for shared translation: '{constructed_filename}'"
                        )
                        shared_translation_found_and_used = True
                    else:
                        core.logger.debug(
                            f"[{service_name}] Shared translation response for '{constructed_filename}' was empty or invalid. JSON: {str(json_response)[:200]}"
                        )
                elif (
                    shared_response.status_code == 200
                ):  # Already a .debug call, body preview is fine
                    core.logger.debug(
                        f"[{service_name}] Shared translation for '{constructed_filename}' returned status 200 "
                        f"but non-JSON content-type: {shared_response.headers.get('content-type', '')}. "
                        f"Body: {shared_response.text[:200]}"
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
                "url": "",
                "lang": kodi_target_lang_full,
                "filename": constructed_filename,
                "gzip": False,
                "service_name": service_name,
                "detail_url": movie_page_full_url,
                "lang_code": sc_lang_code,
                "needs_poll": False,
                "needs_client_side_translation": False,
            }
            item_color = "white"

            patch_determined_href = None
            a_tag = entry_div.select_one('a.green-link[href*=".srt"]')
            if not a_tag:
                a_tag = entry_div.select_one(
                    r'a[href$=".srt"], a[href*=".srt?download="]'
                )
            if a_tag:
                _raw_href = a_tag.get("href")
                if _raw_href:
                    patch_determined_href = _raw_href

            normalized_sc_lang_for_cache_lookup = sc_lang_code
            if sc_lang_code:
                normalized_sc_lang_for_cache_lookup = KODI_REGIONAL_LANG_MAP.get(
                    sc_lang_code.lower(), (None, sc_lang_code)
                )[1]

            cache_key = (
                movie_page_full_url,
                normalized_sc_lang_for_cache_lookup.lower(),
            )
            cached_url = _TRANSLATED_CACHE.get(
                cache_key
            )  # Using thread-safe LRUCache.get
            if cached_url:
                patch_determined_href = cached_url
                core.logger.debug(
                    f"[{service_name}] Using cached translated URL (from _TRANSLATED_CACHE): {cached_url} for {sc_lang_name_full} on {movie_page_full_url}"
                )

            if patch_determined_href:
                action_args["url"] = urljoin(SC_BASE_URL, patch_determined_href)
            else:
                btn = entry_div.select_one(
                    'button.yellow-link[onclick*="translate_from_server_folder"]'
                )
                if not btn:
                    btn = entry_div.select_one(
                        'button[onclick*="translate_from_server_folder"]'
                    )

                if btn:
                    _onclick_attr = btn.get("onclick")
                    if not _onclick_attr:
                        core.logger.debug(
                            f"[{service_name}] Translate button for '{sc_lang_name_full}' has no onclick. Skipping."
                        )
                        continue

                    target_translation_lang = sc_lang_code
                    derived_folder_path = f"/subs/{original_id_from_href}/"
                    derived_orig_filename_stem = f"{filename_base_from_href}-orig"
                    source_srt_filename = f"{derived_orig_filename_stem}.srt"
                    source_srt_url = urljoin(
                        SC_BASE_URL, derived_folder_path + source_srt_filename
                    )

                    core.logger.debug(
                        f"[{service_name}] Client translation needed: target_lang='{target_translation_lang}', source_url='{source_srt_url}'"
                    )

                    action_args.update(
                        {
                            "needs_client_side_translation": True,
                            "original_srt_url": source_srt_url,
                            "target_translation_lang": target_translation_lang,  # This is SC lang code (e.g. 'en', 'pt-br')
                            "url": "",  # No direct download URL yet
                        }
                    )
                    item_color = "yellow"
                else:
                    core.logger.debug(
                        f"[{service_name}] No download link or translate button for '{sc_lang_name_full}'. Skipping."
                    )
                    continue

            results.append(
                {
                    "service_name": service_name,
                    "service": display_name_for_service,
                    "lang": kodi_target_lang_full,
                    "name": f"{movie_title_on_page} ({sc_lang_name_full})",
                    "rating": 0,
                    "lang_code": kodi_target_lang_2_letter,
                    "sync": "false",
                    "impaired": "false",
                    "color": item_color,
                    "action_args": action_args,
                }
            )
            core.logger.debug(
                f"[{service_name}] Added result '{action_args['filename']}' for lang "
                f"'{kodi_target_lang_full}' (ClientTranslate: {action_args['needs_client_side_translation']}, "
                f"URL: {action_args['url']})"
            )

    if results:
        core.logger.debug(
            f"[{service_name}] Returning {len(results)} results after parsing."
        )
        return results

    fallback_reason = None
    try:
        if response is None:
            fallback_reason = "no response"
        elif response.status_code >= 400:
            fallback_reason = f"HTTP {response.status_code}"
        else:
            response_text_preview = response.text[:4000] if response.text else ""
            lowered = response_text_preview.lower()
            if "cloudflare" in lowered or "just a moment" in lowered:
                fallback_reason = "Cloudflare challenge"
    except Exception as resp_exc:
        fallback_reason = f"response inspection failed: {resp_exc}"

    core.logger.debug(
        f"[{service_name}] Primary scraper returned no results. Fallback reason: {fallback_reason or 'empty result set'}"
    )

    try:
        fallback_results = headless_bridge.search(core, service_name, meta)
    except Exception as headless_exc:
        core.logger.error(
            f"[{service_name}] Headless bridge search failed: {headless_exc}"
        )
        fallback_results = []

    if fallback_results:
        core.logger.warning(
            f"[{service_name}] Headless bridge returned {len(fallback_results)} results after primary scraper failed ({fallback_reason or 'no specific reason'})."
        )
        return fallback_results

    core.logger.debug(
        f"[{service_name}] Headless bridge unavailable or returned no results."
    )
    return results


# ---------------------------------------------------------------------------
# DOWNLOAD REQUEST BUILDER
def build_download_request(core, service_name, args):
    """
    Builds the download request for the subtitlecat service.

    Args:
        core (module): The core module.
        service_name (str): The name of the service.
        args (dict): The arguments for the download.

    Returns:
        dict: The download request.
    """
    _filename_from_args = args.get("filename", "unknown_subtitle.srt")
    core.logger.debug(
        f"[{service_name}] Building download request for: {_filename_from_args}, Args: {str(args)[:500]}"
    )

    placeholder_str = _get_setting(
        core,
        "subtitlecat_translation_failed_placeholder",
        DEFAULT_TRANSLATION_FAILED_PLACEHOLDER,
    )

    if args.get("needs_client_side_translation") and _get_setting(core, "debug", False):
        source_lang_override_setting = (
            _get_setting(core, "subtitlecat_source_lang_override", "auto")
            .strip()
            .lower()
        )
        if source_lang_override_setting and source_lang_override_setting != "auto":
            core.logger.debug(
                f"[{service_name}] Client-side translation: Using source language override '{source_lang_override_setting}' from settings."
            )
        else:
            core.logger.debug(
                f"[{service_name}] Client-side translation: Using automatic source language detection (sl=auto)."
            )

    headless_attempted = False

    def _attempt_headless_download(path_from_core_local):
        nonlocal headless_attempted
        if headless_attempted:
            return False
        headless_attempted = True
        if args.get("needs_client_side_translation"):
            core.logger.debug(
                f"[{service_name}] Skipping headless download fallback because client-side translation is required."
            )
            return False
        detail_url = args.get("detail_url")
        lang_code = args.get("lang_code")
        if not detail_url or not lang_code:
            core.logger.debug(
                f"[{service_name}] Headless download fallback skipped – missing detail_url/lang_code in action args."
            )
            return False
        try:
            success = headless_bridge.download(
                core,
                service_name,
                detail_url,
                lang_code,
                path_from_core_local,
                args.get("filename"),
            )
            if success:
                core.logger.warning(
                    f"[{service_name}] Headless bridge download succeeded for {detail_url} ({lang_code})."
                )
            else:
                core.logger.error(
                    f"[{service_name}] Headless bridge download failed for {detail_url} ({lang_code})."
                )
            return success
        except Exception as headless_exc:
            core.logger.error(
                f"[{service_name}] Headless bridge download raised error for {detail_url} ({lang_code}): {headless_exc}"
            )
            return False

    def _save_from_subtitlecat_url(path_from_core, url_to_download):
        _timeout = _get_setting(core, "http_timeout", 15)
        resp_for_save = None
        core.logger.debug(
            f"[{service_name}] _save_from_subtitlecat_url: Downloading from {url_to_download} to {repr(path_from_core)} with timeout {_timeout}s"
        )
        try:
            # MODIFICATION: Use thread-local session and remove lock
            # with _SC_SESSION_LOCK: # ADDED LOCK
            # Headers passed here will be merged with session's default headers (like User-Agent)
            resp_for_save = _get_session().get(
                url_to_download, timeout=_timeout, stream=True
            )
            resp_for_save.raise_for_status()
            raw_bytes = resp_for_save.content
            core.logger.debug(
                f"[{service_name}] _save_from_subtitlecat_url: Download successful, {len(raw_bytes)} bytes received."
            )

            _post_download_fix_encoding(core, service_name, raw_bytes, path_from_core)
            core.logger.debug(
                f"[{service_name}] _save_from_subtitlecat_url: Processing complete for {repr(path_from_core)}"
            )
            return True
        except system_requests.exceptions.Timeout:
            core.logger.error(
                f"[{service_name}] _save_from_subtitlecat_url: Timeout during download from {url_to_download} for {repr(path_from_core)}"
            )
            if _attempt_headless_download(path_from_core):
                return True
            return False
        except system_requests.exceptions.RequestException as e_req:
            core.logger.error(
                f"[{service_name}] _save_from_subtitlecat_url: RequestException for {url_to_download}: {e_req}"
            )
            if _attempt_headless_download(path_from_core):
                return True
            return False
        except Exception as e_proc:
            core.logger.error(
                f"[{service_name}] _save_from_subtitlecat_url: Error processing {url_to_download}: {e_proc}"
            )
            if _attempt_headless_download(path_from_core):
                return True
            return False
        finally:
            if resp_for_save:
                resp_for_save.close()

    if args.get("needs_client_side_translation"):
        core.logger.debug(
            f"[{service_name}] Starting client-side translation for '{_filename_from_args}'"
        )
        original_srt_url = args["original_srt_url"]
        target_gtranslate_lang = args["target_translation_lang"]

        final_translated_srt_str = None
        overall_detected_source_lang = "auto"
        original_srt_text_content = "NOT_FETCHED_DUE_TO_CACHE_HIT"

        # REFINED: Conditional event loop policy setting
        if (
            _AIOHTTP_AVAILABLE
            and asyncio
            and sys.platform.startswith("win")
            and _get_setting(core, "force_selector_loop", False)
        ):
            try:
                # ProactorEventLoopPolicy is default on Win >=3.8 and an attribute of asyncio module.
                # SelectorEventLoopPolicy is an attribute of asyncio module on Win >=3.7.
                # We only want to switch if it's currently Proactor.
                if sys.version_info >= (3, 8) and hasattr(
                    asyncio, "WindowsProactorEventLoopPolicy"
                ):  # Check Proactor exists
                    current_policy = asyncio.get_event_loop_policy()
                    if isinstance(
                        current_policy, asyncio.WindowsProactorEventLoopPolicy
                    ):
                        if hasattr(
                            asyncio, "WindowsSelectorEventLoopPolicy"
                        ):  # Check Selector exists
                            asyncio.set_event_loop_policy(
                                asyncio.WindowsSelectorEventLoopPolicy()
                            )
                            core.logger.debug(
                                f"[{service_name}] Applied WindowsSelectorEventLoopPolicy (was Proactor) due to 'force_selector_loop' setting."
                            )
                        # else: # Not strictly needed to log this, but could be for deep debug
                        #    core.logger.warning(f"[{service_name}] Cannot switch from Proactor: WindowsSelectorEventLoopPolicy not found on asyncio module.")
                # else: # Not Python 3.8+ or Proactor policy not available on asyncio module for various reasons
                #    core.logger.debug(f"[{service_name}] Not on Python 3.8+ or Proactor policy not available/not current. No check/change made for Proactor to Selector.")
            except Exception as e_policy:
                core.logger.error(
                    f"[{service_name}] Failed to apply/check WindowsSelectorEventLoopPolicy: {e_policy}"
                )

        # REMOVED: Event loop management (event_loop_for_this_job, loop_created_by_bdr) as it's no longer used here.

        cache_key_content = (original_srt_url, target_gtranslate_lang)
        cached_content_data = _CLIENT_TRANSLATED_CONTENT_CACHE.get(cache_key_content)

        try:  # This try block no longer needs a finally for loop cleanup
            if cached_content_data:
                core.logger.debug(
                    f"[{service_name}] Using cached client-translated SRT content for {original_srt_url} to {target_gtranslate_lang}."
                )
                final_translated_srt_str = cached_content_data["srt_content"]
                overall_detected_source_lang = cached_content_data[
                    "detected_source_lang"
                ]
            else:
                core.logger.debug(
                    f"[{service_name}] Downloading original SRT from: {original_srt_url}"
                )
                dl_timeout = _get_setting(core, "http_timeout", 20)
                # MODIFICATION: Use thread-local session and remove lock
                # with _SC_SESSION_LOCK: # ADDED LOCK
                original_srt_response = _get_session().get(
                    original_srt_url, timeout=dl_timeout
                )
                original_srt_response.raise_for_status()
                original_srt_text_content = original_srt_response.text
                original_srt_response.close()
                core.logger.debug(
                    f"[{service_name}] Downloaded original SRT content ({len(original_srt_text_content)} chars)."
                )

                parsed_subs = list(srt.parse(original_srt_text_content))
                core.logger.debug(
                    f"[{service_name}] Parsed {len(parsed_subs)} subtitle items from original SRT."
                )

                contains_any_tags_globally = False
                all_logical_lines_original_protected = []
                logical_line_metadata = []

                for srt_idx, srt_item in enumerate(parsed_subs):
                    original_logical_lines_for_srt_item = srt_item.content.split("\n")
                    for logical_line_idx, logical_line_content in enumerate(
                        original_logical_lines_for_srt_item
                    ):
                        protected_text, tags_map, is_all_tag_line = (
                            _protect_subtitle_tags(logical_line_content)
                        )
                        if tags_map:
                            contains_any_tags_globally = True
                        all_logical_lines_original_protected.append(protected_text)
                        logical_line_metadata.append(
                            {
                                "original_srt_item_idx": srt_idx,
                                "original_logical_line_idx_within_srt_item": logical_line_idx,
                                "tags_map_for_this_logical_line": tags_map,
                                "is_all_tag_logical_line": is_all_tag_line,
                            }
                        )
                core.logger.debug(
                    f"[{service_name}] Prepared {len(all_logical_lines_original_protected)} logical lines for translation processing."
                )

                texts_to_translate_for_api = []
                for original_idx, line_content in enumerate(
                    all_logical_lines_original_protected
                ):
                    if not logical_line_metadata[original_idx][
                        "is_all_tag_logical_line"
                    ]:
                        cleaned_line = line_content.translate(
                            _CLEAN_CTRL_TRANSLATION_TABLE
                        )
                        texts_to_translate_for_api.append(cleaned_line)

                core.logger.debug(
                    f"[{service_name}] Found {len(texts_to_translate_for_api)} actual text lines requiring translation API calls (after cleaning and tag filtering)."
                )

                all_translated_pure_text_lines_from_google = []
                all_detected_source_langs_overall = []

                current_api_batch_lines_for_google = []
                current_api_batch_char_count = 0

                api_char_limit = GOOGLE_API_Q_PARAM_CHAR_LIMIT
                api_line_limit = MAX_LINES_PER_API_CALL_CONFIG
                batch_delay_setting = _get_setting(
                    core,
                    "subtitlecat_translation_batch_delay",
                    DEFAULT_BATCH_DELAY_SECONDS,
                )

                if not texts_to_translate_for_api:
                    core.logger.debug(
                        f"[{service_name}] No text lines to translate after filtering. Skipping API calls."
                    )
                else:
                    for i, protected_text_line_for_google in enumerate(
                        texts_to_translate_for_api
                    ):
                        line_char_count = len(protected_text_line_for_google)
                        potential_new_char_count = (
                            current_api_batch_char_count
                            + line_char_count
                            + (1 if current_api_batch_lines_for_google else 0)
                        )

                        if current_api_batch_lines_for_google and (
                            potential_new_char_count > api_char_limit
                            or len(current_api_batch_lines_for_google) >= api_line_limit
                        ):
                            core.logger.debug(
                                f"[{service_name}] Processing API batch of {len(current_api_batch_lines_for_google)} lines, {current_api_batch_char_count} chars."
                            )

                            result = _gtranslate_text_chunk(
                                current_api_batch_lines_for_google,
                                target_gtranslate_lang,
                                core,
                                service_name,
                                0,
                            )
                            if isinstance(result, tuple):
                                translated_segments, detected_lang_from_chunk = result
                            else:
                                translated_segments = str(result).split(_CHUNK_SEP)
                                detected_lang_from_chunk = "auto"

                            if len(translated_segments) != len(
                                current_api_batch_lines_for_google
                            ):
                                core.logger.error(
                                    f"[{service_name}] CRITICAL MISMATCH: _gtranslate_text_chunk returned "
                                    f"{len(translated_segments)}, expected {len(current_api_batch_lines_for_google)}. "
                                    f"Correcting."
                                )
                                corrected_segments = [
                                    placeholder_str if line.strip() else ""
                                    for line in current_api_batch_lines_for_google
                                ]
                                for k_idx in range(
                                    min(
                                        len(translated_segments),
                                        len(corrected_segments),
                                    )
                                ):
                                    corrected_segments[k_idx] = translated_segments[
                                        k_idx
                                    ]
                                all_translated_pure_text_lines_from_google.extend(
                                    corrected_segments
                                )
                            else:
                                all_translated_pure_text_lines_from_google.extend(
                                    translated_segments
                                )

                            if (
                                detected_lang_from_chunk
                                and detected_lang_from_chunk != "auto"
                            ):
                                all_detected_source_langs_overall.append(
                                    detected_lang_from_chunk
                                )

                            current_api_batch_lines_for_google = []
                            current_api_batch_char_count = 0

                            if batch_delay_setting > 0 and i < len(
                                texts_to_translate_for_api
                            ):
                                time.sleep(batch_delay_setting)

                        current_api_batch_lines_for_google.append(
                            protected_text_line_for_google
                        )
                        current_api_batch_char_count += line_char_count
                        if len(current_api_batch_lines_for_google) > 1:
                            current_api_batch_char_count += 1

                    if current_api_batch_lines_for_google:
                        core.logger.debug(
                            f"[{service_name}] Processing final API batch of {len(current_api_batch_lines_for_google)} lines, {current_api_batch_char_count} chars."
                        )
                        result = _gtranslate_text_chunk(
                            current_api_batch_lines_for_google,
                            target_gtranslate_lang,
                            core,
                            service_name,
                            0,
                        )
                        if isinstance(result, tuple):
                            translated_segments, detected_lang_from_chunk = result
                        else:
                            translated_segments = str(result).split(_CHUNK_SEP)
                            detected_lang_from_chunk = "auto"

                        if len(translated_segments) != len(
                            current_api_batch_lines_for_google
                        ):
                            core.logger.error(
                                f"[{service_name}] CRITICAL MISMATCH (final batch): _gtranslate_text_chunk returned "
                                f"{len(translated_segments)}, expected {len(current_api_batch_lines_for_google)}. "
                                f"Correcting."
                            )
                            corrected_segments = [
                                placeholder_str if line.strip() else ""
                                for line in current_api_batch_lines_for_google
                            ]
                            for k_idx in range(
                                min(len(translated_segments), len(corrected_segments))
                            ):
                                corrected_segments[k_idx] = translated_segments[k_idx]
                            all_translated_pure_text_lines_from_google.extend(
                                corrected_segments
                            )
                        else:
                            all_translated_pure_text_lines_from_google.extend(
                                translated_segments
                            )

                        if (
                            detected_lang_from_chunk
                            and detected_lang_from_chunk != "auto"
                        ):
                            all_detected_source_langs_overall.append(
                                detected_lang_from_chunk
                            )

                final_flat_processed_logical_lines = [""] * len(
                    all_logical_lines_original_protected
                )
                current_translated_text_idx = 0

                for original_idx, original_protected_line_val in enumerate(
                    all_logical_lines_original_protected
                ):
                    meta_for_line = logical_line_metadata[original_idx]
                    if meta_for_line["is_all_tag_logical_line"]:
                        final_flat_processed_logical_lines[original_idx] = (
                            original_protected_line_val
                        )
                    else:
                        if current_translated_text_idx < len(
                            all_translated_pure_text_lines_from_google
                        ):
                            translated_line_from_google = (
                                all_translated_pure_text_lines_from_google[
                                    current_translated_text_idx
                                ]
                            )

                            if translated_line_from_google == placeholder_str:
                                final_flat_processed_logical_lines[original_idx] = (
                                    placeholder_str
                                )
                            else:
                                restored_line = translated_line_from_google
                                if (
                                    contains_any_tags_globally
                                    and meta_for_line["tags_map_for_this_logical_line"]
                                ):
                                    restored_line = _restore_subtitle_tags(
                                        translated_line_from_google,
                                        meta_for_line["tags_map_for_this_logical_line"],
                                    )
                                final_flat_processed_logical_lines[original_idx] = (
                                    html.unescape(restored_line)
                                )
                            current_translated_text_idx += 1
                        else:
                            core.logger.error(
                                f"[{service_name}] Mismatch during final reconstruction. Expected translated text for original_idx {original_idx} but ran out. Using placeholder."
                            )
                            final_flat_processed_logical_lines[original_idx] = (
                                placeholder_str
                                if all_logical_lines_original_protected[
                                    original_idx
                                ].strip()
                                else ""
                            )

                if current_translated_text_idx != len(
                    all_translated_pure_text_lines_from_google
                ):
                    core.logger.error(
                        f"[{service_name}] Mismatch: Processed {current_translated_text_idx} translated lines from google, "
                        f"but API processing yielded {len(all_translated_pure_text_lines_from_google)} lines for "
                        f"{len(texts_to_translate_for_api)} inputs."
                    )

                flat_line_cursor = 0
                for srt_idx_rebuild, srt_item_rebuild in enumerate(parsed_subs):
                    num_logical_lines_in_this_srt_item = (
                        srt_item_rebuild.content.count("\n") + 1
                    )
                    end_slice = min(
                        flat_line_cursor + num_logical_lines_in_this_srt_item,
                        len(final_flat_processed_logical_lines),
                    )
                    new_content_lines_for_srt_item = final_flat_processed_logical_lines[
                        flat_line_cursor:end_slice
                    ]

                    if (
                        len(new_content_lines_for_srt_item)
                        != num_logical_lines_in_this_srt_item
                    ):
                        core.logger.error(
                            f"[{service_name}] Mismatch during SRT item reconstruction for srt_idx {srt_idx_rebuild}. "
                            f"Expected {num_logical_lines_in_this_srt_item} lines, got "
                            f"{len(new_content_lines_for_srt_item)}. Padding."
                        )
                        padding_count = num_logical_lines_in_this_srt_item - len(
                            new_content_lines_for_srt_item
                        )
                        if padding_count > 0:
                            new_content_lines_for_srt_item.extend([""] * padding_count)

                    parsed_subs[srt_idx_rebuild].content = "\n".join(
                        new_content_lines_for_srt_item
                    )
                    flat_line_cursor += num_logical_lines_in_this_srt_item

                if flat_line_cursor != len(final_flat_processed_logical_lines):
                    core.logger.error(
                        f"[{service_name}] Mismatch: Processed {flat_line_cursor} flat lines for SRT reconstruction, but had {len(final_flat_processed_logical_lines)} total."
                    )

                if all_detected_source_langs_overall:
                    counts = Counter(all_detected_source_langs_overall)
                    if counts:
                        overall_detected_source_lang = counts.most_common(1)[0][0]
                core.logger.debug(
                    f"[{service_name}] Overall detected source language from API calls: {overall_detected_source_lang}"
                )

                final_translated_srt_str = srt.compose(parsed_subs)
                core.logger.debug(
                    f"[{service_name}] Successfully composed translated SRT string ({len(final_translated_srt_str)} chars)."
                )

            new_url_from_sc = None
            if _get_setting(core, "subtitlecat_upload_translations", False):
                core.logger.debug(
                    f"[{service_name}] Uploading client-translated subtitle is enabled."
                )
                sc_original_filename_stem = "unknown_stem"
                try:
                    parsed_url_path = urllib.parse.urlparse(original_srt_url).path
                    sc_original_filename_stem = urllib.parse.unquote(
                        parsed_url_path.split("/")[-1]
                    )
                    if not sc_original_filename_stem and "/" in parsed_url_path:
                        sc_original_filename_stem = urllib.parse.unquote(
                            parsed_url_path.split("/")[-2]
                        )
                    if sc_original_filename_stem.lower().endswith(".srt"):
                        sc_original_filename_stem = sc_original_filename_stem[:-4]
                    core.logger.debug(
                        f"[{service_name}] Extracted sc_original_filename_stem for upload: {sc_original_filename_stem}"
                    )
                except Exception as e_parse_stem:
                    core.logger.error(
                        f"[{service_name}] Error parsing original_srt_url for filename stem: {e_parse_stem}. Using default '{sc_original_filename_stem}'."
                    )

                target_sc_lang_code_for_upload = args.get("lang_code")
                if not target_sc_lang_code_for_upload:
                    core.logger.error(
                        f"[{service_name}] Could not determine target Subtitlecat language code for upload. Aborting upload."
                    )
                else:
                    overall_detected_source_lang_for_upload = (
                        overall_detected_source_lang
                    )
                    if (
                        overall_detected_source_lang_for_upload == "auto"
                        or not overall_detected_source_lang_for_upload
                    ):
                        core.logger.debug(
                            f"[{service_name}] Original language for upload is '{overall_detected_source_lang_for_upload}'. Defaulting to 'en'."
                        )
                        overall_detected_source_lang_for_upload = "en"

                    new_url_from_sc = _upload_translation_to_subtitlecat(
                        core,
                        service_name,
                        final_translated_srt_str,
                        target_sc_lang_code_for_upload,
                        sc_original_filename_stem,
                        overall_detected_source_lang_for_upload,
                        args.get("detail_url"),
                    )
            else:
                core.logger.debug(
                    f"[{service_name}] Uploading client-translated subtitle is disabled by setting."
                )

            if not new_url_from_sc and not cached_content_data:
                core.logger.debug(
                    f"[{service_name}] Storing client-translated content in _CLIENT_TRANSLATED_CONTENT_CACHE for key: {cache_key_content}"
                )
                _CLIENT_TRANSLATED_CONTENT_CACHE[cache_key_content] = {
                    "srt_content": final_translated_srt_str,
                    "detected_source_lang": overall_detected_source_lang,
                }

            if new_url_from_sc:
                core.logger.debug(
                    f"[{service_name}] Upload successful. Callback will download from: {new_url_from_sc}"
                )
                cache_key_lang = args.get("lang_code", target_gtranslate_lang).lower()
                _TRANSLATED_CACHE[(args.get("detail_url"), cache_key_lang)] = (
                    new_url_from_sc
                )
                core.logger.debug(
                    f"[{service_name}] Stored translated URL in _TRANSLATED_CACHE for key ({args.get('detail_url')}, {cache_key_lang})"
                )
                if _get_setting(core, "subtitlecat_notify_upload", True):
                    try:
                        core.kodi.notification("Subtitle uploaded to Subtitlecat.")
                    except Exception as e_notify:
                        core.logger.error(
                            f"[{service_name}] Failed to send upload notification: {e_notify}"
                        )
                return {
                    "method": "REQUEST_CALLBACK",
                    "save_callback": lambda path: _save_from_subtitlecat_url(
                        path, new_url_from_sc
                    ),
                    "filename": _filename_from_args,
                }
            else:
                core.logger.debug(
                    f"[{service_name}] Upload failed or disabled. Using locally translated SRT content directly."
                )

                def _save_client_translated_srt(path_from_core):
                    try:
                        import io

                        bom = _get_setting(core, "force_bom", False)
                        final_encoding = "utf-8-sig" if bom else "utf-8"
                        with io.open(path_from_core, "w", encoding=final_encoding) as f:
                            f.write(final_translated_srt_str)
                        core.logger.debug(
                            f"[{service_name}] Client-translated SRT saved to '{path_from_core}' with encoding '{final_encoding}'."
                        )
                        return True
                    except Exception as e_save:
                        core.logger.error(
                            f"[{service_name}] Failed to save client-translated SRT to '{path_from_core}': {e_save}"
                        )
                        return False

                return {
                    "method": "CLIENT_SIDE_TRANSLATED",
                    "url": args["original_srt_url"],
                    "save_callback": _save_client_translated_srt,
                    "filename": _filename_from_args,
                }

        except system_requests.exceptions.RequestException as e_req:
            core.logger.error(
                f"[{service_name}] Client-side translation: Network error downloading original SRT {original_srt_url}: {e_req}"
            )
            raise
        except srt.SRTParseError as e_srt:
            core.logger.error(
                f"[{service_name}] Client-side translation: SRT parsing error for {original_srt_url}: "
                f"{e_srt}. Content preview: "
                f"{original_srt_text_content[:200] if isinstance(original_srt_text_content, str) else 'N/A'}"
            )
            raise
        except Exception as e_pipeline:
            core.logger.error(
                f"[{service_name}] Client-side translation pipeline failed for '{_filename_from_args}': {e_pipeline}"
            )
            import traceback

            core.logger.error(traceback.format_exc())
            raise
        # REMOVED: finally block that was cleaning up event_loop_for_this_job

    elif args.get("method_type") == "SHARED_TRANSLATION_CONTENT":
        core.logger.debug(
            f"[{service_name}] Using shared translation content for '{args.get('filename')}'"
        )
        srt_content_to_save = args.get("srt_content", "")

        def _save_shared_srt(path_from_core):
            try:
                current_srt_text_str = ""
                if isinstance(srt_content_to_save, bytes):
                    core.logger.debug(
                        f"[{service_name}] Shared SRT content was bytes, decoding as UTF-8."
                    )
                    current_srt_text_str = srt_content_to_save.decode(
                        "utf-8", errors="replace"
                    )
                else:
                    current_srt_text_str = str(srt_content_to_save)

                temp_unescaped_srt_text = html.unescape(current_srt_text_str)
                temp_bytes_for_fixing = temp_unescaped_srt_text.encode("utf-8")

                _post_download_fix_encoding(
                    core, service_name, temp_bytes_for_fixing, path_from_core
                )

                core.logger.debug(
                    f"[{service_name}] Shared SRT content successfully processed and saved to '{path_from_core}'"
                )
                return True
            except Exception as e_save:
                core.logger.error(
                    f"[{service_name}] Failed to save shared SRT content to '{path_from_core}': {e_save}"
                )
                return False

        return {
            "method": "REQUEST_CALLBACK",
            "save_callback": _save_shared_srt,
            "filename": args.get("filename"),
        }

    else:  # Standard direct download path
        core.logger.debug(
            f"[{service_name}] Proceeding with standard download for '{_filename_from_args}'."
        )
        final_url_for_direct_dl = args.get("url", "")

        if not final_url_for_direct_dl:
            error_msg = f"[{service_name}] Final URL for '{_filename_from_args}' is empty. (Args: {str(args)[:200]}). Cannot download."
            core.logger.error(error_msg)
            raise ValueError(error_msg)

        core.logger.debug(
            f"[{service_name}] Prepared direct download request for '{_filename_from_args}' from {final_url_for_direct_dl}."
        )
        return {
            "method": "REQUEST_CALLBACK",
            "save_callback": lambda path: _save_from_subtitlecat_url(
                path, final_url_for_direct_dl
            ),
            "filename": _filename_from_args,
        }


# END OF MODIFICATION

# --- END OF FILE subtitlecat.py ---
