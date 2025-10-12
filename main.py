# -*- coding: utf-8 -*-

import sys
import os
import importlib
from a4kSubtitles import api

if __name__ == '__main__':
    """
    Main entry point for the addon.

    This script is called by Kodi to run the addon. It initializes the core module and calls the main function.
    """
    os.environ.pop(api.api_mode_env_name, '')
    core = importlib.import_module('a4kSubtitles.core')
    core.main(int(sys.argv[1]), sys.argv[2][1:])
