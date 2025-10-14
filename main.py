# -*- coding: utf-8 -*-

import sys
import os
import importlib
from a4kSubtitles import api

if __name__ == '__main__':
    # This block ensures the script runs only when executed directly by Kodi.
    # It serves as the main entry point for the addon's user-facing actions,
    # such as searching for and downloading subtitles.
    os.environ.pop(api.api_mode_env_name, '')
    core = importlib.import_module('a4kSubtitles.core')
    core.main(int(sys.argv[1]), sys.argv[2][1:])
