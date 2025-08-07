import threading
import time
import urllib.parse
from urllib.parse import urljoin
import concurrent.futures
import requests as system_requests
import re

from .utils import (
    _get_session,
    _get_setting,
    SimpleLRUCache,
    SC_BASE_URL,
    SC_USER_AGENT,
)

_AIOHTTP_AVAILABLE = False
try:
    import asyncio
    import aiohttp
    _AIOHTTP_AVAILABLE = True
except ImportError:
    asyncio = None
    aiohttp = None

_TRANSLATED_CACHE = SimpleLRUCache(maxsize=64)
_CLIENT_TRANSLATED_CONTENT_CACHE = SimpleLRUCache(maxsize=128)

GOOGLE_TRANSLATE_URL = "https://translate.googleapis.com/translate_a/single"
GOOGLE_API_Q_PARAM_CHAR_LIMIT = 500
MAX_LINES_PER_API_CALL_CONFIG = 20
DEFAULT_BATCH_DELAY_SECONDS = 0.25
MAX_PARTIAL_RETRIES = 2
DEFAULT_TRANSLATION_FAILED_PLACEHOLDER = "@@SUBTITLECAT_TRANSLATION_UNAVAILABLE@@"

_COUNTER_LOCK = threading.Lock()
GOOGLE_API_REQUEST_COUNT = 0
_LAST_THROTTLE_RESET_TIME = time.monotonic()
GOOGLE_API_REQUEST_LIMIT_DEFAULT = 90
GOOGLE_API_THROTTLE_SLEEP_SECONDS_DEFAULT = 60
GOOGLE_API_COUNTER_RESET_INTERVAL_SECONDS = 3600

def _inc_api_counter_with_reset(core, service_name, log_prefix_throttle=""):
    global GOOGLE_API_REQUEST_COUNT, _LAST_THROTTLE_RESET_TIME
    with _COUNTER_LOCK:
        now = time.monotonic()
        if (now - _LAST_THROTTLE_RESET_TIME) > GOOGLE_API_COUNTER_RESET_INTERVAL_SECONDS:
            if GOOGLE_API_REQUEST_COUNT > 0:
                core.logger.debug(
                    f"[{service_name}] gtranslate: {log_prefix_throttle}Resetting Google API request counter (was {GOOGLE_API_REQUEST_COUNT}) "
                    f"after {GOOGLE_API_COUNTER_RESET_INTERVAL_SECONDS // 60} minutes."
                )
            GOOGLE_API_REQUEST_COUNT = 0
            _LAST_THROTTLE_RESET_TIME = now
        GOOGLE_API_REQUEST_COUNT += 1
        current_count = GOOGLE_API_REQUEST_COUNT
        request_limit = int(_get_setting(core, "subtitlecat_google_api_request_limit", GOOGLE_API_REQUEST_LIMIT_DEFAULT))
        throttle_sleep_duration = int(_get_setting(core, "subtitlecat_google_api_throttle_sleep", GOOGLE_API_THROTTLE_SLEEP_SECONDS_DEFAULT))
        if request_limit > 0 and current_count > 0 and (current_count % request_limit == 0):
            core.logger.debug(
                f"[{service_name}] gtranslate: {log_prefix_throttle}(Throttle, Count: {current_count}) "
                f"API request limit ({request_limit}) reached. "
                f"Signaling throttle for {throttle_sleep_duration}s."
            )
            return current_count, True, throttle_sleep_duration
        return current_count, False, 0

def _gtranslate_single_line_sync(line_to_translate, source_lang_override, target_lang, core, service_name, placeholder_str, recursion_depth_for_single_line, log_prefix_parent):
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
        r = None
        try:
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
            r_text_for_debug = r.text
            r.raise_for_status()
            response_json = r.json()
            if not isinstance(response_json, list):
                raise ValueError(f"Expected list response, got {type(response_json)}")
            if (response_json and response_json[0] and isinstance(response_json[0], list) and
                    len(response_json[0]) > 0 and response_json[0][0] and
                    response_json[0][0][0] is not None):
                translated_text = str(response_json[0][0][0])
                detected_lang_single = response_json[2] if len(response_json) > 2 else "auto"
                return translated_text, detected_lang_single
            else:
                raise ValueError(f"Unexpected response format: {response_json[:3] if isinstance(response_json, list) else response_json}")
        except system_requests.exceptions.Timeout:
            if attempt < MAX_RETRIES_HTTP_SINGLE:
                time.sleep(RETRY_DELAY_BASE_SECONDS_SINGLE * (2 ** attempt))
                continue
            core.logger.error(f"[{service_name}] gtranslate: {log_prefix_single}Timeout after {MAX_RETRIES_HTTP_SINGLE+1} attempts. Using placeholder.")
            return placeholder_str if line_to_translate.strip() else "", detected_lang_single
        except Exception as e:
            if attempt < MAX_RETRIES_HTTP_SINGLE:
                time.sleep(RETRY_DELAY_BASE_SECONDS_SINGLE * (2 ** attempt))
                continue
            core.logger.error(f"[{service_name}] gtranslate: {log_prefix_single}Unexpected error {e}. Using placeholder.")
            return placeholder_str if line_to_translate.strip() else "", detected_lang_single
        finally:
            if r:
                r.close()

def _gtranslate_text_chunk(lines_to_translate, target_lang, core, service_name, recursion_depth=0):
    if not lines_to_translate:
        return [], "auto"
    placeholder_str = _get_setting(core, "subtitlecat_translation_failed_placeholder", DEFAULT_TRANSLATION_FAILED_PLACEHOLDER)
    if recursion_depth >= MAX_PARTIAL_RETRIES:
        log_prefix_guard = f"(Depth {recursion_depth}, MAX_RETRIES_EXCEEDED) "
        first_line_preview_msg = f"'{str(lines_to_translate[0])[:50]}...'" if lines_to_translate else "N/A"
        core.logger.error(f"[{service_name}] gtranslate: {log_prefix_guard}Max recursion depth ({MAX_PARTIAL_RETRIES}) for chunk processing. First: {first_line_preview_msg}. Using placeholders.")
        return [placeholder_str if line.strip() else "" for line in lines_to_translate], "auto"
    if not any(line.strip() for line in lines_to_translate):
        return ["" for _ in lines_to_translate], "auto"
    source_lang_override = _get_setting(core, "subtitlecat_source_lang_override", "auto").strip().lower() or "auto"
    prepared_lines_for_join = [line if line.strip() else " " for line in lines_to_translate]
    joined_query_text = "\n".join(prepared_lines_for_join)
    params_for_api_call = [
        ('client', 'gtx'),
        ('sl', source_lang_override),
        ('tl', target_lang),
        ('dt', 't'),
        ('format', 'text'),
        ('q', joined_query_text)
    ]
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
            core.logger.debug(
                f"[{service_name}] gtranslate: {log_prefix}"
                f"Translating {line_count_desc} to '{target_lang}' {sl_info} via {method_used} "
                f"(single 'q'). Joined query len: {len(joined_query_text)} chars."
            )
        try:
            current_session = _get_session()
            if use_post:
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
            full_translated_text_blob = ""
            if (response_json and isinstance(response_json[0], list)):
                for chunk in response_json[0]:
                    if chunk and isinstance(chunk, list) and chunk[0] is not None:
                        full_translated_text_blob += str(chunk[0])
            if not full_translated_text_blob.strip() and joined_query_text.strip():
                if _get_setting(core, "debug", False):
                    core.logger.debug(f"[{service_name}] gtranslate: {log_prefix}API returned empty translation blob for non-empty joined query. Response: {str(response_json)[:200]}")
            translated_segments_for_this_call_final = full_translated_text_blob.split("\n")
            detected_lang_for_this_call = response_json[2] if len(response_json) > 2 else "auto"
            break
        except system_requests.exceptions.HTTPError as http_err:
            status_code = getattr(http_err.response, 'status_code', None)
            if status_code == 503 and _get_setting(core, "subtitlecat_try_single_line_on_503", True) and len(lines_to_translate) > 1:
                core.logger.debug(f"[{service_name}] gtranslate: {log_prefix}HTTPError 503. Splitting chunk and retrying individually.")
                results_holder = [None] * len(lines_to_translate)
                detected_lang_counter = {}
                with concurrent.futures.ThreadPoolExecutor(max_workers=3) as executor:
                    futures = {}
                    for idx, line in enumerate(lines_to_translate):
                        futures[executor.submit(
                            _gtranslate_single_line_sync,
                            line,
                            source_lang_override,
                            target_lang,
                            core,
                            service_name,
                            placeholder_str,
                            recursion_depth + 1,
                            log_prefix
                        )] = idx
                    for future in concurrent.futures.as_completed(futures):
                        line_idx = futures[future]
                        translated_line, detected_lang_single = future.result()
                        results_holder[line_idx] = translated_line
                        detected_lang_counter[detected_lang_single] = detected_lang_counter.get(detected_lang_single, 0) + 1
                detected_lang_for_this_call = max(detected_lang_counter, key=detected_lang_counter.get) if detected_lang_counter else "auto"
                translated_segments_for_this_call_final = results_holder
                break
            if status_code == 429 and attempt < MAX_RETRIES_HTTP:
                delay = RETRY_DELAY_BASE_SECONDS * (2 ** attempt) + int(_get_setting(core, "subtitlecat_google_api_throttle_sleep", 60) / 2)
                core.logger.debug(f"[{service_name}] gtranslate: {log_prefix}HTTPError 429 (Rate Limit). Retrying in {delay}s...")
                time.sleep(delay)
                continue
            if attempt < MAX_RETRIES_HTTP:
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
        core.logger.error(
            f"[{service_name}] gtranslate: (FinalLengthCheckNL) CRITICAL MISMATCH: "
            f"Final segment count ({len(translated_segments_for_this_call_final)}) != "
            f"input count ({len(lines_to_translate)}). Padding/truncating."
        )
        if len(translated_segments_for_this_call_final) < len(lines_to_translate):
            padding = [placeholder_str if lines_to_translate[i].strip() else "" for i in range(len(translated_segments_for_this_call_final), len(lines_to_translate))]
            translated_segments_for_this_call_final.extend(padding)
        else:
            translated_segments_for_this_call_final = translated_segments_for_this_call_final[:len(lines_to_translate)]
    return translated_segments_for_this_call_final, detected_lang_for_this_call

_PLACEHOLDER_SENTINEL_PREFIX = "\u2063@@SCPTAG_hexidx_"
_PLACEHOLDER_SUFFIX = "_hexidx_SCP@@"
__TAG_REGEX_FOR_PROTECTION = re.compile(r'(<(?:"[^"]*"|\'[^\']*\'|[^>"\'])*>|{(?:"[^"]*"|\'[^\']*\'|[^}\'"])*})')
_CONTROL_CHARS_TO_CLEAN = '\u200b\u200e\u200f'
_CLEAN_CTRL_TRANSLATION_TABLE = str.maketrans('', '', _CONTROL_CHARS_TO_CLEAN)

def _protect_subtitle_tags(text_line):
    stripped_line_no_tags = __TAG_REGEX_FOR_PROTECTION.sub('', text_line).strip()
    if not stripped_line_no_tags:
        return text_line, [], True
    tags_found = []
    def _replacer(match):
        tag = match.group(1)
        tags_found.append(tag)
        placeholder_idx_str = hex(len(tags_found) - 1)[2:]
        return f"{_PLACEHOLDER_SENTINEL_PREFIX}{placeholder_idx_str}{_PLACEHOLDER_SUFFIX}"
    processed_text = __TAG_REGEX_FOR_PROTECTION.sub(_replacer, text_line)
    return processed_text, tags_found, False

def _restore_subtitle_tags(text_line_with_placeholders, tags_list):
    for i in range(len(tags_list) - 1, -1, -1):
        original_tag_content = tags_list[i]
        placeholder_idx_str = hex(i)[2:]
        placeholder = f"{_PLACEHOLDER_SENTINEL_PREFIX}{placeholder_idx_str}{_PLACEHOLDER_SUFFIX}"
        text_line_with_placeholders = text_line_with_placeholders.replace(placeholder, original_tag_content)
    return text_line_with_placeholders

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
        'User-Agent': SC_USER_AGENT,
        'Referer': movie_page_full_url or SC_BASE_URL,
        'Content-Type': 'application/x-www-form-urlencoded; charset=UTF-8',
        'X-Requested-With': 'XMLHttpRequest',
    }
    core.logger.debug(
        f"[{service_name}] Attempting to upload translated subtitle '{name_for_upload}' "
        f"to {upload_url} for language '{target_sc_lang_code}', "
        f"source lang '{detected_source_language_code}'. "
        f"Referer: {headers['Referer']}"
    )
    try:
        response = _get_session().post(upload_url, data=payload, headers=headers, timeout=30)
        response.raise_for_status()
        json_response = response.json()
        if core.settings and core.settings.get("debug", False):
            core.logger.debug(f"[{service_name}] Upload response from Subtitlecat: {str(json_response)[:500]}")
        elif not core.settings:
            core.logger.debug(f"[{service_name}] Upload response from Subtitlecat (details omitted, core.settings unavailable). Echo: {json_response.get('echo')}")
        if json_response.get("echo") == "ok" and json_response.get("url"):
            returned_path = json_response["url"]
            if returned_path.startswith("/"):
                new_srt_url_on_sc = urljoin(SC_BASE_URL, returned_path.lstrip('/'))
            else:
                new_srt_url_on_sc = urljoin(SC_BASE_URL, returned_path)
            core.logger.debug(f"[{service_name}] Successfully uploaded translated subtitle. New URL: {new_srt_url_on_sc}")
            return new_srt_url_on_sc
        else:
            core.logger.error(
                f"[{service_name}] Subtitlecat upload failed or returned unexpected response. "
                f"Echo: {json_response.get('echo')}, URL: {json_response.get('url')}, "
                f"Message: {json_response.get('message')}"
            )
            return None
    except system_requests.exceptions.Timeout:
        core.logger.error(f"[{service_name}] Timeout during subtitle upload to {upload_url}.")
        return None
    except system_requests.exceptions.RequestException as e:
        core.logger.error(f"[{service_name}] RequestException during subtitle upload: {e}")
        return None
    except ValueError as e_json:
        response_text_preview = response.text[:200] if 'response' in locals() and hasattr(response, 'text') else 'N/A'
        core.logger.error(f"[{service_name}] JSONDecodeError parsing Subtitlecat upload response: {e_json}. Response text: {response_text_preview}")
        return None
    except Exception as e_unexp:
        core.logger.error(f"[{service_name}] Unexpected error during subtitle upload: {e_unexp}")
        return None
