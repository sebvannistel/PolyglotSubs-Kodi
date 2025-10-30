"""Vendorized SubtitleCAT Gemini translator helpers.

This package vendors the non-GUI translation utilities from
`TestersNightmare/SubtitleCAT` so the addon can reuse the Gemini powered
translator without pulling in the Tkinter application. Only the minimal
APIs required by PolyglotSubs-Kodi are exposed.
"""

from .translator import GeminiSubtitleTranslator, TranslationError, TranslatorConfig

__all__ = [
    "GeminiSubtitleTranslator",
    "TranslationError",
    "TranslatorConfig",
]
