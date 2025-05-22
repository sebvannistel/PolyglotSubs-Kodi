# -*- coding: utf-8 -*-

import sys
import os

# --- Start of sys.path modification ---
try:
    import xbmcaddon
    ADDON_ID = 'service.subtitles.a4ksubtitlecat' # Your specific addon ID
    ADDON = xbmcaddon.Addon(ADDON_ID)
    # getAddonInfo('path') returns the addon's root directory
    ADDON_PATH = ADDON.getAddonInfo('path')
    # On Windows, Kodi might return a path that needs decoding
    if sys.platform == 'win32':
        ADDON_PATH = ADDON_PATH.decode('utf-8')
except ImportError:
    # Fallback for environments where xbmcaddon is not available (e.g., local testing outside Kodi)
    # This assumes __file__ is .../a4kSubtitles/__init__.py
    # So, os.path.dirname(os.path.abspath(__file__)) is .../a4kSubtitles/
    # And os.path.dirname(os.path.dirname(os.path.abspath(__file__))) is the addon root.
    print("a4kSubtitles: xbmcaddon not found, attempting to determine addon path from __file__.")
    ADDON_PATH = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
except Exception as e:
    # Catch any other errors during xbmcaddon usage and try to fallback
    print("a4kSubtitles: Error getting addon path via xbmcaddon: %s. Falling back." % str(e))
    ADDON_PATH = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


# Path to the a4kSubtitles package itself (which is the directory containing this __init__.py)
# This is os.path.join(ADDON_PATH, 'a4kSubtitles')
A4KSUBTITLES_DIR = os.path.join(ADDON_PATH, 'a4kSubtitles')

# Path to the third_party libraries, which is inside a4kSubtitles/lib/
THIRD_PARTY_LIBS_PATH = os.path.join(A4KSUBTITLES_DIR, 'lib', 'third_party')

if os.path.exists(THIRD_PARTY_LIBS_PATH):
    if THIRD_PARTY_LIBS_PATH not in sys.path:
        sys.path.insert(0, THIRD_PARTY_LIBS_PATH)
        print("a4kSubtitles: Added to sys.path: %s" % THIRD_PARTY_LIBS_PATH)
    else:
        print("a4kSubtitles: Already in sys.path: %s" % THIRD_PARTY_LIBS_PATH)
else:
    print("a4kSubtitles: CRITICAL - Path not found, cannot add to sys.path: %s" % THIRD_PARTY_LIBS_PATH)

# (Optional) If you also have libraries directly under a4kSubtitles/lib/
# MAIN_LIBS_PATH = os.path.join(A4KSUBTITLES_DIR, 'lib')
# if os.path.exists(MAIN_LIBS_PATH):
#     if MAIN_LIBS_PATH not in sys.path:
#         sys.path.insert(0, MAIN_LIBS_PATH)
#         print("a4kSubtitles: Added to sys.path: %s" % MAIN_LIBS_PATH)
# else:
#     print("a4kSubtitles: Path not found for main libs: %s" % MAIN_LIBS_PATH)
# --- End of sys.path modification ---

# You can leave the rest of this file empty if it was, or add other package-level initializations.
print("a4kSubtitles package initialized. Current sys.path relevant entries:")
for p in sys.path:
    if "a4ksubtitlecat" in p.lower() or "rapidfuzz" in p.lower(): # just for debug logging
        print("  -> %s" % p)