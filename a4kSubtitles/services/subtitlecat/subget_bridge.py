"""Bridge for invoking the subget command line helper."""

from __future__ import annotations

import json
import os
import shutil
import subprocess
import sys
from pathlib import Path
from typing import Any, Dict, Iterable, List, Optional, Sequence
from urllib.parse import unquote, urljoin

from .translation import _TRANSLATED_CACHE
from .utils import (
    KODI_REGIONAL_LANG_MAP,
    SC_BASE_URL,
    _get_setting,
    _is_title_close,
    _post_download_fix_encoding,
)


class SubgetError(RuntimeError):
    """Base error for the Subget bridge."""


class SubgetNotAvailableError(SubgetError):
    """Raised when the helper binary cannot be located."""


class SubgetExecutionError(SubgetError):
    """Raised when the helper returns an error payload."""


_ENV_OVERRIDE_KEYS = (
    "A4KSUBTITLES_SUBGET_PATH",
    "A4KSUBS_SUBGET_PATH",
)


def _addon_root() -> Path:
    return Path(__file__).resolve().parents[3]


def _platform_folder() -> str:
    if os.environ.get("ANDROID_DATA") and os.environ.get("ANDROID_ROOT"):
        return "android"
    if sys.platform.startswith("linux"):
        return "linux"
    if sys.platform == "darwin":
        return "macos"
    if sys.platform.startswith("win"):
        return "windows"
    return "linux"


def _candidate_names() -> Sequence[str]:
    if _platform_folder() == "windows":
        return ("subget.exe", "subget.bat", "subget")
    return ("subget",)


def _candidate_paths(core: Any) -> Iterable[Path]:
    seen: set[Path] = set()
    for key in _ENV_OVERRIDE_KEYS:
        value = os.environ.get(key)
        if value:
            candidate = Path(value)
            if candidate not in seen:
                seen.add(candidate)
                yield candidate

    configured = _get_setting(core, "subtitlecat_subget_path", "")
    if configured:
        candidate = Path(configured)
        if candidate not in seen:
            seen.add(candidate)
            yield candidate

    platform_dir = _addon_root() / "resources" / "bin" / _platform_folder()
    for name in _candidate_names():
        candidate = platform_dir / name
        if candidate not in seen:
            seen.add(candidate)
            yield candidate

    which_path = shutil.which("subget")
    if which_path:
        candidate = Path(which_path)
        if candidate not in seen:
            seen.add(candidate)
            yield candidate


def _resolve_binary(core: Any) -> Optional[Path]:
    for candidate in _candidate_paths(core):
        if candidate.exists():
            return candidate
    return None


def is_available(core: Any) -> bool:
    return _resolve_binary(core) is not None


def _subprocess_timeout(core: Any, multiplier: int = 2, minimum: int = 30) -> int:
    try:
        configured = int(_get_setting(core, "http_timeout", 15))
    except (TypeError, ValueError):
        configured = 15
    return max(minimum, configured * multiplier)


def _run_subget(
    core: Any,
    args: Sequence[str],
    *,
    capture_output: bool = True,
    text: bool = True,
    timeout: Optional[int] = None,
) -> subprocess.CompletedProcess[str]:
    binary = _resolve_binary(core)
    if not binary:
        raise SubgetNotAvailableError("subget helper binary not found")

    command = [str(binary), *args]
    timeout = timeout or _subprocess_timeout(core)
    try:
        return subprocess.run(
            command,
            capture_output=capture_output,
            text=text,
            check=False,
            timeout=timeout,
        )
    except subprocess.TimeoutExpired as exc:
        raise SubgetExecutionError(
            f"subget helper timed out after {timeout}s: {' '.join(command)}"
        ) from exc


def _base_name(name: str) -> str:
    import re

    return re.split(r"[ (]", name, 1)[0].lower()


def _normalize_language(core: Any, sc_lang_code: str, sc_lang_name: str) -> tuple[str, str]:
    kodi_target_lang_full = sc_lang_name or sc_lang_code
    kodi_target_lang_iso2 = sc_lang_code.split("-")[0].lower()

    sc_lang_code_lower = sc_lang_code.lower()
    if sc_lang_code_lower.startswith("zh-"):
        kodi_target_lang_full = "Chinese"
        kodi_target_lang_iso2 = "zh"
    elif sc_lang_code_lower in KODI_REGIONAL_LANG_MAP:
        map_full_name, map_iso_code = KODI_REGIONAL_LANG_MAP[sc_lang_code_lower]
        kodi_target_lang_full = map_full_name
        kodi_target_lang_iso2 = map_iso_code
    else:
        try:
            converted_full_name = core.utils.get_lang_id(
                sc_lang_code, core.kodi.xbmc.ENGLISH_NAME
            )
            if converted_full_name:
                kodi_target_lang_full = converted_full_name
            converted_iso2 = core.utils.get_lang_id(
                kodi_target_lang_full, core.kodi.xbmc.ISO_639_1
            )
            if converted_iso2:
                kodi_target_lang_iso2 = converted_iso2.lower()
        except Exception:
            pass

    return kodi_target_lang_full, kodi_target_lang_iso2


def _display_name_for_service(core: Any, service_name: str) -> str:
    service_obj = None
    if getattr(core, "services", None):
        service_obj = core.services.get(service_name)
    if service_obj:
        return getattr(service_obj, "display_name", service_name)
    return service_name


def _build_query_from_meta(meta: Any) -> str:
    if not meta:
        return ""
    query_title = (
        getattr(meta, "tvshow", None)
        if getattr(meta, "is_tvshow", False)
        else getattr(meta, "title", None)
    )
    if not query_title:
        return ""
    parts: List[str] = [str(query_title)]
    meta_year = getattr(meta, "year", None)
    if meta_year:
        parts.append(str(meta_year))
    return " ".join(parts)


def _construct_filename(detail_href: str, sc_lang_code: str) -> str:
    filename_parts = detail_href.split("/")
    filename_base = (
        unquote(filename_parts[-1]).replace(".html", "")
        if filename_parts
        else "subtitle"
    )
    original_id = filename_parts[-2] if len(filename_parts) > 1 else "id"
    return f"{original_id}-{filename_base}-{sc_lang_code}.srt"


def _convert_items_to_results(
    core: Any,
    service_name: str,
    meta: Any,
    items: Iterable[Dict[str, Any]],
) -> List[Dict[str, Any]]:
    results: List[Dict[str, Any]] = []
    display_name = _display_name_for_service(core, service_name)

    wanted_languages_lower = {
        str(lang).lower()
        for lang in getattr(meta, "languages", [])
        if isinstance(lang, str) and lang
    }
    wanted_iso2 = {
        core.utils.get_lang_id(language, core.kodi.xbmc.ISO_639_1).lower()
        for language in getattr(meta, "languages", [])
        if language
        and core.utils.get_lang_id(language, core.kodi.xbmc.ISO_639_1)
    }
    allow_any_language = not wanted_languages_lower and not wanted_iso2

    meta_title = getattr(meta, "title", "") or ""

    for item in items:
        movie_title = item.get("title") or "Unknown Title"
        if meta_title and not _is_title_close(meta_title, movie_title):
            continue

        detail_href = item.get("href") or item.get("detail") or ""
        if not detail_href:
            continue
        detail_url = urljoin(SC_BASE_URL, detail_href)

        languages = item.get("languages") or []
        for language_entry in languages:
            sc_lang_code = language_entry.get("code")
            if not sc_lang_code:
                continue
            sc_lang_name = language_entry.get("name") or sc_lang_code

            kodi_lang_full, kodi_lang_iso2 = _normalize_language(
                core, sc_lang_code, sc_lang_name
            )

            if not allow_any_language:
                if (
                    _base_name(kodi_lang_full) not in wanted_languages_lower
                    and kodi_lang_iso2 not in wanted_iso2
                ):
                    continue

            constructed_filename = language_entry.get("filename") or _construct_filename(
                detail_href, sc_lang_code
            )

            action_args: Dict[str, Any] = {
                "url": "",
                "lang": kodi_lang_full,
                "filename": constructed_filename,
                "gzip": False,
                "service_name": service_name,
                "detail_url": detail_url,
                "lang_code": sc_lang_code,
                "needs_poll": False,
                "needs_client_side_translation": False,
                "subget": True,
            }

            item_color = language_entry.get("color", "white")

            download_href = language_entry.get("download")
            if download_href:
                action_args["url"] = urljoin(SC_BASE_URL, download_href)

            translated_download = language_entry.get("translatedDownload")
            if translated_download:
                translated_url = urljoin(SC_BASE_URL, translated_download)
                action_args["url"] = translated_url
                cache_key_lang = language_entry.get("cacheLangKey") or kodi_lang_iso2
                if cache_key_lang:
                    _TRANSLATED_CACHE[(detail_url, cache_key_lang.lower())] = translated_url

            if language_entry.get("needsClientTranslation"):
                action_args.update(
                    {
                        "needs_client_side_translation": True,
                        "original_srt_url": urljoin(
                            SC_BASE_URL, language_entry.get("original") or ""
                        ),
                        "target_translation_lang": language_entry.get("target")
                        or sc_lang_code,
                    }
                )
                item_color = "yellow"

            if language_entry.get("shared"):
                item_color = "cyan"

            results.append(
                {
                    "service_name": service_name,
                    "service": display_name,
                    "lang": kodi_lang_full,
                    "name": f"{movie_title} ({sc_lang_name})",
                    "rating": 0,
                    "lang_code": kodi_lang_iso2,
                    "sync": "false",
                    "impaired": "false",
                    "color": item_color,
                    "action_args": action_args,
                }
            )

    return results


def search(core: Any, service_name: str, meta: Any) -> List[Dict[str, Any]]:
    query = _build_query_from_meta(meta)
    if not query:
        return []

    timeout = _subprocess_timeout(core, multiplier=3, minimum=30)
    completed = _run_subget(core, ["--json-search", query], timeout=timeout)

    stdout = (completed.stdout or "").strip()
    if completed.returncode != 0:
        message = completed.stderr.strip() if completed.stderr else stdout
        raise SubgetExecutionError(
            f"subget search failed (exit {completed.returncode}): {message or 'no output'}"
        )

    if not stdout:
        raise SubgetExecutionError("subget search returned empty stdout")

    try:
        payload = json.loads(stdout)
    except json.JSONDecodeError as exc:
        raise SubgetExecutionError(
            f"subget search returned invalid JSON: {exc}: {stdout[:2000]}"
        ) from exc

    if not payload:
        return []
    if payload.get("ok") is False:
        raise SubgetExecutionError(payload.get("error", "unknown subget error"))

    items = payload.get("items") or []
    return _convert_items_to_results(core, service_name, meta, items)


def download(
    core: Any,
    service_name: str,
    detail_url: str,
    lang_code: str,
    outfile: str,
    filename_hint: Optional[str] = None,
) -> bool:
    if not detail_url or not lang_code:
        raise ValueError("detail_url and lang_code are required")

    timeout = _subprocess_timeout(core, multiplier=2, minimum=30)
    completed = _run_subget(
        core,
        ["--download", detail_url, "--lang", lang_code, "--stdout"],
        timeout=timeout,
        text=False,
    )

    if completed.returncode != 0:
        message = (completed.stderr or b"").decode("utf-8", "replace").strip()
        raise SubgetExecutionError(
            f"subget download failed (exit {completed.returncode}): {message or 'no output'}"
        )

    raw_bytes = completed.stdout or b""
    if not raw_bytes:
        raise SubgetExecutionError("subget download produced no data")

    if getattr(core, "logger", None):
        core.logger.debug(
            f"[{service_name}] Subget download received {len(raw_bytes)} bytes"
            f" for {detail_url} ({lang_code})."
        )

    _post_download_fix_encoding(core, service_name, raw_bytes, outfile)
    return True
