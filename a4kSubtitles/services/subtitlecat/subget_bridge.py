"""Utilities for invoking the external subget helper."""
from __future__ import annotations

import json
import os
import subprocess
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Dict, Iterable, List, Optional

from .utils import _get_setting, _post_download_fix_encoding


@dataclass
class BridgeSearchOutcome:
    """Represents the result of a subget search invocation."""

    used_bridge: bool
    results: List[Dict[str, Any]]
    status_code: int
    stdout: str = ""
    stderr: str = ""


class SubgetBridgeError(RuntimeError):
    """Raised when the subget helper fails in a non-recoverable way."""

    def __init__(self, message: str, *, returncode: Optional[int] = None):
        super().__init__(message)
        self.returncode = returncode


def _addon_root() -> Path:
    return Path(__file__).resolve().parents[3].parent


def _detect_platform(core) -> str:
    kodi = getattr(core, "kodi", None)
    xbmc = getattr(kodi, "xbmc", None)
    cond_visibility = getattr(xbmc, "getCondVisibility", None)
    if callable(cond_visibility):  # pragma: no branch - best effort detection
        if cond_visibility("system.platform.android"):
            return "android"
        if cond_visibility("system.platform.windows"):
            return "windows"
        if cond_visibility("system.platform.osx"):
            return "darwin"
        if cond_visibility("system.platform.linux"):
            return "linux"

    platform = sys.platform
    if platform.startswith("win"):
        return "windows"
    if platform == "darwin":
        return "darwin"
    if platform.startswith("linux"):
        if os.environ.get("ANDROID_ROOT"):
            return "android"
        return "linux"
    return "linux"


def _candidate_paths(core) -> Iterable[Path]:
    override = (_get_setting(core, "subtitlecat_subget_path_override", "") or "").strip()
    if override:
        yield Path(override)

    platform_name = _detect_platform(core)
    bin_dir = _addon_root() / "resources" / "bin" / platform_name
    yield bin_dir / "subget"
    yield bin_dir / "subget.py"
    yield bin_dir / "subget.exe"


def _resolve_binary(core) -> Optional[Path]:
    for path in _candidate_paths(core):
        if path.is_file() and os.access(path, os.X_OK):
            return path
    return None


def is_available(core) -> bool:
    """Return True if a usable subget helper is available."""

    binary = _resolve_binary(core)
    return binary is not None


def _build_search_command(binary: Path, meta) -> List[str]:
    cmd: List[str] = [str(binary), "--json-search"]

    title = getattr(meta, "title", "") or ""
    if title:
        cmd.extend(["--title", title])

    tvshow = getattr(meta, "tvshow", "") or ""
    if tvshow:
        cmd.extend(["--tvshow", tvshow])

    if getattr(meta, "is_tvshow", False):
        season = getattr(meta, "season", None)
        episode = getattr(meta, "episode", None)
        if season is not None:
            cmd.extend(["--season", str(season)])
        if episode is not None:
            cmd.extend(["--episode", str(episode)])

    year = getattr(meta, "year", None)
    if year:
        cmd.extend(["--year", str(year)])

    imdb_id = getattr(meta, "imdb_id", "") or ""
    if imdb_id:
        cmd.extend(["--imdb-id", imdb_id])

    for lang in getattr(meta, "languages", []) or []:
        if lang:
            cmd.extend(["--lang", lang])

    return cmd


def search(core, meta) -> BridgeSearchOutcome:
    """Run a search through the external helper."""

    binary = _resolve_binary(core)
    if not binary:
        return BridgeSearchOutcome(False, [], 0, stderr="subget helper not found")

    cmd = _build_search_command(binary, meta)
    try:
        completed = subprocess.run(
            cmd,
            capture_output=True,
            text=True,
            check=False,
        )
    except FileNotFoundError as exc:  # pragma: no cover - defensive
        return BridgeSearchOutcome(False, [], 0, stderr=str(exc))
    except OSError as exc:  # pragma: no cover - defensive
        raise SubgetBridgeError(
            f"Failed to execute subget helper: {exc}", returncode=getattr(exc, "errno", None)
        ) from exc

    stdout = completed.stdout or ""
    stderr = completed.stderr or ""
    status = completed.returncode

    if status != 0:
        return BridgeSearchOutcome(True, [], status, stdout=stdout, stderr=stderr)

    try:
        payload = json.loads(stdout or "[]")
    except json.JSONDecodeError as exc:
        raise SubgetBridgeError(
            f"Invalid JSON returned by subget helper: {exc}" , returncode=status
        ) from exc

    if not isinstance(payload, list):
        raise SubgetBridgeError(
            "Expected a JSON array from subget helper", returncode=status
        )

    return BridgeSearchOutcome(True, payload, status, stdout=stdout, stderr=stderr)


def download(core, service_name: str, bridge_payload: Dict[str, Any], target_path: str) -> bool:
    """Download subtitle bytes through the helper and post-process them."""

    binary = _resolve_binary(core)
    if not binary:
        raise SubgetBridgeError("subget helper is not available")

    args = list(bridge_payload.get("args", []))
    if not args and bridge_payload.get("download_id"):
        args.extend(["--download", str(bridge_payload["download_id"])])
    if bridge_payload.get("lang"):
        args.extend(["--lang", str(bridge_payload["lang"])])
    if "--stdout" not in args:
        args.append("--stdout")

    cmd = [str(binary)] + args

    env = os.environ.copy()
    extra_env = bridge_payload.get("env") or {}
    env.update({str(k): str(v) for k, v in extra_env.items()})

    try:
        completed = subprocess.run(
            cmd,
            capture_output=True,
            check=False,
            env=env,
        )
    except FileNotFoundError as exc:  # pragma: no cover - defensive
        raise SubgetBridgeError(str(exc)) from exc
    except OSError as exc:  # pragma: no cover - defensive
        raise SubgetBridgeError(
            f"Failed to execute subget helper: {exc}", returncode=getattr(exc, "errno", None)
        ) from exc

    if completed.returncode != 0:
        raise SubgetBridgeError(
            f"subget helper exited with {completed.returncode}: {completed.stderr.decode(errors='ignore')}",
            returncode=completed.returncode,
        )

    raw_bytes = completed.stdout
    if raw_bytes is None:
        raw_bytes = b""

    if isinstance(raw_bytes, str):
        raw_bytes = raw_bytes.encode("utf-8", errors="ignore")

    _post_download_fix_encoding(core, service_name, raw_bytes, target_path)
    return True
