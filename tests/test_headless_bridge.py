import base64
import json
import os
import sys
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

# Ensure repository root on sys.path
CURRENT_DIR = os.path.dirname(__file__)
REPO_ROOT = os.path.abspath(os.path.join(CURRENT_DIR, "..", ".."))
if REPO_ROOT not in sys.path:
    sys.path.append(REPO_ROOT)

os.environ.setdefault("A4KSUBTITLES_API_MODE", json.dumps({"kodi": True}))

from a4kSubtitles.services.subtitlecat import headless_bridge  # noqa: E402


def _build_core():
    core = MagicMock()
    core.logger = MagicMock()
    core.settings.get.side_effect = lambda key, default=None: default
    core.services = MagicMock()

    xbmc = SimpleNamespace(ISO_639_1="iso639-1", ENGLISH_NAME="english")
    core.kodi = SimpleNamespace(xbmc=xbmc)

    def get_lang_id(value, target):
        mapping = {
            ("English", xbmc.ISO_639_1): "en",
            ("Albanian", xbmc.ISO_639_1): "sq",
            ("en", xbmc.ENGLISH_NAME): "English",
            ("sq", xbmc.ENGLISH_NAME): "Albanian",
        }
        return mapping.get((value, target))

    core.utils = SimpleNamespace(get_lang_id=get_lang_id)
    core.services.get.return_value = SimpleNamespace(display_name="Subtitlecat.com")
    return core


@patch("a4kSubtitles.services.subtitlecat.headless_bridge._run_node")
def test_search_converts_node_results(mock_run_node):
    core = _build_core()
    meta = SimpleNamespace(title="Inception", is_tvshow=False, languages=["English"])

    payload = {
        "ok": True,
        "items": [
            {
                "title": "Inception",
                "href": "subs/1/Inception.html",
                "detailUrl": "https://www.subtitlecat.com/subs/1/Inception.html",
                "languages": [
                    {
                        "code": "en",
                        "name": "English",
                        "downloadHref": "/subs/123/Inception-en.srt",
                    }
                ],
            }
        ],
    }
    mock_run_node.return_value = SimpleNamespace(stdout=json.dumps(payload), stderr="", returncode=0)

    results = headless_bridge.search(core, "subtitlecat", meta)

    assert len(results) == 1
    entry = results[0]
    assert entry["action_args"]["url"] == "https://www.subtitlecat.com/subs/123/Inception-en.srt"
    assert entry["action_args"]["needs_client_side_translation"] is False
    mock_run_node.assert_called_once()


@patch("a4kSubtitles.services.subtitlecat.headless_bridge._post_download_fix_encoding")
@patch("a4kSubtitles.services.subtitlecat.headless_bridge._run_node")
def test_download_success(mock_run_node, mock_fix_encoding):
    core = _build_core()
    payload = {
        "ok": True,
        "data": base64.b64encode(b"hello world").decode("ascii"),
    }
    mock_run_node.return_value = SimpleNamespace(stdout=json.dumps(payload), stderr="", returncode=0)

    result = headless_bridge.download(
        core,
        "subtitlecat",
        "https://www.subtitlecat.com/subs/1/Inception.html",
        "en",
        "/tmp/output.srt",
    )

    assert result is True
    mock_fix_encoding.assert_called_once()


@patch("a4kSubtitles.services.subtitlecat.headless_bridge._post_download_fix_encoding")
@patch("a4kSubtitles.services.subtitlecat.headless_bridge._run_node", return_value=None)
def test_download_timeout(mock_run_node, mock_fix_encoding):
    core = _build_core()

    result = headless_bridge.download(
        core,
        "subtitlecat",
        "https://www.subtitlecat.com/subs/1/Inception.html",
        "en",
        "/tmp/output.srt",
    )

    assert result is False
    mock_fix_encoding.assert_not_called()
