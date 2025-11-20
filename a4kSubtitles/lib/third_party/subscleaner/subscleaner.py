# -*- coding: utf-8 -*-

"""
Subscleaner vendored for a4kSubtitles.
Modified to remove appdirs dependency and CLI features.
"""

import re
import logging

try:
    from .. import pysrt
    from .. import chardet
except ImportError:
    import pysrt
    import chardet

# Copying AD_PATTERNS from the original file
AD_PATTERNS = [
    re.compile(r"\bnordvpn\b", re.IGNORECASE),
    re.compile(r"\ba Card Shark AMERICASCARDROOM\b", re.IGNORECASE),
    re.compile(r"\bOpenSubtitles\b", re.IGNORECASE),
    re.compile(r"\bAdvertise your product or brand here\b", re.IGNORECASE),
    re.compile(r"\bApóyanos y conviértete en miembro VIP Para\b", re.IGNORECASE),
    re.compile(r"\bAddic7ed\b", re.IGNORECASE),
    re.compile(r"\bargenteam\b", re.IGNORECASE),
    re.compile(r"\bAllSubs\b", re.IGNORECASE),
    re.compile(r"\bCreated and Encoded by\b", re.IGNORECASE),
    re.compile(r"\bcorrected\s+by\b", re.IGNORECASE),
    re.compile(r"\bEntre a AmericasCardroom\.com Hoy\b", re.IGNORECASE),
    re.compile(r"\bEveryone is intimidated by a shark\. Become\b", re.IGNORECASE),
    re.compile(r"\bJuegue Poker en Línea por Dinero Real\b", re.IGNORECASE),
    re.compile(r"\bOpen Subtitles\b", re.IGNORECASE),
    re.compile(r"\bMKV Player\b", re.IGNORECASE),
    re.compile(r"\bResync\s+for\b", re.IGNORECASE),
    re.compile(r"\bResync\s+improved\b", re.IGNORECASE),
    re.compile(r"\bRipped\s+By\b", re.IGNORECASE),
    re.compile(r'\bSigue "Community" en\b', re.IGNORECASE),
    re.compile(r"\bSubtitles\s+by\b", re.IGNORECASE),
    re.compile(r"\bSubt[íi]tulos\s+por\b", re.IGNORECASE),
    re.compile(r"\bSupport us and become VIP member\b", re.IGNORECASE),
    re.compile(r"\bSubs\s+Team\b", re.IGNORECASE),
    re.compile(r"\bsubscene\b", re.IGNORECASE),
    re.compile(r"\bSubtitulado por\b", re.IGNORECASE),
    re.compile(r"\bsubtitulamos\b", re.IGNORECASE),
    re.compile(r"\bSynchronized\s+by\b", re.IGNORECASE),
    re.compile(r"\bSincronizado y corregido por\b", re.IGNORECASE),
    re.compile(r"\bsubdivx\b", re.IGNORECASE),
    re.compile(r"\bSync\s+Corrected\b", re.IGNORECASE),
    re.compile(r"\bSync\s+corrections\s+by\b", re.IGNORECASE),
    re.compile(r"\bsync and corrections by\b", re.IGNORECASE),
    re.compile(r"\bSync\s+by\b", re.IGNORECASE),
    re.compile(r"\bUna\s+traducci[óo]n\s+de\b", re.IGNORECASE),
    re.compile(r"\btvsubtitles\b", re.IGNORECASE),
    re.compile(r"\bTacho8\b", re.IGNORECASE),
    re.compile(r"\bfrom 3.49 USD/month ---->\b", re.IGNORECASE),
    re.compile(r"\bimplement REST API from", re.IGNORECASE),
    re.compile(r"\bSignup Here ->", re.IGNORECASE),
    re.compile(r"\bwww\.flixify\.app\b", re.IGNORECASE),
    re.compile(r"\bwww\.ADMITME\.APP\b", re.IGNORECASE),
    re.compile(r"\bwww\.ADMIT1\.APP\b", re.IGNORECASE),
    re.compile(r"\bsaveanilluminati\.com\b", re.IGNORECASE),
    re.compile(r"\bosdb\.link/\w+\b", re.IGNORECASE),
    re.compile(r"\bFilthyRichFutures\.com\b", re.IGNORECASE),
    re.compile(r"\bServerPartDeals\.com\b", re.IGNORECASE),
    re.compile(r"\bStreamingSites\.com\b", re.IGNORECASE),
    re.compile(r"\bSubtitles search by drag & drop\b", re.IGNORECASE),
    re.compile(r"\bSubtitles conformed by\b", re.IGNORECASE),
    re.compile(r"\bSubtitled [Bb]y\b", re.IGNORECASE),
    re.compile(r"\bResync by\b", re.IGNORECASE),
    re.compile(r"\bTRANSCRIPTED BY:\b", re.IGNORECASE),
    re.compile(r"\bVisiontext subtitles:\b", re.IGNORECASE),
    re.compile(r"\bSignup Here\b", re.IGNORECASE),
    re.compile(r"\bFind out @\b", re.IGNORECASE),
    re.compile(r"\bPublic shouldn't leave reviews for lawyers\.\b", re.IGNORECASE),
    re.compile(r"\bTrading can\.\b", re.IGNORECASE),
    re.compile(r"\bFree Browser extension:\b", re.IGNORECASE),
    re.compile(r"\bto get subtitles ->\b", re.IGNORECASE),
    re.compile(r"\bHelp other users to choose the best subtitles\b", re.IGNORECASE),
    re.compile(r"\bwith Subtitles for Free\b", re.IGNORECASE),
    re.compile(r"\bRARBG\b", re.IGNORECASE),
    re.compile(r"\bSerieCanal\.com\b", re.IGNORECASE),
    re.compile(r"\bNest0r\b", re.IGNORECASE),
    re.compile(r"\bikerslot\b", re.IGNORECASE),
    re.compile(r"\bmenoyos\b", re.IGNORECASE),
    re.compile(r"\bYTS.MX\b", re.IGNORECASE),
]

def contains_ad(subtitle_line):
    """
    Check if the given subtitle line contains an ad.

    Args:
        subtitle_line (str): The subtitle line to be checked.

    Returns:
        bool: True if the subtitle line contains an ad, False otherwise.
    """
    return any(pattern.search(subtitle_line) for pattern in AD_PATTERNS)

def remove_ad_lines(subtitle_data):
    """
    Remove ad lines from the subtitle data.

    Args:
        subtitle_data (pysrt.SubRipFile): The subtitle data object.

    Returns:
        bool: True if the subtitle data was modified, False otherwise.
    """
    modified = False
    indices_to_remove = []

    for index, subtitle in enumerate(subtitle_data):
        if contains_ad(subtitle.text):
            indices_to_remove.append(index)
            modified = True

    for index in sorted(indices_to_remove, reverse=True):
        del subtitle_data[index]

    return modified
