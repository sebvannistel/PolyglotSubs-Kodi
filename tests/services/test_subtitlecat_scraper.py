import json
import os
import types
from unittest.mock import MagicMock, patch

import pytest

os.environ.setdefault("A4KSUBTITLES_API_MODE", json.dumps({"kodi": True}))

from a4kSubtitles.services.subtitlecat import request as subtitlecat_request
from a4kSubtitles.services.subtitlecat import translation as subtitlecat_translation
from a4kSubtitles.services.subtitlecat import utils as subtitlecat_utils


@pytest.fixture(autouse=True)
def reset_thread_local_session():
    if hasattr(subtitlecat_utils, "_thread_local_session_storage"):
        storage = subtitlecat_utils._thread_local_session_storage
        if hasattr(storage, "session"):
            del storage.session
    yield
    if hasattr(subtitlecat_utils, "_thread_local_session_storage"):
        storage = subtitlecat_utils._thread_local_session_storage
        if hasattr(storage, "session"):
            del storage.session


def _build_core_mock():
    core = types.SimpleNamespace()
    core.logger = MagicMock()
    core.settings = MagicMock()
    core.settings.get.side_effect = lambda key, default=None: default
    kodi = MagicMock()
    kodi.notification = MagicMock()
    core.kodi = kodi
    return core


def test_get_session_uses_cloudscraper_defaults():
    fake_session = MagicMock()
    fake_session.headers = {}
    with patch(
        "a4kSubtitles.services.subtitlecat.utils.cloudscraper.create_scraper",
        return_value=fake_session,
    ) as create_scraper:
        session = subtitlecat_utils._get_session()
        assert session is fake_session
        create_scraper.assert_called_once_with(
            browser="firefox", delay=subtitlecat_utils.SC_SCRAPER_DELAY_SECONDS
        )
        for header_key in subtitlecat_utils._SCRAPER_DEFAULT_HEADERS:
            assert (
                fake_session.headers[header_key]
                == subtitlecat_utils._SCRAPER_DEFAULT_HEADERS[header_key]
            )


def test_warm_translation_cache_notifies_on_rate_limit():
    core = _build_core_mock()
    response = MagicMock()
    response.status_code = 503
    response.iter_content.return_value = []
    response.raise_for_status.return_value = None
    response.close = MagicMock()
    session = MagicMock()
    session.get.return_value = response
    with patch.object(subtitlecat_translation, "_get_session", return_value=session):
        success = subtitlecat_translation.warm_translation_cache(
            core, "subtitlecat", "https://example.com/result.srt"
        )
    assert not success
    session.get.assert_called_once()
    core.kodi.notification.assert_called_once()
    notified_message = core.kodi.notification.call_args[0][0]
    assert "503" in notified_message
    response.close.assert_called_once()


def test_direct_download_streams_challenge_payload(tmp_path):
    core = _build_core_mock()
    args = {
        "url": "https://www.subtitlecat.com/subs/foo/bar.srt",
        "filename": "bar.srt",
    }
    fake_payload = (
        "<html><title>Just a moment...</title><body>payload ready</body></html>".encode(
            "utf-8"
        )
    )
    response = MagicMock()
    response.status_code = 200
    response.iter_content.return_value = [fake_payload]
    response.raise_for_status.return_value = None
    response.close = MagicMock()
    session = MagicMock()
    session.get.return_value = response
    with patch.object(subtitlecat_request, "_get_session", return_value=session):
        with patch.object(
            subtitlecat_request,
            "_post_download_fix_encoding",
            wraps=subtitlecat_request._post_download_fix_encoding,
        ) as fix_encoding:
            download_request = subtitlecat_request.build_download_request(
                core, "subtitlecat", args
            )
            assert download_request["method"] == "REQUEST_CALLBACK"
            target_file = tmp_path / "out.srt"
            assert download_request["save_callback"](target_file.as_posix()) is True
            fix_encoding.assert_called_once()
            raw_bytes = fix_encoding.call_args[0][2]
            assert raw_bytes == fake_payload
    response.close.assert_called_once()
    session.get.assert_called_with(
        args["url"], timeout=core.settings.get("http_timeout", 15), stream=True
    )
