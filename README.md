<img align="left" width="115px" height="115px" src="ico.png">

# PolyglotSubs-Kodi
[![Kodi version](https://img.shields.io/badge/kodi%20versions-20--21-blue)](https://kodi.tv/)
[![View Releases](https://img.shields.io/badge/releases-on%20GitHub-blue)](https://github.com/sevannistel/a4kSubtitles/releases)

This is a fork of the original [a4kSubtitles](https://github.com/a4k-openproject/a4kSubtitles) addon, modified to include **Subtitlecat.com** as an additional subtitle provider.

## Description

a4kSubtitles is a subtitle addon for KODI. This version retains the features and providers of the original while adding support for Subtitlecat.com.

**Key Features of PolyglotSubs-Kodi:**
*   Includes all original providers from a4kSubtitles.
*   **Adds Subtitlecat.com:**
    *   Searches for subtitles on Subtitlecat.com.
    *   Supports on-demand translation of subtitles via Subtitlecat's server-side translation feature. If a direct subtitle in your desired language isn't available but can be translated by Subtitlecat, this addon will trigger the translation and poll for the result.

**Supported Subtitle Services:**
*   Addic7ed
*   BSPlayer
*   OpenSubtitles
*   Podnadpisi.NET
*   SubDL
*   SubSource
*   **Subtitlecat.com (New in this Mod)**

## What's New in this Fork?

This fork introduces the `SubtitlecatMod`, which integrates [Subtitlecat.com](https://www.subtitlecat.com) as a subtitle service. The main changes are within the `a4kSubtitles/services/subtitlecat.py` file, enabling:
*   Direct searching and downloading of subtitles from Subtitlecat.
*   Automated requests for server-side translation of subtitles if a direct match for your language isn't immediately available. The addon will then wait for the translation to complete and download the subtitle.
*   Robust URL handling and parsing tailored for Subtitlecat.

Otherwise, this fork aims to keep the core functionality and other providers as they are in the upstream `a4k-openproject` version.

## Configuration
General configuration for providers remains similar to the original a4kSubtitles.
*(Original configuration GIF, still largely applicable)*
![configuration](https://media.giphy.com/media/kewuE4BgfOnFin0vEC/source.gif)

The Subtitlecat provider does not require special configuration beyond enabling it in the addon settings (if applicable) and selecting your preferred languages.

## Installation of this Fork (SubtitlecatMod)

To install this specific version of a4kSubtitles with the SubtitlecatMod:

1.  **Download the Addon:**
    *   Go to the releases page for this fork: [https://github.com/sevannistel/a4kSubtitles/releases](https://github.com/sevannistel/a4kSubtitles/releases)
    *   Download the latest `service.subtitles.a4ksubtitlecat-X.X.X.sc.X.zip` file (e.g., `service.subtitles.a4ksubtitlecat-3.20.0.sc.9.zip`).

2.  **Install in KODI:**
    *   Open KODI.
    *   Navigate to **Add-ons**.
    *   Select **Install from zip file**.
    *   You may need to enable "Unknown sources" if you haven't already.
    *   Browse to the location where you downloaded the `.zip` file and select it.
    *   Wait for the "Add-on installed" notification.

3.  **Configure (Optional but Recommended):**
    *   After installation, find "a4kSubtitles" in your Program or Subtitle add-ons.
    *   Open its settings. Ensure "Subtitlecat" is enabled as a provider (if there's a toggle) and configure your preferred languages.

**Note:** This installation method installs the addon directly. It differs from the original a4kSubtitles installation that uses a repository. If you have the original a4kSubtitles installed, this version might overwrite it, or you might need to uninstall the original first, depending on Kodi's behavior with addon ID conflicts.

## Preview
The general usage for searching and selecting subtitles remains consistent with the original a4kSubtitles addon.
*(Original usage GIF, still largely applicable)*
![usage](https://media.giphy.com/media/QTmhgEJTpTPTPxByfj/source.gif)

## Differences from Original a4kSubtitles

*   **Primary Change:** This fork's main purpose is to add **Subtitlecat.com** as a provider, including its unique translation-on-demand feature.
*   **Source:** This version is maintained by [sevannistel](https://github.com/sevannistel), not the original `a4k-openproject` team.
*   **Release Method:** Releases for this fork are provided as direct ZIP files on the [sevannistel/a4kSubtitles releases page](https://github.com/sevannistel/a4kSubtitles/releases).

## License

This addon, like the original, is licensed under the MIT License. See the [LICENSE](LICENSE) file for more details.

## Icon

Original logo `quill` by Ramy Wafaa ([RoundIcons](https://roundicons.com)).
