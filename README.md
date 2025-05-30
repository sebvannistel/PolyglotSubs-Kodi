<img align="left" width="90px" height="90px" src="icon.png">


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

This fork integrates [Subtitlecat.com](https://www.subtitlecat.com) as a subtitle service. The main changes are within the `a4kSubtitles/services/subtitlecat.py` file, enabling:
*   Direct searching and downloading of subtitles from Subtitlecat.
*   Automated requests for server-side translation of subtitles if a direct match for your language isn't immediately available. The addon will then wait for the translation to complete and download the subtitle.
*   Robust URL handling and parsing tailored for Subtitlecat.

Otherwise, this fork aims to keep the core functionality and other providers as they are in the upstream `a4k-openproject` version.

## Configuration

You can customize PolyglotSubs-Kodi to your preferences through the addon settings.

**How to Access Addon Settings:**
1.  Open KODI.
2.  Navigate to **Settings** (the gear icon on the main menu).
3.  Select **Add-ons**.
4.  Choose **My add-ons**.
5.  Scroll down and select **Subtitle add-ons**.
6.  Find and select **PolyglotSubs-Kodi** (it might be listed as a4kSubtitles or a similar name).
7.  Click on **Configure**.

*(The existing configuration GIF from the original project that provides a good general overview of navigating the settings panel.)*
![configuration](https://media.giphy.com/media/kewuE4BgfOnFin0vEC/source.gif)

Below is a description of the available settings, generally following the structure you'll find in the configuration dialog:

### 1. General Settings (Category: General)

This section covers the main behavior of the addon.

*   **Preferred Subtitle Languages:**
    *   **What it does:** Standard Kodi feature allowing you to set your primary, secondary, and tertiary languages for subtitles. PolyglotSubs-Kodi will prioritize results in these languages.
    *   **How to access:** This is typically configured in Kodi's global settings: **Settings -> Player -> Language**. Look for "Preferred subtitle language". Some skins or setups might also offer quick access during playback. PolyglotSubs-Kodi will use these system-wide settings.
*   **Timeout for Services (ID: `general.timeout`):**
    *   **What it does:** Sets the maximum time (in seconds) the addon will wait for each subtitle service to respond.
    *   **Default:** 15 seconds. You can increase this if you have a slow connection or decrease it for faster searches (though some services might be missed).
*   **Limit Results per Service (ID: `general.results_limit`):**
    *   **What it does:** Defines the maximum number of subtitle results to fetch from each enabled service.
    *   **Default:** 100.
*   **Auto Search First Item (ID: `general.auto_search`):**
    *   **What it does:** If enabled, automatically starts a subtitle search when you open the subtitle dialog for the first time for a video.
    *   **Default:** False (Disabled).
*   **Auto Download First Result Silently (ID: `general.auto_download`):**
    *   **What it does:** If enabled (and "Auto Search First Item" is also enabled), the addon will attempt to automatically download the first subtitle result it finds without showing you the selection list. Use with caution, as the "best" result isn't always perfect.
    *   **Default:** False (Disabled).
*   **Use Charset Detection (chardet) (ID: `general.use_chardet`):**
    *   **What it does:** Enables the use of the `chardet` library to automatically detect and correct the encoding of subtitles. This is useful for subtitles with special characters that might not display correctly.
    *   **Default:** True (Enabled).
*   **Auto-select subtitle if only one result (ID: `general.auto_select`):**
    *   **What it does:** If only one subtitle is found across all enabled services, it will be automatically selected and downloaded.
    *   **Default:** True (Enabled).
*   **Prefer SDH Subtitles (Subtitles for Deaf or Hard-of-hearing) (ID: `general.prefer_sdh`):**
    *   **What it does:** If enabled (and "Auto Download First Result Silently" is active), the addon will try to prioritize SDH subtitles if available. This preference might also influence sorting in manual selection lists.
    *   **Default:** False (Disabled).
*   **Prefer Forced Subtitles (ID: `general.prefer_forced`):**
    *   **What it does:** If enabled, the addon will try to prioritize "forced" subtitles. Forced subtitles are used to translate dialogue in a foreign language when the main audio track is in your preferred language (e.g., alien speech in a sci-fi movie). This preference is active when "Auto-select subtitle if only one result" is true or "Auto Download First Result Silently" is true.
    *   **Default:** True (Enabled).
*   **Enable/Disable Embedded Subtitles:**
    *   **Note:** PolyglotSubs-Kodi primarily focuses on downloading external subtitle files. The handling of embedded subtitles (those already within your video file) is usually controlled by Kodi's main player settings, not this addon's settings specifically. Check under **Settings -> Player -> Language -> Enable parsing for closed captions / Teletext**.

### 2. Services (Subtitle Providers)

This section allows you to enable or disable individual subtitle providers. PolyglotSubs-Kodi will only search for subtitles on services that are enabled here.

*   **Addic7ed (ID: `addic7ed.enabled`):** Default: False (Disabled)
*   **BSPlayer (ID: `bsplayer.enabled`):** Default: False (Disabled)
*   **OpenSubtitles (ID: `opensubtitles.enabled`):** Default: False (Disabled). *Requires account details in the "Accounts" section.*
*   **Podnadpisi.NET (ID: `podnadpisi.enabled`):** Default: False (Disabled)
*   **Subtitlecat.com (ID: `subtitlecat.enabled`):** Default: True (Enabled)
    *   **Also for Subtitlecat - Upload translated subtitles (ID: `subtitlecat_upload_translations`):**
        *   **What it does:** When PolyglotSubs-Kodi requests an on-demand translation from Subtitlecat, this setting (if enabled) allows the addon to indicate to Subtitlecat that the translated result can be shared and made available to other Subtitlecat users. This helps improve the Subtitlecat database over time. Disabling this means translations are for your use only.
        *   **Default:** True (Enabled - contributes back to Subtitlecat).
*   **SubDL (ID: `subdl.enabled`):** Default: False (Disabled). *May require API key in the "Accounts" section.*
*   **SubSource (ID: `subsource.enabled`):** Default: False (Disabled)

### 3. Accounts

Some subtitle services require you to have an account (and sometimes API keys) to use them.

*   **OpenSubtitles:**
    *   **Username (ID: `opensubtitles.username`):** Your OpenSubtitles.org username. **This is often mandatory for the OpenSubtitles service to work.**
    *   **Password (ID: `opensubtitles.password`):** Your OpenSubtitles.org password.
*   **SubDL:**
    *   **API Key (ID: `subdl.apikey`):** Your SubDL API key, if you have one.

**Note on Languages and Providers:**
Remember to set your preferred languages in Kodi's main settings. PolyglotSubs-Kodi uses these preferences to search across all enabled providers. The availability and quality of subtitles can vary greatly between providers and languages. If you're not finding subtitles for specific content, try enabling more providers or checking their individual websites.

## Installation of this Fork (PolyglotSubs-Kodi)

To install this specific version of a4kSubtitles:

**Important First Step:** To prevent potential conflicts or issues, it is **highly recommended to uninstall any previous versions of `a4kSubtitles` or other conflicting subtitle addons** before installing this fork.

1.  **Download the Addon:**
    *   Go to the releases page for this fork: [(https://github.com/sebvannistel/PolyglotSubs-Kodi/releases)]((https://github.com/sebvannistel/PolyglotSubs-Kodi/releases))
    *   Download the latest `service.subtitles.polyglotsubs-kodi-X.X.X.sc.X.zip` file (e.g., `service.subtitles.polyglotsubs-kodi-3.20.0.sc.9.zip`).

2.  **Enable Unknown Sources in KODI (If Not Already Done):**
    *   Before you can install from a zip file, you might need to enable "Unknown Sources".
    *   Typically, you can find this under **Settings** (often a gear icon) **-> System -> Add-ons -> Unknown sources**.
    *   Toggle this option **on**.
    *   Kodi will likely show a warning about the risks of installing from unknown sources; you'll need to read and accept this warning to proceed.
    *   *Note: The exact path to this setting might vary slightly depending on your Kodi version or skin. If you can't find it, you can refer to the [official Kodi Wiki](https://kodi.wiki/view/Settings/System/Add-ons#Unknown_sources) for the most current instructions.*

3.  **Install in KODI:**
    *   Open KODI.
    *   Navigate to **Settings** (often a gear icon on the main menu) **-> Add-ons** -> **Install from zip file**.
    *   Browse to the location where you downloaded the `.zip` file (from Step 1) and select it.
    *   Wait for the "Add-on installed" notification.

4.  **Configure (Recommended):**
    *   After installation, find "PolyglotSubs-Kodi" in your Subtitle add-ons.
    *   Open its settings. **Subtitlecat.com is enabled by default.** You can review other provider settings and also configure your preferred languages here, though main language preferences are typically set globally in Kodi's Player settings (see Configuration section).

**Note:** This installation method installs the addon directly. It differs from the original a4kSubtitles installation that typically uses a repository.

## Using PolyglotSubs-Kodi

This section explains common user actions. The general process of searching and selecting subtitles is also visually demonstrated in the "Preview" section below.

### Subtitle Search

1.  **Access Player Controls:** While your video is playing, access the video player controls. This might vary by Kodi skin, but often involves pressing 'Enter', 'OK', or a menu button on your remote.
2.  **Open Subtitles Menu:** Navigate to the Subtitles icon/button (often looks like a speech bubble or 'cc' icon) within the player controls.
3.  **Search Process:** PolyglotSubs-Kodi will then search for subtitles using your enabled providers. If multiple services are active, this might take a few moments.
4.  **Select and Download:** You'll be presented with a list of found subtitles. Results are typically sorted by relevance or language. Select a subtitle from the list to download and display it on your video. If "subtitlecat.com" is shown in yellow colour it means that the subtitles have not been translated yet. Therefore when you select it you need to give it around 2-3min time to translate. After it finished it will download automatically.


### Subtitlecat.com Integration

PolyglotSubs-Kodi automatically leverages Subtitlecat.com if Subtitlecat is enabled as a provider in the addon's settings.

*   **Direct Matches:** If a subtitle in your preferred language is found directly on Subtitlecat, it will be listed in your search results like any other provider.
*   **On-Demand Translation:** This is a key feature of the Subtitlecat integration.
    *   If a direct subtitle match isn't found in your preferred language, but Subtitlecat has a version it can translate (e.g., an English subtitle that can be translated to your Spanish preferred language), the addon will automatically request this translation from Subtitlecat's servers.
    *   This process happens in the background. You might see a notification about the translation being initiated.
    *   The translated subtitle will typically appear in the search results list after a short delay (usually a minute or two, depending on Subtitlecat's server load and the length of the subtitle).
    *   No extra steps are usually needed from your side other than waiting briefly for these translated options to appear in the list. Select them as you would any other subtitle.

### Automatic & Other Features

PolyglotSubs-Kodi inherits many features from the original a4kSubtitles, including options for automation.

*   **Explore Settings:** You can explore the addon's settings for features like "Auto download first subtitle result silently" or other options to automatically download the best-matched subtitle based on your preferences.
*   These settings can help streamline your subtitle experience, but their availability and behavior might depend on the specific version and your overall Kodi setup.

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

## Contributing

We welcome contributions! Please see our [CONTRIBUTING.md](CONTRIBUTING.md) file for guidelines on how to report issues, suggest features, and submit pull requests.

## Icon

Original logo `quill` by Ramy Wafaa ([RoundIcons](https://roundicons.com)).
