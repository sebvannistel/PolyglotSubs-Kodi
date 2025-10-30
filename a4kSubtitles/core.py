# -*- coding: utf-8 -*-

import json
import os
import sys
import threading
import copy
import shutil
import gzip
import difflib
import time
import hashlib
import re
import zipfile
from datetime import datetime, timedelta
from base64 import b64encode
from xml.etree import ElementTree
from io import BytesIO

from .lib import (
    cache,
    kodi,
    logger,
    ordinal,
    request,
    utils,
    video,
)

core = sys.modules[__name__]
utils.core = core
core.ordinal = ordinal
core.num2ordinal = ordinal  # Backwards compatibility for legacy callers

api_mode_enabled = True
handle = None

progress_dialog = None
progress_text = ''

from .services import services
from .search import search
from .download import download
from .data import data

def main(handle, paramstring):  # pragma: no cover
    """
    The main entry point for the addon when called by Kodi.

    This function is responsible for parsing the input parameters from Kodi
    and routing the request to the appropriate function (e.g., search, download).

    Args:
        handle (int): The handle of the plugin, provided by Kodi.
        paramstring (str): A URL-encoded string of parameters, provided by Kodi.
                           Example: '?action=search&languages=en&preferredlanguage=en'
    """
    core.api_mode_enabled = False
    core.handle = handle

    params = dict(utils.parse_qsl(paramstring))
    if params['action'] == 'manualsearch':
        kodi.notification('Manual search is not supported')
    elif params['action'] == 'search':
        core.progress_text = ''
        core.progress_dialog = kodi.get_progress_dialog()

        try:
            search(core, params)
        finally:
            core.progress_dialog.close()
            core.progress_dialog = None

    elif params['action'] == 'download':
        params['action_args'] = json.loads(params['action_args'])
        download(core, params)

    kodi.xbmcplugin.endOfDirectory(handle)
