import os
import re
import threading
import time
import urllib.parse
from typing import Optional
from urllib.parse import urljoin

from resources.vendor.subtitlecat_translator import (
    GeminiSubtitleTranslator,
    GeminiTranslationError,
)

from .utils import (
    SC_BASE_URL,
    SC_USER_AGENT,
    LRUCache,
    _get_session,
    _get_setting,
    SCRAPER_HTTP_ERROR,
    SCRAPER_REQUEST_EXCEPTION,
    SCRAPER_TIMEOUT_EXCEPTION,
    CLOUDFLARE_CHALLENGE_EXCEPTION,
    CLOUDFLARE_EXCEPTION,
)

_AIOHTTP_AVAILABLE = False
try:
    import asyncio

    import aiohttp

    _AIOHTTP_AVAILABLE = True
except ImportError:
    asyncio = None
    aiohttp = None

_TRANSLATED_CACHE = LRUCache(maxsize=64)
_CLIENT_TRANSLATED_CONTENT_CACHE = LRUCache(maxsize=128)
_CHUNK_SEP = "\u241e"

GEMINI_MAX_JOINED_CHAR_COUNT = 500
MAX_LINES_PER_API_CALL_CONFIG = 20
DEFAULT_BATCH_DELAY_SECONDS = 0.25
MAX_PARTIAL_RETRIES = 2
DEFAULT_TRANSLATION_FAILED_PLACEHOLDER = "@@SUBTITLECAT_TRANSLATION_UNAVAILABLE@@"

_COUNTER_LOCK = threading.Lock()
GEMINI_API_REQUEST_COUNT = 0
_LAST_THROTTLE_RESET_TIME = time.monotonic()
GEMINI_API_REQUEST_LIMIT_DEFAULT = 90
GEMINI_API_THROTTLE_SLEEP_SECONDS_DEFAULT = 60
GEMINI_API_COUNTER_RESET_INTERVAL_SECONDS = 3600
_GEMINI_TRANSLATOR_LOCK = threading.Lock()
_GEMINI_TRANSLATOR: Optional[GeminiSubtitleTranslator] = None
_GEMINI_TRANSLATOR_CONFIG: Optional[tuple[tuple[str, ...], str]] = None


def _parse_api_keys(raw_value: str) -> list[str]:
    keys: list[str] = []
    if raw_value:
        normalized = raw_value.replace(";", "\n").replace(",", "\n")
        for line in normalized.splitlines():
            candidate = line.strip()
            if candidate:
                keys.append(candidate)
    if not keys:
        env_key = os.environ.get("GEMINI_API_KEY") or os.environ.get("GOOGLE_API_KEY")
        if env_key and env_key.strip():
            keys.append(env_key.strip())
    return keys


def _get_gemini_translator(core, service_name: str) -> GeminiSubtitleTranslator:
    global _GEMINI_TRANSLATOR, _GEMINI_TRANSLATOR_CONFIG
    configured_keys = _parse_api_keys(
        _get_setting(core, "subtitlecat_gemini_api_keys", "")
    )
    model_name = (
        _get_setting(core, "subtitlecat_gemini_model", "gemini-2.0-flash").strip()
        or "gemini-2.0-flash"
    )
    config_signature = (tuple(configured_keys), model_name)
    with _GEMINI_TRANSLATOR_LOCK:
        if (
            _GEMINI_TRANSLATOR is None
            or _GEMINI_TRANSLATOR_CONFIG != config_signature
        ):
            if not configured_keys:
                raise GeminiTranslationError(
                    "No Gemini API keys configured for Subtitlecat translations"
                )
            if getattr(core, "logger", None):
                core.logger.debug(
                    f"[{service_name}] gemini: Initialising translator for model '{model_name}' with {len(configured_keys)} key(s)."
                )
            _GEMINI_TRANSLATOR = GeminiSubtitleTranslator(
                configured_keys,
                model=model_name,
            )
            _GEMINI_TRANSLATOR_CONFIG = config_signature
    return _GEMINI_TRANSLATOR


def _inc_gemini_counter_with_reset(core, service_name, log_prefix_throttle=""):
    global GEMINI_API_REQUEST_COUNT, _LAST_THROTTLE_RESET_TIME
    with _COUNTER_LOCK:
        now = time.monotonic()
        if (
            now - _LAST_THROTTLE_RESET_TIME
        ) > GEMINI_API_COUNTER_RESET_INTERVAL_SECONDS:
            if GEMINI_API_REQUEST_COUNT > 0:
                core.logger.debug(
                    f"[{service_name}] gemini: {log_prefix_throttle}Resetting Gemini API request counter (was {GEMINI_API_REQUEST_COUNT}) "
                    f"after {GEMINI_API_COUNTER_RESET_INTERVAL_SECONDS // 60} minutes."
                )
            GEMINI_API_REQUEST_COUNT = 0
            _LAST_THROTTLE_RESET_TIME = now
        GEMINI_API_REQUEST_COUNT += 1
        current_count = GEMINI_API_REQUEST_COUNT
        request_limit = int(
            _get_setting(
                core,
                "subtitlecat_gemini_api_request_limit",
                GEMINI_API_REQUEST_LIMIT_DEFAULT,
            )
        )
        throttle_sleep_duration = int(
            _get_setting(
                core,
                "subtitlecat_gemini_api_throttle_sleep",
                GEMINI_API_THROTTLE_SLEEP_SECONDS_DEFAULT,
            )
        )
        if (
            request_limit > 0
            and current_count > 0
            and (current_count % request_limit == 0)
        ):
            core.logger.debug(
                f"[{service_name}] gemini: {log_prefix_throttle}(Throttle, Count: {current_count}) "
                f"API request limit ({request_limit}) reached. "
                f"Signaling throttle for {throttle_sleep_duration}s."
            )
            return current_count, True, throttle_sleep_duration
        return current_count, False, 0


def _gemini_translate_text_chunk(
    lines_to_translate, target_lang, core, service_name, recursion_depth=0
):
    if not lines_to_translate:
        return [], "auto"

    placeholder_str = _get_setting(
        core,
        "subtitlecat_translation_failed_placeholder",
        DEFAULT_TRANSLATION_FAILED_PLACEHOLDER,
    )

    if recursion_depth >= MAX_PARTIAL_RETRIES:
        first_line_preview_msg = (
            f"'{str(lines_to_translate[0])[:50]}...'" if lines_to_translate else "N/A"
        )
        core.logger.error(
            f"[{service_name}] gemini: (Depth {recursion_depth}) Max recursion depth reached for chunk starting with {first_line_preview_msg}."
        )
        return [
            placeholder_str if line.strip() else "" for line in lines_to_translate
        ], "auto"

    if not any(line.strip() for line in lines_to_translate):
        return ["" for _ in lines_to_translate], "auto"

    source_lang_override = (
        _get_setting(core, "subtitlecat_source_lang_override", "auto").strip().lower()
        or "auto"
    )

    log_prefix = f"(Gemini Depth {recursion_depth}) "
    try:
        translator = _get_gemini_translator(core, service_name)
    except GeminiTranslationError as exc:
        core.logger.error(
            f"[{service_name}] gemini: {log_prefix}Translator initialisation failed: {exc}"
        )
        return [
            placeholder_str if line.strip() else "" for line in lines_to_translate
        ], "auto"

    _, should_throttle, throttle_duration = _inc_gemini_counter_with_reset(
        core, service_name, log_prefix
    )
    if should_throttle:
        time.sleep(throttle_duration)

    debug_enabled = _get_setting(core, "debug", False)

    try:
        if debug_enabled:
            core.logger.debug(
                f"[{service_name}] gemini: {log_prefix}Translating {len(lines_to_translate)} line(s) to '{target_lang}' using model {translator.config.model}."
            )
        translations = translator.translate_lines(
            lines_to_translate,
            source_language=source_lang_override,
            target_language=target_lang,
            delimiter=_CHUNK_SEP,
            log=(
                core.logger.debug
                if debug_enabled and getattr(core, "logger", None)
                else None
            ),
        )
        return translations, source_lang_override or "auto"
    except GeminiTranslationError as exc:
        if len(lines_to_translate) > 1:
            core.logger.warning(
                f"[{service_name}] gemini: {log_prefix}Batch translation failed ({exc}). Falling back to per-line translation."
            )
            results = []
            detected_lang_counter = {}
            for line in lines_to_translate:
                translated_segment, detected_lang = _gemini_translate_text_chunk(
                    [line],
                    target_lang,
                    core,
                    service_name,
                    recursion_depth + 1,
                )
                results.extend(translated_segment)
                detected_lang_counter[detected_lang] = (
                    detected_lang_counter.get(detected_lang, 0) + 1
                )
            detected_lang_final = (
                max(detected_lang_counter, key=detected_lang_counter.get)
                if detected_lang_counter
                else "auto"
            )
            return results, detected_lang_final
        core.logger.error(
            f"[{service_name}] gemini: {log_prefix}Translation failed: {exc}. Using placeholders."
        )
        return [
            placeholder_str if line.strip() else "" for line in lines_to_translate
        ], "auto"

_PLACEHOLDER_SENTINEL_PREFIX = "\u2063@@SCPTAG_hexidx_"
_PLACEHOLDER_SUFFIX = "_hexidx_SCP@@"
__TAG_REGEX_FOR_PROTECTION = re.compile(
    r'(<(?:"[^"]*"|\'[^\']*\'|[^>"\'])*>|{(?:"[^"]*"|\'[^\']*\'|[^}\'"])*})'
)
_CONTROL_CHARS_TO_CLEAN = "\u200b\u200e\u200f"
_CLEAN_CTRL_TRANSLATION_TABLE = str.maketrans("", "", _CONTROL_CHARS_TO_CLEAN)


def _protect_subtitle_tags(text_line):
    """
    Protects subtitle tags from being translated.

    Args:
        text_line (str): The line of text to protect.

    Returns:
        tuple: A tuple containing the protected text, a list of the tags found, and a boolean indicating whether the line is all tags.
    """
    stripped_line_no_tags = __TAG_REGEX_FOR_PROTECTION.sub("", text_line).strip()
    if not stripped_line_no_tags:
        return text_line, [], True
    tags_found = []

    def _replacer(match):
        tag = match.group(1)
        tags_found.append(tag)
        placeholder_idx_str = hex(len(tags_found) - 1)[2:]
        return (
            f"{_PLACEHOLDER_SENTINEL_PREFIX}{placeholder_idx_str}{_PLACEHOLDER_SUFFIX}"
        )

    processed_text = __TAG_REGEX_FOR_PROTECTION.sub(_replacer, text_line)
    return processed_text, tags_found, False


def _restore_subtitle_tags(text_line_with_placeholders, tags_list):
    """
    Restores subtitle tags that were protected.

    Args:
        text_line_with_placeholders (str): The line of text with placeholders.
        tags_list (list): The list of tags to restore.

    Returns:
        str: The line of text with the tags restored.
    """
    for i in range(len(tags_list) - 1, -1, -1):
        original_tag_content = tags_list[i]
        placeholder_idx_str = hex(i)[2:]
        placeholder = (
            f"{_PLACEHOLDER_SENTINEL_PREFIX}{placeholder_idx_str}{_PLACEHOLDER_SUFFIX}"
        )
        text_line_with_placeholders = text_line_with_placeholders.replace(
            placeholder, original_tag_content
        )
    return text_line_with_placeholders


def _upload_translation_to_subtitlecat(
    core,
    service_name,
    translated_srt_content_str,
    target_sc_lang_code,
    original_filename_stem_from_sc,
    detected_source_language_code,
    movie_page_full_url,
):
    """
    Uploads a translated subtitle to Subtitlecat.

    Args:
        core (module): The core module.
        service_name (str): The name of the service.
        translated_srt_content_str (str): The translated SRT content.
        target_sc_lang_code (str): The target language code.
        original_filename_stem_from_sc (str): The original filename stem.
        detected_source_language_code (str): The detected source language code.
        movie_page_full_url (str): The URL of the movie page.

    Returns:
        str: The URL of the uploaded subtitle, or None if the upload failed.
    """
    upload_url = "https://www.subtitlecat.com/upload_subtitles.php"
    name_for_upload = original_filename_stem_from_sc
    if original_filename_stem_from_sc.endswith("-orig.srt"):
        name_for_upload = original_filename_stem_from_sc[: -len("-orig.srt")] + ".srt"
    elif original_filename_stem_from_sc.endswith("-orig"):
        name_for_upload = original_filename_stem_from_sc[: -len("-orig")] + ".srt"
    else:
        if not original_filename_stem_from_sc.endswith(".srt"):
            name_for_upload = f"{original_filename_stem_from_sc}.srt"
            core.logger.debug(
                f"[{service_name}] original_filename_stem_from_sc ('{original_filename_stem_from_sc}') did not end with -orig or -orig.srt. Appended .srt: '{name_for_upload}'"
            )
    payload = {
        "filename": name_for_upload,
        "content": translated_srt_content_str,
        "language": target_sc_lang_code,
        "orig_language": detected_source_language_code,
    }
    headers = {
        "User-Agent": SC_USER_AGENT,
        "Referer": movie_page_full_url or SC_BASE_URL,
        "Content-Type": "application/x-www-form-urlencoded; charset=UTF-8",
        "X-Requested-With": "XMLHttpRequest",
    }
    core.logger.debug(
        f"[{service_name}] Attempting to upload translated subtitle '{name_for_upload}' "
        f"to {upload_url} for language '{target_sc_lang_code}', "
        f"source lang '{detected_source_language_code}'. "
        f"Referer: {headers['Referer']}"
    )
    try:
        response = _get_session().post(
            upload_url, data=payload, headers=headers, timeout=30
        )
        response.raise_for_status()
        json_response = response.json()
        if core.settings and core.settings.get("debug", False):
            core.logger.debug(
                f"[{service_name}] Upload response from Subtitlecat: {str(json_response)[:500]}"
            )
        elif not core.settings:
            core.logger.debug(
                f"[{service_name}] Upload response from Subtitlecat (details omitted, core.settings unavailable). Echo: {json_response.get('echo')}"
            )
        if json_response.get("echo") == "ok" and json_response.get("url"):
            returned_path = json_response["url"]
            if returned_path.startswith("/"):
                new_srt_url_on_sc = urljoin(SC_BASE_URL, returned_path.lstrip("/"))
            else:
                new_srt_url_on_sc = urljoin(SC_BASE_URL, returned_path)
            core.logger.debug(
                f"[{service_name}] Successfully uploaded translated subtitle. New URL: {new_srt_url_on_sc}"
            )
            return new_srt_url_on_sc
        else:
            core.logger.error(
                f"[{service_name}] Subtitlecat upload failed or returned unexpected response. "
                f"Echo: {json_response.get('echo')}, URL: {json_response.get('url')}, "
                f"Message: {json_response.get('message')}"
            )
            return None
    except SCRAPER_TIMEOUT_EXCEPTION:
        core.logger.error(
            f"[{service_name}] Timeout during subtitle upload to {upload_url}."
        )
        return None
    except SCRAPER_REQUEST_EXCEPTION as e:
        core.logger.error(
            f"[{service_name}] RequestException during subtitle upload: {e}"
        )
        return None
    except ValueError as e_json:
        response_text_preview = (
            response.text[:200]
            if "response" in locals() and hasattr(response, "text")
            else "N/A"
        )
        core.logger.error(
            f"[{service_name}] JSONDecodeError parsing Subtitlecat upload response: {e_json}. Response text: {response_text_preview}"
        )
        return None
    except Exception as e_unexp:
        core.logger.error(
            f"[{service_name}] Unexpected error during subtitle upload: {e_unexp}"
        )
        return None


def _notify_rate_limit(core, message: str) -> None:
    notifier = None
    kodi = getattr(core, "kodi", None)
    if kodi is not None:
        notifier = getattr(kodi, "notification", None)
    if callable(notifier):
        try:
            notifier(message)
        except Exception as notify_error:  # pragma: no cover - defensive logging only
            if getattr(core, "logger", None):
                core.logger.debug(
                    f"[subtitlecat] Failed to send Kodi notification: {notify_error}"
                )


def warm_translation_cache(
    core,
    service_name: str,
    translation_url: str,
    *,
    timeout: Optional[float] = None,
    chunk_size: int = 2048,
) -> bool:
    """Prime Subtitlecat's translation cache using the shared scraper session.

    The warm-up fetches a small chunk of the translated subtitle to reduce the
    chance of subsequent requests triggering Cloudflare rate limits. Any
    rate-limiting responses (HTTP 403/503) surface a Kodi notification so users
    receive actionable feedback instead of silent failures.

    Args:
        core: Kodi core adapter providing logging and notifications.
        service_name: Provider name for logging context.
        translation_url: Fully qualified URL to the translated subtitle.
        timeout: Optional per-request timeout override.
        chunk_size: Size of the first chunk to read from the response stream.

    Returns:
        bool: ``True`` if the warm-up succeeded, otherwise ``False``.
    """

    if not translation_url:
        return False

    response = None
    session = _get_session()
    effective_timeout = (
        timeout
        if timeout is not None
        else _get_setting(core, "http_timeout", 15)
    )

    def _handle_rate_limited(status_code: int) -> None:
        if getattr(core, "logger", None):
            core.logger.warning(
                f"[{service_name}] Warm-up request returned HTTP {status_code} for {translation_url}."
            )
        if status_code == 403:
            message = "Subtitlecat blocked the request (HTTP 403). Please try again later."
        else:
            message = "Subtitlecat is temporarily unavailable (HTTP 503). Please try again soon."
        _notify_rate_limit(core, message)

    try:
        response = session.get(
            translation_url,
            stream=True,
            timeout=effective_timeout,
        )
        status_code = getattr(response, "status_code", None)
        if status_code in (403, 503):
            _handle_rate_limited(status_code)
            return False
        response.raise_for_status()

        for chunk in response.iter_content(chunk_size=chunk_size):
            if chunk:
                break
        if getattr(core, "logger", None):
            core.logger.debug(
                f"[{service_name}] Warmed translation cache for {translation_url}."
            )
        return True
    except SCRAPER_TIMEOUT_EXCEPTION as timeout_exc:
        if getattr(core, "logger", None):
            core.logger.warning(
                f"[{service_name}] Timeout warming translation cache for {translation_url}: {timeout_exc}"
            )
        return False
    except CLOUDFLARE_CHALLENGE_EXCEPTION as challenge_exc:
        if getattr(core, "logger", None):
            core.logger.warning(
                f"[{service_name}] Cloudflare challenge during cache warm-up: {challenge_exc}"
            )
        return False
    except CLOUDFLARE_EXCEPTION as cf_exc:
        if getattr(core, "logger", None):
            core.logger.warning(
                f"[{service_name}] Cloudflare error during cache warm-up: {cf_exc}"
            )
        return False
    except SCRAPER_HTTP_ERROR as http_err:
        status_code = getattr(http_err.response, "status_code", None)
        if status_code in (403, 503):
            _handle_rate_limited(status_code)
        if getattr(core, "logger", None):
            core.logger.error(
                f"[{service_name}] HTTP error warming translation cache for {translation_url}: {http_err}"
            )
        return False
    except SCRAPER_REQUEST_EXCEPTION as req_exc:
        if getattr(core, "logger", None):
            core.logger.error(
                f"[{service_name}] Request error warming translation cache for {translation_url}: {req_exc}"
            )
        return False
    finally:
        if response is not None:
            response.close()
