# -*- coding: utf-8 -*-

from a4kSubtitles import api, service

if __name__ == '__main__':
    """
    Main entry point for the addon's service.

    This script is called by Kodi to run the addon's service in the background.
    """
    service.start(api.A4kSubtitlesApi())
