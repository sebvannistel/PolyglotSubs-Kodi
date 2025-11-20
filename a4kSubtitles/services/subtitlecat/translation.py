import os
import re
import sys
import threading
import time
import urllib.parse
from pathlib import Path
from typing import Optional, Sequence
from urllib.parse import urljoin

from .utils import (
    CLOUDFLARE_CHALLENGE_EXCEPTION,
    CLOUDFLARE_EXCEPTION,
    SC_BASE_URL,
    SC_USER_AGENT,
    SCRAPER_HTTP_ERROR,
    SCRAPER_REQUEST_EXCEPTION,
    SCRAPER_TIMEOUT_EXCEPTION,
    LRUCache,
    _get_session,
    _get_setting,
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
_CHUNK_SEP = "␞"

GOOGLE_API_Q_PARAM_CHAR_LIMIT = 500
MAX_LINES_PER_API_CALL_CONFIG = 20
DEFAULT_BATCH_DELAY_SECONDS = 0.25
DEFAULT_TRANSLATION_FAILED_PLACEHOLDER = "@@SUBTITLECAT_TRANSLATION_UNAVAILABLE@@"

_COUNTER_LOCK = threading.Lock()
_GEMINI_API_REQUEST_COUNT = 0
_LAST_THROTTLE_RESET_TIME = time.monotonic()
GEMINI_API_REQUEST_LIMIT_DEFAULT = 90
GEMINI_API_THROTTLE_SLEEP_SECONDS_DEFAULT = 60
GEMINI_API_COUNTER_RESET_INTERVAL_SECONDS = 3600

_TRANSLATOR_CACHE_LOCK = threading.RLock()
_TRANSLATOR_CACHE = {}

_VENDOR_TRANSLATOR_PATH = (
    Path(__file__).resolve().parents[2]
    / "resources"
    / "vendor"
    / "subtitlecat_translator"
)
if _VENDOR_TRANSLATOR_PATH.exists():
    vendor_path_str = str(_VENDOR_TRANSLATOR_PATH)
    if vendor_path_str not in sys.path:
        sys.path.insert(0, vendor_path_str)

try:  # pragma: no cover - import guarded for optional dependency
    from subtitlecat_translator import (  # type: ignore
        GeminiSubtitleTranslator,
        TranslationError,
        TranslatorConfig,
    )
except Exception:  # pragma: no cover - handled lazily in runtime
    GeminiSubtitleTranslator = None  # type: ignore
    TranslationError = Exception  # type: ignore
    TranslatorConfig = None  # type: ignore

_TARGET_LANGUAGE_NAME_OVERRIDES = {
    "zh": "Chinese",
    "zh-cn": "Simplified Chinese",
    "zh-hans": "Simplified Chinese",
    "zh-hant": "Traditional Chinese",
    "zh-tw": "Traditional Chinese",
    "pt-br": "Portuguese (Brazil)",
    "es-419": "Spanish",
    "sr-me": "Serbian",
}


def _inc_gemini_counter_with_reset(core, service_name, log_prefix=""):
    global _GEMINI_API_REQUEST_COUNT, _LAST_THROTTLE_RESET_TIME
    with _COUNTER_LOCK:
        now = time.monotonic()
        if (
            now - _LAST_THROTTLE_RESET_TIME
        ) > GEMINI_API_COUNTER_RESET_INTERVAL_SECONDS:
            if _GEMINI_API_REQUEST_COUNT > 0 and getattr(core, "logger", None):
                core.logger.debug(
                    f"[{service_name}] gemini: {log_prefix}Resetting request counter (was {_GEMINI_API_REQUEST_COUNT}) "
                    f"after {GEMINI_API_COUNTER_RESET_INTERVAL_SECONDS // 60} minutes."
                )
            _GEMINI_API_REQUEST_COUNT = 0
            _LAST_THROTTLE_RESET_TIME = now
        _GEMINI_API_REQUEST_COUNT += 1
        current_count = _GEMINI_API_REQUEST_COUNT
        request_limit = int(
            _get_setting(
                core,
                "subtitlecat_gemini_request_limit",
                GEMINI_API_REQUEST_LIMIT_DEFAULT,
            )
        )
        throttle_sleep_duration = int(
            _get_setting(
                core,
                "subtitlecat_gemini_throttle_sleep",
                GEMINI_API_THROTTLE_SLEEP_SECONDS_DEFAULT,
            )
        )
        if (
            request_limit > 0
            and current_count > 0
            and current_count % request_limit == 0
        ):
            if getattr(core, "logger", None):
                core.logger.debug(
                    f"[{service_name}] gemini: {log_prefix}(Throttle, Count: {current_count}) "
                    f"Request limit ({request_limit}) reached. Sleeping for {throttle_sleep_duration}s."
                )
            return current_count, True, throttle_sleep_duration
        return current_count, False, 0


def _parse_api_keys(raw_value: Optional[str]) -> Sequence[str]:
    if not raw_value:
        return []
    potential_parts = re.split(r"[\s,;]+", raw_value)
    keys = [part.strip() for part in potential_parts if part and part.strip()]
    deduped = []
    for key in keys:
        if key not in deduped:
            deduped.append(key)
    return deduped


def _collect_gemini_api_keys(core) -> Sequence[str]:
    settings_value = _get_setting(core, "subtitlecat_gemini_api_keys", "") or ""
    env_keys = os.getenv("SUBTITLECAT_GEMINI_API_KEYS") or os.getenv(
        "SUBTITLECAT_GEMINI_API_KEY", ""
    )
    combined = list(_parse_api_keys(settings_value))
    for env_key in _parse_api_keys(env_keys):
        if env_key not in combined:
            combined.append(env_key)
    return combined


def _build_translator_config(core) -> TranslatorConfig:
    api_keys = _collect_gemini_api_keys(core)
    if not api_keys:
        raise TranslationError("No Gemini API keys configured")
    model = (
        _get_setting(core, "subtitlecat_gemini_model", "gemini-2.5-flash")
        or "gemini-2.5-flash"
    )
    retry_count = int(_get_setting(core, "subtitlecat_gemini_retry_count", 3))
    retry_delay = float(_get_setting(core, "subtitlecat_gemini_retry_delay", 10.0))
    max_rounds = int(_get_setting(core, "subtitlecat_gemini_max_rounds", 3))
    round_wait = float(_get_setting(core, "subtitlecat_gemini_round_wait", 60.0))
    return TranslatorConfig(
        api_keys=tuple(api_keys),
        model=str(model).strip() or "gemini-2.5-flash",
        retry_count=max(0, retry_count),
        retry_delay=max(0.0, retry_delay),
        max_key_rounds=max(1, max_rounds),
        round_wait_base=max(0.0, round_wait),
    )


def _get_gemini_translator(core, service_name):
    if GeminiSubtitleTranslator is None or TranslatorConfig is None:
        raise TranslationError(
            "Gemini translator dependencies are unavailable. Install google-genai to enable translations."
        )
    config = _build_translator_config(core)
    with _TRANSLATOR_CACHE_LOCK:
        translator = _TRANSLATOR_CACHE.get(config)
        if translator is None:
            logger = getattr(core, "logger", None)
            translator = GeminiSubtitleTranslator(config, logger=logger)
            _TRANSLATOR_CACHE[config] = translator
    return translator


def _resolve_target_language_label(target_lang: str) -> str:
    if not target_lang:
        return ""
    lowered = target_lang.strip().lower()
    if lowered in _TARGET_LANGUAGE_NAME_OVERRIDES:
        return _TARGET_LANGUAGE_NAME_OVERRIDES[lowered]
    return target_lang


def _translate_text_chunk(
    lines_to_translate, target_lang, core, service_name, recursion_depth=0
):
    if not lines_to_translate:
        return [], "auto"
    placeholder_str = _get_setting(
        core,
        "subtitlecat_translation_failed_placeholder",
        DEFAULT_TRANSLATION_FAILED_PLACEHOLDER,
    )
    if not any(line.strip() for line in lines_to_translate):
        return ["" for _ in lines_to_translate], "auto"

    try:
        translator = _get_gemini_translator(core, service_name)
    except TranslationError as exc:  # pragma: no cover - depends on runtime config
        if getattr(core, "logger", None):
            core.logger.error(f"[{service_name}] gemini: {exc}")
        return [
            placeholder_str if line.strip() else "" for line in lines_to_translate
        ], "auto"

    _, should_throttle, throttle_duration = _inc_gemini_counter_with_reset(
        core, service_name, "(BatchThrottle) "
    )
    if should_throttle and throttle_duration > 0:
        time.sleep(throttle_duration)

    target_language_label = _resolve_target_language_label(target_lang or "")

    try:
        translated_segments = translator.translate(
            list(lines_to_translate),
            target_language=target_language_label or target_lang,
            start_index=1,
        )
    except TranslationError as exc:  # pragma: no cover - network/SDK failure
        if getattr(core, "logger", None):
            core.logger.error(
                f"[{service_name}] gemini: Translation error for target '{target_lang}': {exc}"
            )
        translated_segments = [None] * len(lines_to_translate)
    except Exception as exc:  # pragma: no cover - defensive catch-all
        if getattr(core, "logger", None):
            core.logger.error(
                f"[{service_name}] gemini: Unexpected error for target '{target_lang}': {exc}"
            )
        translated_segments = [None] * len(lines_to_translate)

    if len(translated_segments) != len(lines_to_translate):
        if getattr(core, "logger", None):
            core.logger.error(
                f"[{service_name}] gemini: Output count mismatch. Expected {len(lines_to_translate)}, received {len(translated_segments)}"
            )
        corrected = []
        for idx in range(len(lines_to_translate)):
            translated = (
                translated_segments[idx] if idx < len(translated_segments) else None
            )
            corrected.append(translated)
        translated_segments = corrected

    sanitized_segments = []
    for original_line, translated_line in zip(lines_to_translate, translated_segments):
        if translated_line:
            sanitized_segments.append(translated_line)
        else:
            sanitized_segments.append(placeholder_str if original_line.strip() else "")

    return sanitized_segments, "auto"


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
        timeout if timeout is not None else _get_setting(core, "http_timeout", 15)
    )

    def _handle_rate_limited(status_code: int) -> None:
        if getattr(core, "logger", None):
            core.logger.warning(
                f"[{service_name}] Warm-up request returned HTTP {status_code} for {translation_url}."
            )
        if status_code == 403:
            message = (
                "Subtitlecat blocked the request (HTTP 403). Please try again later."
            )
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
