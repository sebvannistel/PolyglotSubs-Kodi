<img align="left" width="90px" height="90px" src="icon.png">

# a4kSubtitles

[![Kodi version](https://img.shields.io/badge/kodi%20versions-19+-blue)](https://kodi.tv/)
[![View Releases](https://img.shields.io/badge/releases-on%20GitHub-blue)](https://github.com/a4k-openproject/a4kSubtitles/releases)

a4kSubtitles is a subtitle addon for Kodi.

## Description

a4kSubtitles is a subtitle addon for KODI. It supports multiple subtitle services and provides a simple API for developers to integrate subtitle functionality into their own addons.

## Features

*   **Multiple Subtitle Services:** Supports a variety of subtitle services, including:
    *   Addic7ed
    *   BSPlayer
    *   OpenSubtitles
    *   Podnadpisi.NET
    *   SubDL
    *   SubSource
    *   Subtitlecat.com
*   **Automatic Subtitle Search and Download:** Automatically searches for and downloads subtitles for the currently playing video.
*   **Manual Subtitle Search:** Allows users to manually search for subtitles.
*   **Subtitle Post-Processing:** Cleans up and formats subtitles for optimal viewing.
*   **API for Developers:** Provides a simple API for developers to integrate subtitle functionality into their own addons.

## Installation (for Users)

1.  **Download the Addon:**
    *   Go to the [releases page](https://github.com/a4k-openproject/a4kSubtitles/releases).
    *   Download the latest `service.subtitles.a4ksubtitles-X.X.X.zip` file.
2.  **Enable Unknown Sources in KODI:**
    *   Go to **Settings -> System -> Add-ons -> Unknown sources**.
    *   Toggle this option **on**.
3.  **Install in KODI:**
    *   Go to **Settings -> Add-ons -> Install from zip file**.
    *   Browse to the location where you downloaded the `.zip` file and select it.
    *   Wait for the "Add-on installed" notification.

## Usage (for Users)

### Subtitle Search

1.  While a video is playing, open the subtitles menu.
2.  Select "Download...".
3.  a4kSubtitles will search for subtitles using the enabled services.
4.  Select a subtitle from the list to download and display it.

### Automatic Subtitle Search

a4kSubtitles can automatically search for and download subtitles when a video starts playing. To enable this feature:

1.  Go to the addon settings.
2.  Enable "Auto search first item".
3.  Optionally, enable "Auto download first result silently" to automatically download the best-matched subtitle.

## Configuration

You can customize a4kSubtitles to your preferences through the addon settings.

**How to Access Addon Settings:**
1.  Open KODI.
2.  Navigate to **Settings** (the gear icon on the main menu).
3.  Select **Add-ons**.
4.  Choose **My add-ons**.
5.  Scroll down and select **Subtitle add-ons**.
6.  Find and select **a4kSubtitles**.
7.  Click on **Configure**.

![configuration](https://media.giphy.com/media/kewuE4BgfOnFin0vEC/source.gif)

Below is a description of the available settings, generally following the structure you'll find in the configuration dialog:

### 1. General Settings (Category: General)

This section covers the main behavior of the addon.

*   **Preferred Subtitle Languages:**
    *   **What it does:** Standard Kodi feature allowing you to set your primary, secondary, and tertiary languages for subtitles. a4kSubtitles will prioritize results in these languages.
    *   **How to access:** This is typically configured in Kodi's global settings: **Settings -> Player -> Language**. Look for "Preferred subtitle language". Some skins or setups might also offer quick access during playback. a4kSubtitles will use these system-wide settings.
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
*   **Upload Translated Subtitles to Subtitlecat (ID: `subtitlecat_upload_translations`):**
    *   **What it does:** When a4kSubtitles requests an on-demand translation from Subtitlecat, enabling this option allows the addon to share the translated subtitle back with Subtitlecat so other users can benefit. Disable it if you prefer the translation to remain private.
    *   **Default:** True (Enabled - contributes back to Subtitlecat).
*   **Notify When Upload Completes (ID: `subtitlecat_notify_upload`):**
    *   **What it does:** Shows a Kodi notification once a translated subtitle has been successfully uploaded to Subtitlecat and a shareable URL is returned.
    *   **Default:** True (Enabled).
*   **Include Server-Shared Translations (ID: `subtitlecat_include_shared`):**
    *   **What it does:** Controls whether Subtitlecat results from its shared translation system (shown with "[Shared]") appear in your search results.
    *   **Default:** True (Enabled).
*   **Gemini Translator (IDs: `subtitlecat_gemini_*`):**
    *   **What it does:** Configures the built-in Gemini-powered translator used when Subtitlecat cannot supply a ready-made translation. Add one or more API keys (comma or newline separated) that the addon can rotate through when making Gemini requests. You can also pick a custom Gemini model, set how many requests are allowed per key before throttling, and control how long the addon sleeps between throttled batches.
    *   **Defaults:** Empty API key list (must be provided), model `gemini-2.0-flash`, request limit `90`, throttle sleep `60` seconds. Keys can also be read from the environment variables `GEMINI_API_KEY` or `GOOGLE_API_KEY` if you prefer not to store them in the Kodi settings dialog.
*   **Enable/Disable Embedded Subtitles:**
    *   **Note:** a4kSubtitles primarily focuses on downloading external subtitle files. The handling of embedded subtitles (those already within your video file) is usually controlled by Kodi's main player settings, not this addon's settings specifically. Check under **Settings -> Player -> Language -> Enable parsing for closed captions / Teletext**.

### 2. Services (Subtitle Providers)

This section allows you to enable or disable individual subtitle providers. a4kSubtitles will only search for subtitles on services that are enabled here.

*   **Addic7ed (ID: `addic7ed.enabled`):** Default: False (Disabled)
*   **BSPlayer (ID: `bsplayer.enabled`):** Default: False (Disabled)
*   **OpenSubtitles (ID: `opensubtitles.enabled`):** Default: False (Disabled). *Requires account details in the "Accounts" section.*
*   **Podnadpisi.NET (ID: `podnadpisi.enabled`):** Default: False (Disabled)
*   **Subtitlecat.com (ID: `subtitlecat.enabled`):** Default: True (Enabled)
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
Remember to set your preferred languages in Kodi's main settings. a4kSubtitles uses these preferences to search across all enabled providers. The availability and quality of subtitles can vary greatly between providers and languages. If you're not finding subtitles for specific content, try enabling more providers or checking their individual websites.

## For Developers

This section provides information for developers who want to contribute to a4kSubtitles or use its API.

### Getting Started

1.  **Clone the repository:**
    ```bash
    git clone https://github.com/a4k-openproject/a4kSubtitles.git
    cd a4kSubtitles
    ```
2.  **Set up a virtual environment:**
    ```bash
    python3 -m venv venv
    source venv/bin/activate
    ```
3.  **Install dependencies:**
    ```bash
    pip install -r requirements.txt
    pip install -r requirements-dev.txt
    ```

### Dependencies

The addon relies on the Python packages listed in `requirements.txt` for runtime operation. Subtitlecat translation caching now
uses [`cachetools`](https://cachetools.readthedocs.io/) to provide a robust LRU implementation, so downstream packagers should
ensure that `cachetools>=5.5` is available when building or distributing PolyglotSubs-Kodi.

For environments that need to bypass Cloudflare or otherwise rely on the Subtitlecat headless bridge, install [Node.js 18 or newer](https://nodejs.org/) (or provide another compatible runtime) and set the **Node.js executable (Subtitlecat headless helper)** path in the addon settings. When no path is configured the addon falls back to searching for `node` on `PATH`; if the runtime cannot be located the traditional scraper continues to operate and detailed errors are logged to help with troubleshooting.

### Running Tests

Run unit tests with:

```bash
pytest
```

Integration tests are skipped by default. Include them with:

```bash
pytest --run-integration
```

Before committing or pushing changes, run the preflight script to execute the linters and tests:

```bash
scripts/preflight.sh
```

This script runs `pre-commit run --all-files` and `pytest` to catch formatting problems and failing tests early.

### Project Structure

*   `a4kSubtitles/`: Main addon source code.
    *   `api.py`: The public API for other addons to consume.
    *   `core.py`: Core logic for searching, downloading, and managing services.
    *   `lib/`: Utility functions, libraries, and helpers (e.g., Kodi wrappers, caching, request handling).
    *   `services/`: Implementations for each individual subtitle provider.
    *   `main.py`: The main entry point for the addon when called by Kodi.
    *   `main_service.py`: The entry point for the background service (for automatic downloads).
*   `tests/`: Unit and integration tests.
*   `resources/`: Addon resources like settings definitions (`settings.xml`) and language files.

### How It Works

1.  A user action (e.g., "Download Subtitles") or the background service triggers the `search` function in `a4kSubtitles/core.py`.
2.  The `search` function gets video metadata (IMDb ID, title, season, episode) using helpers in `a4kSubtitles/lib/video.py`.
3.  It then iterates through all enabled services defined in `a4kSubtitles/services/`.
4.  For each service, it calls `build_search_requests` to get the necessary HTTP request details.
5.  It executes these requests in parallel threads.
6.  As responses arrive, `parse_search_response` is called for each service to transform the service-specific response into a standardized list of subtitle results.
7.  All results are collected, sorted, and ranked in `__prepare_results`.
8.  The final list is presented to the user or, if auto-download is enabled, the top result is passed to the `download` function.
9.  The `download` function calls `build_download_request` for the selected service and handles the file download and extraction.

### Adding a New Service

To add a new subtitle provider, you need to create a new service file and implement a set of functions.

1.  **Create a new file** in `a4kSubtitles/services/`, e.g., `newservice.py`.
2.  **Implement the service functions** in this file. See existing services for examples.
    *   `build_search_requests(core, service_name, meta)`: Should return a list of request dictionaries for searching.
    *   `parse_search_response(core, service_name, meta, response)`: Should parse the HTTP response and return a list of standardized subtitle result dictionaries.
    *   `build_download_request(core, service_name, action_args)`: Should return a request dictionary for downloading the selected subtitle file.
    *   (Optional) `build_auth_request` and `parse_auth_response` if the service requires authentication.
3.  **Register the service** in `a4kSubtitles/services/__init__.py`. Add your new service to the `services` dictionary. The key should be the service name (e.g., `newservice`), and the value should be a dictionary containing its display name and a reference to your implemented functions.
4.  **Add settings** for your service in `resources/settings.xml` so users can enable/disable it and configure any necessary settings (like username/password).

### API Reference

a4kSubtitles provides a simple API for developers to integrate subtitle functionality into their own addons.

**`A4kSubtitlesApi` Class**

This is the main class for interacting with the addon.

```python
from a4kSubtitles import api

# Initialize the API
# In a real addon, you would not pass mocks.
a4k = api.A4kSubtitlesApi()
```

**Methods:**

*   **`search(params, settings=None, video_meta=None)`**: Searches for subtitles.
    *   `params` (dict): A dictionary of search parameters. Required keys: `languages` (comma-separated list) and `preferredlanguage`.
    *   `settings` (dict, optional): Mock addon settings for testing.
    *   `video_meta` (dict, optional): Mock video metadata for testing.
    *   **Returns**: A list of subtitle result dictionaries.

*   **`download(params, settings=None)`**: Downloads a subtitle.
    *   `params` (dict): A subtitle result dictionary obtained from `search()`.
    *   `settings` (dict, optional): Mock addon settings for testing.
    *   **Returns**: The local path to the downloaded subtitle file.

*   **`mock_settings(settings)`**: Temporarily overrides addon settings. Useful for testing.
    *   `settings` (dict): A dictionary of settings to mock.
    *   **Returns**: A function to restore the original settings.

*   **`auto_load_enabled(settings=None)`**: Checks if auto-loading of subtitles is enabled.
    *   `settings` (dict, optional): Mock addon settings for testing.
    *   **Returns**: `True` if auto-loading is enabled, `False` otherwise.

**Example:**

```python
from a4kSubtitles import api

# Initialize the API
a4k = api.A4kSubtitlesApi()

# Search for subtitles
# In a real addon, params would be provided by Kodi.
results = a4k.search({
    'languages': 'en',
    'preferredlanguage': 'en',
})

# Download a subtitle
if results:
    subfile = a4k.download(results[0])
    print("Subtitle downloaded to:", subfile)
```

## Contributing

We welcome contributions! Please see our [CONTRIBUTING.md](CONTRIBUTING.md) file for guidelines on how to report issues, suggest features, and submit pull requests.

## License

This addon is licensed under the MIT License. See the [LICENSE](LICENSE) file for more details.

## Icon

Original logo `quill` by Ramy Wafaa ([RoundIcons](https://roundicons.com)).