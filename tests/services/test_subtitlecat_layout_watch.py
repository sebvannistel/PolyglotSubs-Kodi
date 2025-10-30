import json
import os
import sys
import types
from pathlib import Path

import pytest

os.environ.setdefault("A4KSUBTITLES_API_MODE", json.dumps({"kodi": True}))

if "cloudscraper" not in sys.modules:
    fake_cloudscraper = types.ModuleType("cloudscraper")

    class _FakeResponse:
        status_code = 200

        def iter_content(self, chunk_size=0):
            yield b""

        def raise_for_status(self):
            return None

        def close(self):
            return None

    class _FakeScraper:
        def __init__(self):
            self.headers = {}

        def get(self, *args, **kwargs):
            return _FakeResponse()

    fake_cloudscraper.create_scraper = lambda **kwargs: _FakeScraper()
    sys.modules["cloudscraper"] = fake_cloudscraper
    fake_exceptions = types.ModuleType("cloudscraper.exceptions")

    class _FakeCloudflareException(Exception):
        pass

    fake_exceptions.CloudflareException = _FakeCloudflareException
    fake_exceptions.CloudflareChallengeError = _FakeCloudflareException
    sys.modules["cloudscraper.exceptions"] = fake_exceptions

from a4kSubtitles.services.subtitlecat import request as subtitlecat_request

SNAPSHOT_DIR = Path(__file__).resolve().parents[1] / "data" / "subtitlecat_watch"
SNAPSHOTS = sorted(SNAPSHOT_DIR.glob("*.html"))


@pytest.mark.parametrize("snapshot_path", SNAPSHOTS or [None])
def test_subtitlecat_snapshots_parse(snapshot_path):
    if snapshot_path is None:
        pytest.skip(
            "No watcher snapshots captured yet. Run tools/subtitlecat-layout-watch/watch_subtitlecat.py "
            "--update-test-fixtures to add fixtures."
        )

    html = snapshot_path.read_text(encoding="utf-8")

    core = types.SimpleNamespace()
    core.logger = types.SimpleNamespace(
        debug=lambda *args, **kwargs: None,
        info=lambda *args, **kwargs: None,
        warning=lambda *args, **kwargs: None,
        error=lambda *args, **kwargs: None,
    )
    core.settings = types.SimpleNamespace(get=lambda key, default=None: default)
    core.services = {"subtitlecat": types.SimpleNamespace(display_name="Subtitlecat.com")}
    core.utils = types.SimpleNamespace(
        get_lang_id=lambda language, *_args: (language or "en")[:2].lower()
    )
    core.kodi = types.SimpleNamespace(
        xbmc=types.SimpleNamespace(ISO_639_1="iso-639-1")
    )

    meta = types.SimpleNamespace(
        title=snapshot_path.stem.replace("-", " "),
        tvshow="",
        is_tvshow=False,
        year=None,
        languages=["English"],
        season=None,
        episode=None,
    )

    response = types.SimpleNamespace(
        status_code=200,
        text=html,
        url=f"https://www.subtitlecat.com/index.php?search={snapshot_path.stem}",
    )

    results = subtitlecat_request.parse_search_response(core, "subtitlecat", meta, response)
    assert results, f"Expected subtitle results for snapshot {snapshot_path.name}"
