"""Gemini translation helpers extracted from SubtitleCAT."""

from __future__ import annotations

import re
import threading
import time
from dataclasses import dataclass
from typing import Callable, List, Optional, Sequence

from google import genai


class GeminiTranslationError(RuntimeError):
    """Raised when the Gemini translator cannot fulfil a request."""


@dataclass(frozen=True)
class _TranslatorConfig:
    api_keys: tuple[str, ...]
    model: str


class GeminiSubtitleTranslator:
    """Thread-safe Gemini client wrapper with key rotation and retries."""

    _MAX_KEY_ROUNDS = 3

    def __init__(
        self,
        api_keys: Sequence[str],
        *,
        model: str = "gemini-2.0-flash",
        max_retries: int = 3,
        sleep_on_retry: float = 5.0,
    ) -> None:
        keys = [key.strip() for key in api_keys if key and key.strip()]
        if not keys:
            raise GeminiTranslationError("No Gemini API keys configured")
        self._config = _TranslatorConfig(tuple(keys), model)
        self._max_retries = max(1, int(max_retries))
        self._sleep_on_retry = max(0.0, float(sleep_on_retry))
        self._thread_state = threading.local()

    # ------------------------------------------------------------------
    # Internal helpers
    def _get_state(self) -> dict[str, object]:
        state = getattr(self._thread_state, "value", None)
        if state is None:
            state = {
                "client": None,
                "index": 0,
                "round": 0,
            }
            self._thread_state.value = state
        return state

    def _current_key(self) -> str:
        state = self._get_state()
        index = state["index"]  # type: ignore[assignment]
        return self._config.api_keys[int(index)]

    def _ensure_client(self) -> genai.Client:
        state = self._get_state()
        client = state.get("client") if isinstance(state, dict) else None
        if client is None:
            client = genai.Client(api_key=self._current_key())
            state["client"] = client
        return client  # type: ignore[return-value]

    def _switch_key(self, log: Callable[[str], None]) -> None:
        state = self._get_state()
        idx = int(state["index"]) + 1
        if idx >= len(self._config.api_keys):
            idx = 0
            state["round"] = int(state.get("round", 0)) + 1
            if int(state["round"]) >= self._MAX_KEY_ROUNDS:
                raise GeminiTranslationError(
                    "Exhausted all configured Gemini API keys"
                )
        state["index"] = idx
        state["client"] = None
        key = self._current_key()
        log(
            "Switched Gemini API key to %s...%s"
            % (key[:6], key[-4:])
        )

    @staticmethod
    def _is_rate_limited(error: Exception) -> bool:
        message = str(error).lower()
        return "429" in message or "rate" in message

    @staticmethod
    def _is_service_unavailable(error: Exception) -> bool:
        message = str(error).lower()
        return "503" in message or "unavailable" in message

    @staticmethod
    def _is_invalid_key(error: Exception) -> bool:
        message = str(error).lower()
        return "invalid api key" in message or "403" in message

    @staticmethod
    def _extract_retry_delay(error: Exception) -> float:
        message = str(error)
        delay_match = re.search(r"(\d+)(?:\s*s)?", message)
        if delay_match:
            try:
                return max(1.0, float(delay_match.group(1)))
            except ValueError:
                pass
        return 10.0

    # ------------------------------------------------------------------
    def _call_api(
        self,
        prompt: str,
        *,
        log: Callable[[str], None],
        stop_flag: Optional[Callable[[], bool]] = None,
    ) -> str:
        state = self._get_state()
        state["round"] = 0
        last_error: Optional[Exception] = None
        while int(state.get("round", 0)) < self._MAX_KEY_ROUNDS:
            for attempt in range(self._max_retries):
                if stop_flag and stop_flag():
                    return ""
                try:
                    client = self._ensure_client()
                    response = client.models.generate_content(
                        model=self._config.model,
                        contents=prompt,
                    )
                    text = getattr(response, "text", None)
                    if not isinstance(text, str):
                        raise GeminiTranslationError("Gemini response missing text")
                    return text
                except Exception as error:  # pragma: no cover - best effort
                    last_error = error
                    message = str(error)
                    if self._is_invalid_key(error):
                        log(
                            "Gemini rejected the current API key (%s)"
                            % message
                        )
                        self._switch_key(log)
                        break
                    if self._is_service_unavailable(error):
                        log("Gemini service unavailable: %s" % message)
                        self._switch_key(log)
                        break
                    if self._is_rate_limited(error):
                        delay = self._extract_retry_delay(error)
                        log(
                            "Gemini rate limited request; sleeping %.1fs"
                            % delay
                        )
                        time.sleep(delay)
                        continue
                    if attempt + 1 >= self._max_retries:
                        raise GeminiTranslationError(message) from error
                    log(
                        "Gemini error (%s); retrying in %.1fs"
                        % (message, self._sleep_on_retry)
                    )
                    time.sleep(self._sleep_on_retry)
            else:
                continue
            if int(state.get("round", 0)) >= self._MAX_KEY_ROUNDS:
                break
        if last_error is None:
            raise GeminiTranslationError("Unknown Gemini failure")
        raise GeminiTranslationError(str(last_error)) from last_error

    # ------------------------------------------------------------------
    def translate_lines(
        self,
        lines: Sequence[str],
        *,
        source_language: str = "auto",
        target_language: str,
        delimiter: str,
        log: Optional[Callable[[str], None]] = None,
        stop_flag: Optional[Callable[[], bool]] = None,
    ) -> List[str]:
        if not lines:
            return []
        log_fn = log or (lambda message: None)
        prompt = self._build_prompt(
            lines,
            source_language=source_language,
            target_language=target_language,
            delimiter=delimiter,
        )
        raw_text = self._call_api(prompt, log=log_fn, stop_flag=stop_flag)
        segments = [segment for segment in raw_text.split(delimiter)]
        if len(segments) != len(lines):
            raise GeminiTranslationError(
                "Gemini returned %d lines for %d inputs"
                % (len(segments), len(lines))
            )
        return segments

    # ------------------------------------------------------------------
    def _build_prompt(
        self,
        lines: Sequence[str],
        *,
        source_language: str,
        target_language: str,
        delimiter: str,
    ) -> str:
        safe_source = source_language or "auto"
        numbered_lines = "\n".join(
            f"{index+1}. {line}" if line else f"{index+1}."
            for index, line in enumerate(lines)
        )
        return (
            "You are a professional subtitle translator. Translate the"
            f" following {len(lines)} subtitle lines from {safe_source} to"
            f" {target_language}. Maintain the same number of lines and the"
            " original order. Preserve any formatting tags such as <i>, </i>,"
            " {\an8}, or tokens that begin with '\u2063@@SCPTAG_' and end"
            " with '_SCP@@'. If an input line is empty, return an empty line."
            f" Respond with only the translated lines separated by the delimiter"
            f" '{delimiter}'.\nLines:\n{numbered_lines}"
        )

    # ------------------------------------------------------------------
    @property
    def config(self) -> _TranslatorConfig:
        return self._config


__all__ = ["GeminiSubtitleTranslator", "GeminiTranslationError"]
