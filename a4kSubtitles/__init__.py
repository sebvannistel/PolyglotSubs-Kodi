# -*- coding: utf-8 -*-

import sys # Moved sys import to the top as it's used immediately
import os

# --- Print Python version for debugging ---
print("a4kSubtitles/__init__.py: KODI PYTHON VERSION: %s" % sys.version)
# ---

# --- Start of sys.path modification ---
# This code runs when the 'a4kSubtitles' package is first imported.

_ADDON_PATH = None
_A4KSUBTITLES_DIR = None
_THIRD_PARTY_LIBS_PATH = None

try:
    # Preferred Kodi way
    import xbmcaddon
    ADDON_ID = 'service.subtitles.polyglotsubs-kodi' # Your specific addon ID
    _ADDON = xbmcaddon.Addon(ADDON_ID)
    _ADDON_PATH = _ADDON.getAddonInfo('path')
    # On some systems (like Windows), Kodi might return a path that needs decoding
    if isinstance(_ADDON_PATH, bytes): # Python 3 check
        _ADDON_PATH = _ADDON_PATH.decode('utf-8')
    print("a4kSubtitles/__init__.py: Addon path from xbmcaddon: %s" % _ADDON_PATH)
except ImportError:
    print("a4kSubtitles/__init__.py: xbmcaddon not found. Falling back to __file__ for path.")
    # Fallback for environments where xbmcaddon is not available (e.g., local testing)
    # Assumes __file__ is .../a4kSubtitles/__init__.py
    # os.path.dirname(os.path.abspath(__file__)) is .../a4kSubtitles/
    # os.path.dirname(os.path.dirname(os.path.abspath(__file__))) is the addon root.
    try:
        _A4KSUBTITLES_DIR_FROM_FILE = os.path.dirname(os.path.abspath(__file__))
        _ADDON_PATH = os.path.dirname(_A4KSUBTITLES_DIR_FROM_FILE)
        print("a4kSubtitles/__init__.py: Addon path from __file__: %s" % _ADDON_PATH)
    except NameError: # __file__ might not be defined in some contexts
        print("a4kSubtitles/__init__.py: CRITICAL - __file__ not defined, cannot determine addon path.")
        _ADDON_PATH = None # Ensure it's None if path can't be found
except Exception as e:
    # Catch any other errors during xbmcaddon usage
    print("a4kSubtitles/__init__.py: Error getting addon path via xbmcaddon: %s. Attempting fallback." % str(e))
    try:
        _A4KSUBTITLES_DIR_FROM_FILE = os.path.dirname(os.path.abspath(__file__))
        _ADDON_PATH = os.path.dirname(_A4KSUBTITLES_DIR_FROM_FILE)
        print("a4kSubtitles/__init__.py: Addon path from __file__ (after xbmcaddon error): %s" % _ADDON_PATH)
    except NameError:
        print("a4kSubtitles/__init__.py: CRITICAL - __file__ not defined during fallback, cannot determine addon path.")
        _ADDON_PATH = None
    except Exception as e2:
        print("a4kSubtitles/__init__.py: CRITICAL - Error in fallback path determination: %s" % str(e2))
        _ADDON_PATH = None

if _ADDON_PATH:
    # Path to the a4kSubtitles package itself
    _A4KSUBTITLES_DIR = os.path.join(_ADDON_PATH, 'a4kSubtitles')

    # Path to the third_party libraries, which is inside a4kSubtitles/lib/
    _THIRD_PARTY_LIBS_PATH = os.path.join(_A4KSUBTITLES_DIR, 'lib', 'third_party')

    if os.path.isdir(_THIRD_PARTY_LIBS_PATH): # Use isdir for directories
        if _THIRD_PARTY_LIBS_PATH not in sys.path:
            sys.path.insert(0, _THIRD_PARTY_LIBS_PATH)
            print("a4kSubtitles/__init__.py: Added to sys.path: %s" % _THIRD_PARTY_LIBS_PATH)
        else:
            print("a4kSubtitles/__init__.py: Already in sys.path: %s" % _THIRD_PARTY_LIBS_PATH)
    else:
        print("a4kSubtitles/__init__.py: WARNING - third_party path not found or not a directory: %s" % _THIRD_PARTY_LIBS_PATH)
else:
    print("a4kSubtitles/__init__.py: CRITICAL - Addon path could not be determined. sys.path not modified for third_party libs.")

# --- End of sys.path modification ---

# Optional: A quick check to see if a core vendored lib is now importable (for debugging)
# This should be done *after* sys.path is modified.
_VENDORED_TEST_SUCCESS = False
try:
    import attrs # Corrected from 'attr'
    _VENDORED_TEST_SUCCESS = True
    print("a4kSubtitles/__init__.py: Successfully test-imported 'attrs' from vendored path.")
except ImportError as e:
    print("a4kSubtitles/__init__.py: FAILED to test-import 'attrs'. Check path and vendored files. Error: %s" % e)
    print("Current sys.path (condensed for relevant paths):")
    for p_idx, p_val in enumerate(sys.path):
        # Making the check more robust for various path casings
        path_lower = p_val.lower()
        if "polyglotsubs-kodi" in path_lower or "a4ksubtitles" in path_lower or "third_party" in path_lower:
            print("  [%d] -> %s" % (p_idx, p_val))
except Exception as e_attrs: # Catch any other potential errors during attrs import
    print("a4kSubtitles/__init__.py: UNEXPECTED ERROR during 'attrs' test-import: %s" % e_attrs)


# You can leave the rest of this file empty if it was, or add other package-level initializations.
print("a4kSubtitles package initialized.")