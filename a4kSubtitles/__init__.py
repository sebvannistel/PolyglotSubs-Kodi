# -*- coding: utf-8 -*-

"""Initialization helpers for the a4kSubtitles package.

This module intentionally avoids side effects at import time. The
``initialize`` function prepares the environment by locating vendored
third‑party libraries and ensuring they are available on ``sys.path``.
"""

from __future__ import annotations

import os
import sys
from typing import Optional


_ADDON_PATH: Optional[str] = None
_A4KSUBTITLES_DIR: Optional[str] = None
_THIRD_PARTY_LIBS_PATH: Optional[str] = None


def initialize() -> bool:
    """Configure paths and perform a minimal sanity check.

    Returns ``True`` if the optional vendored library check succeeds, ``False``
    otherwise.
    """

    try:
        from .lib import logger  # type: ignore
    except Exception:
        import logging

        logger = logging.getLogger(__name__)

    logger.debug("a4kSubtitles/__init__.py: KODI PYTHON VERSION: %s" % sys.version)

    global _ADDON_PATH, _A4KSUBTITLES_DIR, _THIRD_PARTY_LIBS_PATH

    try:
        import xbmcaddon

        addon_id = "service.subtitles.polyglotsubs-kodi"
        addon = xbmcaddon.Addon(addon_id)
        _ADDON_PATH = addon.getAddonInfo("path")
        if isinstance(_ADDON_PATH, bytes):
            _ADDON_PATH = _ADDON_PATH.decode("utf-8")
        logger.debug("a4kSubtitles/__init__.py: Addon path from xbmcaddon: %s" % _ADDON_PATH)
    except ImportError:
        logger.debug(
            "a4kSubtitles/__init__.py: xbmcaddon not found. Falling back to __file__ for path."
        )
        try:
            a4ksubtitles_dir_from_file = os.path.dirname(os.path.abspath(__file__))
            _ADDON_PATH = os.path.dirname(a4ksubtitles_dir_from_file)
            logger.debug("a4kSubtitles/__init__.py: Addon path from __file__: %s" % _ADDON_PATH)
        except NameError:
            logger.error(
                "a4kSubtitles/__init__.py: __file__ not defined, cannot determine addon path."
            )
            _ADDON_PATH = None
    except (FileNotFoundError, OSError) as exc:
        logger.error(
            "a4kSubtitles/__init__.py: Error getting addon path via xbmcaddon: %s. Attempting fallback." % exc
        )
        try:
            a4ksubtitles_dir_from_file = os.path.dirname(os.path.abspath(__file__))
            _ADDON_PATH = os.path.dirname(a4ksubtitles_dir_from_file)
            logger.debug(
                "a4kSubtitles/__init__.py: Addon path from __file__ (after xbmcaddon error): %s" % _ADDON_PATH
            )
        except NameError:
            logger.error(
                "a4kSubtitles/__init__.py: __file__ not defined during fallback, cannot determine addon path."
            )
            _ADDON_PATH = None
        except (FileNotFoundError, OSError) as exc2:
            logger.error(
                "a4kSubtitles/__init__.py: Error in fallback path determination: %s" % exc2
            )
            _ADDON_PATH = None

    if _ADDON_PATH:
        _A4KSUBTITLES_DIR = os.path.join(_ADDON_PATH, "a4kSubtitles")
        _THIRD_PARTY_LIBS_PATH = os.path.join(_A4KSUBTITLES_DIR, "lib", "third_party")

        if os.path.isdir(_THIRD_PARTY_LIBS_PATH):
            try:
                # Import requests before exposing vendored libraries to avoid
                # its dependency check from picking up our bundled chardet.
                import requests  # noqa: F401
            except Exception:
                logger.debug(
                    "a4kSubtitles/__init__.py: 'requests' not imported prior to sys.path modification"
                )

            if _THIRD_PARTY_LIBS_PATH not in sys.path:
                sys.path.insert(0, _THIRD_PARTY_LIBS_PATH)
                logger.debug(
                    "a4kSubtitles/__init__.py: Added to sys.path: %s" % _THIRD_PARTY_LIBS_PATH
                )
            else:
                logger.debug(
                    "a4kSubtitles/__init__.py: Already in sys.path: %s" % _THIRD_PARTY_LIBS_PATH
                )
        else:
            logger.warning(
                "a4kSubtitles/__init__.py: third_party path not found or not a directory: %s" % _THIRD_PARTY_LIBS_PATH
            )
    else:
        logger.error(
            "a4kSubtitles/__init__.py: Addon path could not be determined. sys.path not modified for third_party libs."
        )

    vendored_test_success = False
    try:
        import attrs  # noqa: F401

        vendored_test_success = True
        logger.debug(
            "a4kSubtitles/__init__.py: Successfully test-imported 'attrs' from vendored path."
        )
    except ImportError as exc:
        logger.error(
            "a4kSubtitles/__init__.py: FAILED to test-import 'attrs'. Check path and vendored files. Error: %s" % exc
        )
        logger.debug("Current sys.path (condensed for relevant paths):")
        for p_idx, p_val in enumerate(sys.path):
            path_lower = p_val.lower()
            if (
                "polyglotsubs-kodi" in path_lower
                or "a4ksubtitles" in path_lower
                or "third_party" in path_lower
            ):
                logger.debug("  [%d] -> %s" % (p_idx, p_val))
    except Exception as exc_attrs:
        logger.error(
            "a4kSubtitles/__init__.py: UNEXPECTED ERROR during 'attrs' test-import: %s" % exc_attrs
        )

    logger.debug("a4kSubtitles package initialized.")
    return vendored_test_success


__all__ = ["initialize"]

# Ensure third-party libraries are available when the package is imported.
initialize()

