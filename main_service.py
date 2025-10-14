# -*- coding: utf-8 -*-

from a4kSubtitles import api, service

if __name__ == '__main__':
    # This block ensures the script runs only when executed directly by Kodi.
    # It serves as the entry point for the addon's background service, which
    # handles tasks like automatic subtitle searching and downloading.
    service.start(api.A4kSubtitlesApi())
