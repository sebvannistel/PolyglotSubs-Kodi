"""Utilities for invoking the vendored headless Subtitlecat helper."""

from __future__ import annotations

import base64
import json
import os
import shlex
import shutil
import subprocess
from pathlib import Path
from typing import Any, Dict, Iterable, List, Optional, Sequence, Tuple
from urllib.parse import unquote, urljoin

from .utils import (
    KODI_REGIONAL_LANG_MAP,
    SC_BASE_URL,
    _get_setting,
    _is_title_close,
    _post_download_fix_encoding,
)

_NODE_SETTING_KEY = "subtitlecat.node_path"


def _headless_script_path() -> Path:
    return Path(__file__).resolve().parents[3] / "resources" / "external" / "subtitlecat-headless" / "index.js"


def _get_node_executable(core: Any) -> str:
    configured = _get_setting(core, _NODE_SETTING_KEY, "")
    if configured:
        return configured.strip()
    return "node"


def _node_exists(executable: str) -> bool:
    if not executable:
        return False
    if os.path.isabs(executable) or os.sep in executable:
        return Path(executable).exists()
    return shutil.which(executable) is not None


def is_available(core: Any) -> bool:
    script_path = _headless_script_path()
    if not script_path.exists():
        return False
    return _node_exists(_get_node_executable(core))


def _subprocess_timeout(core: Any, multiplier: int = 2, minimum: int = 20) -> int:
    try:
        configured = int(_get_setting(core, "http_timeout", 15))
    except (TypeError, ValueError):
        configured = 15
    return max(minimum, configured * multiplier)


def _run_node(core: Any, args: Sequence[str], timeout: Optional[int] = None) -> Optional[subprocess.CompletedProcess[str]]:
    script_path = _headless_script_path()
    node_exec = _get_node_executable(core)

    if not script_path.exists():
        if core and getattr(core, "logger", None):
            core.logger.debug("[subtitlecat] Headless helper script missing: %s", script_path)
        return None

    if not _node_exists(node_exec):
        if core and getattr(core, "logger", None):
            core.logger.debug("[subtitlecat] Node executable not found: %s", node_exec)
        return None

    command: List[str] = [node_exec, str(script_path), *args]
    try:
        completed = subprocess.run(
            command,
            capture_output=True,
            text=True,
            timeout=timeout,
            check=False,
        )
        return completed
    except subprocess.TimeoutExpired:
        if core and getattr(core, "logger", None):
            core.logger.error(
                "[subtitlecat] Headless helper timed out after %ss for command: %s",
                timeout,
                shlex.join(command),
            )
        return None
    except FileNotFoundError:
        if core and getattr(core, "logger", None):
            core.logger.error("[subtitlecat] Node executable missing: %s", node_exec)
        return None


def _base_name(name: str) -> str:
    import re

    return re.split(r"[ (]", name, 1)[0].lower()


def _normalize_language(core: Any, sc_lang_code: str, sc_lang_name: str) -> Tuple[str, str]:
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


def _build_query_from_meta(meta: Any) -> str:
    if not meta:
        return ""
    query_title = getattr(meta, "tvshow", None) if getattr(meta, "is_tvshow", False) else getattr(meta, "title", None)
    if not query_title:
        return ""
    parts: List[str] = [str(query_title)]
    meta_year = getattr(meta, "year", None)
    if meta_year:
        parts.append(str(meta_year))
    return " ".join(parts)


def _display_name_for_service(core: Any, service_name: str) -> str:
    if core and getattr(core, "services", None) and hasattr(core.services, "get"):
        service_obj = core.services.get(service_name)
        if service_obj:
            return getattr(service_obj, "display_name", service_name)
    return service_name


def _convert_node_items_to_results(
    core: Any,
    service_name: str,
    meta: Any,
    node_items: Iterable[Dict[str, Any]],
) -> List[Dict[str, Any]]:
    results: List[Dict[str, Any]] = []
    display_name_for_service = _display_name_for_service(core, service_name)

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

    for item in node_items:
        movie_title = item.get("title") or "Unknown Title"
        if meta_title and not _is_title_close(meta_title, movie_title):
            continue

        href = item.get("href") or ""
        if not href:
            continue
        try:
            filename_parts = href.split("/")
            filename_base = unquote(filename_parts[-1]).replace(".html", "") if filename_parts else "subtitle"
            original_id = filename_parts[-2] if len(filename_parts) > 1 else "id"
        except Exception:
            filename_base = "subtitle"
            original_id = "id"

        detail_url = item.get("detailUrl") or urljoin(SC_BASE_URL, href)
        languages = item.get("languages") or []
        if item.get("warning") and core and getattr(core, "logger", None):
            core.logger.warning(
                "[subtitlecat] Headless helper warning for %s: %s",
                detail_url,
                item["warning"],
            )

        for language_entry in languages:
            sc_lang_code = language_entry.get("code")
            if not sc_lang_code:
                continue
            sc_lang_name = language_entry.get("name") or sc_lang_code
            kodi_lang_full, kodi_lang_iso2 = _normalize_language(core, sc_lang_code, sc_lang_name)

            if not allow_any_language:
                if (
                    _base_name(kodi_lang_full) not in wanted_languages_lower
                    and kodi_lang_iso2 not in wanted_iso2
                ):
                    continue

            constructed_filename = f"{original_id}-{filename_base}-{sc_lang_code}.srt"
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
            }
            item_color = "white"

            download_href = language_entry.get("downloadHref")
            translate_args = language_entry.get("translateArgs")

            if download_href:
                action_args["url"] = urljoin(SC_BASE_URL, download_href)
            elif translate_args:
                folder = translate_args.get("folder") or f"/subs/{original_id}/"
                if not folder.startswith("/"):
                    folder = "/" + folder
                if not folder.endswith("/"):
                    folder = folder + "/"
                source_file = translate_args.get("sourceFile") or f"{filename_base}-orig.srt"
                source_url = urljoin(SC_BASE_URL, folder + source_file)
                target_translation_lang = translate_args.get("target") or sc_lang_code
                action_args.update(
                    {
                        "needs_client_side_translation": True,
                        "original_srt_url": source_url,
                        "target_translation_lang": target_translation_lang,
                    }
                )
                item_color = "yellow"
            else:
                continue

            results.append(
                {
                    "service_name": service_name,
                    "service": display_name_for_service,
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
    """Run the headless bridge search and convert results for Kodi."""

    query = _build_query_from_meta(meta)
    if not query:
        if core and getattr(core, "logger", None):
            core.logger.debug(
                f"[{service_name}] Headless bridge search aborted: empty query constructed from metadata."
            )
        return []

    timeout = _subprocess_timeout(core, multiplier=3, minimum=30)
    completed = _run_node(core, ["search", query], timeout=timeout)
    if completed is None:
        return []

    stdout = (completed.stdout or "").strip()
    if not stdout:
        if core and getattr(core, "logger", None):
            core.logger.error(
                f"[{service_name}] Headless bridge search returned empty stdout. Stderr: {completed.stderr}"
            )
        return []

    try:
        payload = json.loads(stdout)
    except json.JSONDecodeError as err:
        if core and getattr(core, "logger", None):
            core.logger.error(
                f"[{service_name}] Failed to decode headless search JSON: {err}. Raw: {stdout[:2000]}"
            )
        return []

    if not payload.get("ok", False):
        if core and getattr(core, "logger", None):
            core.logger.error(
                f"[{service_name}] Headless bridge search error: {payload.get('error', 'unknown error')}"
            )
        return []

    items = payload.get("items") or []
    converted = _convert_node_items_to_results(core, service_name, meta, items)
    if core and getattr(core, "logger", None):
        core.logger.debug(
            f"[{service_name}] Headless bridge produced {len(converted)} converted results from {len(items)} raw items."
        )
    return converted


def download(
    core: Any,
    service_name: str,
    detail_url: str,
    lang_code: str,
    outfile: str,
    filename_hint: Optional[str] = None,
) -> bool:
    """Download subtitles via the headless helper and write them through the encoding fixer."""

    if not outfile:
        raise ValueError("outfile is required for headless download")

    timeout = _subprocess_timeout(core, multiplier=2, minimum=25)
    completed = _run_node(core, ["download", detail_url, lang_code], timeout=timeout)
    if completed is None:
        return False

    stdout = (completed.stdout or "").strip()
    if not stdout:
        if core and getattr(core, "logger", None):
            core.logger.error(
                f"[{service_name}] Headless bridge download returned empty stdout. Stderr: {completed.stderr}"
            )
        return False

    try:
        payload = json.loads(stdout)
    except json.JSONDecodeError as err:
        if core and getattr(core, "logger", None):
            core.logger.error(
                f"[{service_name}] Failed to decode headless download JSON: {err}. Raw: {stdout[:2000]}"
            )
        return False

    if not payload.get("ok", False):
        if core and getattr(core, "logger", None):
            core.logger.error(
                f"[{service_name}] Headless bridge download error: {payload.get('error', 'unknown error')}"
            )
        return False

    data_b64 = payload.get("data")
    if not data_b64:
        if core and getattr(core, "logger", None):
            core.logger.error(
                f"[{service_name}] Headless bridge download payload missing data field."
            )
        return False

    try:
        raw_bytes = base64.b64decode(data_b64)
    except (ValueError, TypeError) as err:
        if core and getattr(core, "logger", None):
            core.logger.error(
                f"[{service_name}] Failed to decode base64 payload from headless download: {err}"
            )
        return False

    if core and getattr(core, "logger", None):
        core.logger.debug(
            f"[{service_name}] Headless bridge download received {len(raw_bytes)} bytes (filename hint: {filename_hint})."
        )

    _post_download_fix_encoding(core, service_name, raw_bytes, outfile)
    return True
