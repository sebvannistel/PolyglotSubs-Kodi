"""Gemini powered subtitle translation helpers.

The implementation is adapted from the open source SubtitleCAT project
(https://github.com/TestersNightmare/SubtitleCAT) and keeps the same
high-level behaviour: build numbered prompts, route requests through a
pool of Gemini API keys, and parse the indexed response back into the
original ordering.

Only the non-GUI translation pieces are included here so that the Kodi
addon can depend on a pure-Python module without bundling Tkinter assets.
"""

from __future__ import annotations

import re
import threading
import time
from dataclasses import dataclass
from typing import Callable, Dict, Iterable, List, Optional, Sequence

try:  # pragma: no cover - import guarded for environments without google-genai
    from google import genai  # type: ignore
except ImportError:  # pragma: no cover - exercised in unit tests
    genai = None


class TranslationError(RuntimeError):
    """Raised when the Gemini API cannot return a usable translation."""


@dataclass(frozen=True)
class TranslatorConfig:
    """Runtime configuration for :class:`GeminiSubtitleTranslator`."""

    api_keys: Sequence[str]
    model: str = "gemini-2.5-flash"
    retry_count: int = 3
    retry_delay: float = 10.0
    max_key_rounds: int = 3
    round_wait_base: float = 60.0

    def __post_init__(self) -> None:
        if not self.api_keys:
            raise ValueError("api_keys must not be empty")


class GeminiSubtitleTranslator:
    """Translate subtitle lines using Google Gemini."""

    def __init__(
        self,
        config: TranslatorConfig,
        *,
        logger: Optional[object] = None,
        sleep: Callable[[float], None] = time.sleep,
    ) -> None:
        self._config = config
        self._logger = logger
        self._sleep = sleep
        self._local = threading.local()

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------
    def _ensure_local_state(self) -> None:
        if not hasattr(self._local, "current_index"):
            self._local.current_index = 0
            self._local.round_count = 0
            self._local.client = None
            self._local.active_key = None

    def _log(self, level: str, message: str) -> None:
        logger = self._logger
        if logger is None:
            return
        log_method = getattr(logger, level, None)
        if callable(log_method):
            try:
                log_method(message)
            except Exception:  # pragma: no cover - defensive logging
                pass

    def _current_key(self) -> str:
        self._ensure_local_state()
        return self._config.api_keys[self._local.current_index]

    def _get_client(self):
        if genai is None:
            raise TranslationError(
                "google-genai is not installed. Install the 'google-genai' package to "
                "enable Gemini translations."
            )
        self._ensure_local_state()
        api_key = self._current_key()
        if self._local.client is None or self._local.active_key != api_key:
            self._log(
                "debug",
                f"[subtitlecat] Initialising Gemini client for key index {self._local.current_index}",
            )
            self._local.client = genai.Client(api_key=api_key)
            self._local.active_key = api_key
        return self._local.client

    def _switch_key(self, reason: str) -> bool:
        self._ensure_local_state()
        self._local.current_index += 1
        if self._local.current_index >= len(self._config.api_keys):
            self._local.round_count += 1
            if self._local.round_count >= self._config.max_key_rounds:
                return False
            self._local.current_index = 0
            wait_time = self._config.round_wait_base * self._local.round_count
            if wait_time > 0:
                self._log(
                    "warning",
                    f"[subtitlecat] Rotating Gemini API keys after {reason}. Waiting {wait_time}s before retrying.",
                )
                try:
                    self._sleep(wait_time)
                except Exception:  # pragma: no cover - defensive sleep wrapper
                    pass
        self._local.client = None
        self._local.active_key = None
        self._log(
            "info",
            f"[subtitlecat] Switching to Gemini API key index {self._local.current_index} due to {reason}",
        )
        return True

    @staticmethod
    def _is_fatal_error(exc: Exception) -> bool:
        message = str(exc).lower()
        if "invalid api key" in message:
            return True
        if "permission" in message and "403" in message:
            return True
        return False

    @staticmethod
    def _retry_delay_from_error(exc: Exception) -> Optional[float]:
        error_obj = getattr(exc, "error", None)
        if isinstance(error_obj, dict):
            if error_obj.get("code") == 429:
                details = error_obj.get("details") or []
                for detail in details:
                    if not isinstance(detail, dict):
                        continue
                    retry_delay = detail.get("retryDelay")
                    if isinstance(retry_delay, str):
                        match = re.search(r"(\d+)", retry_delay)
                        if match:
                            return float(match.group(1)) + 1.0
        return None

    def _safe_generate_content(self, prompt: str) -> str:
        self._ensure_local_state()
        attempts = 0
        last_error: Optional[Exception] = None

        while self._local.round_count < self._config.max_key_rounds:
            try:
                client = self._get_client()
                response = client.models.generate_content(
                    model=self._config.model,
                    contents=prompt,
                )
                text = getattr(response, "text", None)
                if text:
                    return text
                # Some SDK versions expose candidates instead of text.
                candidates = getattr(response, "candidates", None)
                if candidates:
                    for candidate in candidates:
                        parts = getattr(candidate, "content", None)
                        if parts and getattr(parts, "parts", None):
                            combined = "".join(
                                getattr(part, "text", "") for part in parts.parts
                            )
                            if combined:
                                return combined
                return ""
            except Exception as exc:  # pragma: no cover - network/SDK errors
                last_error = exc
                if self._is_fatal_error(exc):
                    if not self._switch_key("fatal Gemini error"):
                        break
                    attempts = 0
                    continue
                attempts += 1
                retry_delay = self._retry_delay_from_error(exc)
                if retry_delay is None:
                    retry_delay = self._config.retry_delay
                if attempts <= self._config.retry_count:
                    if retry_delay > 0:
                        self._log(
                            "warning",
                            f"[subtitlecat] Gemini request failed ({exc}); retrying in {retry_delay}s",
                        )
                        try:
                            self._sleep(retry_delay)
                        except Exception:
                            pass
                    continue
                if not self._switch_key("retry budget exhausted"):
                    break
                attempts = 0

        raise TranslationError("Gemini translation failed") from last_error

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------
    def translate(
        self,
        texts: Sequence[str],
        *,
        target_language: str,
        start_index: int = 1,
    ) -> List[Optional[str]]:
        if not texts:
            return []
        numbered_inputs = [
            f"{start_index + idx}|||{text}" for idx, text in enumerate(texts)
        ]
        prompt = self._build_prompt(numbered_inputs, target_language)
        response_text = self._safe_generate_content(prompt)
        mapping = parse_indexed_response(response_text)
        results: List[Optional[str]] = []
        for offset, _ in enumerate(texts):
            lookup_index = start_index + offset
            translated = mapping.get(lookup_index)
            if translated is None:
                results.append(None)
            else:
                results.append(translated.replace("\n", " ").strip())
        return results

    @staticmethod
    def _build_prompt(numbered_inputs: Sequence[str], target_language: str) -> str:
        rules = (
            f"You are a professional subtitle translator. Translate the following "
            f"subtitle lines into {target_language}.\n"
            "Each input line is formatted as: Index|||Original text\n"
            "Return one line per input using the format: Index|||Translated text\n\n"
            "Rules:\n"
            "1. Do not change, skip, or re-order indices.\n"
            "2. Preserve the number of lines – one output per input.\n"
            "3. Keep translations concise (similar length, +/- 30%).\n"
            "4. If a line cannot be translated, return `Index|||`.\n"
            "5. Do not add annotations or explanations.\n\n"
        )
        example = (
            "Example:\n"
            "Input:\n"
            "1|||This is an example line\n"
            "2|||It should stay on one line\n\n"
            "Output:\n"
            "1|||Esto es una línea de ejemplo\n"
            "2|||Debe mantenerse en una línea\n\n"
        )
        return rules + example + "\n".join(numbered_inputs)


def parse_indexed_response(resp_text: Optional[str]) -> Dict[int, str]:
    if not resp_text:
        return {}
    mapping: Dict[int, str] = {}
    for raw_line in resp_text.splitlines():
        line = raw_line.strip()
        if not line:
            continue
        if "|||" in line:
            index_part, content = line.split("|||", 1)
        else:
            match = re.match(r"^(\d+)[\.\)\:,-]?\s+(.*)$", line)
            if not match:
                continue
            index_part, content = match.group(1), match.group(2)
        index_match = re.search(r"(\d+)", index_part)
        if not index_match:
            continue
        idx = int(index_match.group(1))
        mapping[idx] = content.strip()
    return mapping


__all__ = [
    "GeminiSubtitleTranslator",
    "TranslationError",
    "TranslatorConfig",
    "parse_indexed_response",
]
