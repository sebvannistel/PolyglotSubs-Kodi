import json
import os
import types
from pathlib import Path

import pytest

from tests import common  # noqa: F401  # adds bundled dependencies to sys.path

os.environ.setdefault("A4KSUBTITLES_API_MODE", json.dumps({"kodi": True}))

from a4kSubtitles import api  # noqa: E402
from a4kSubtitles.services import subtitlecat as subtitlecat_module  # noqa: E402
from a4kSubtitles.services.subtitlecat import (  # noqa: E402
    request as subtitlecat_request,
)

SNAPSHOT_SEARCH_DIR = (
    Path(__file__).resolve().parent
    / "services"
    / "subtitlecat"
    / "watch_snapshots"
    / "search"
)


@pytest.mark.parametrize(
    "snapshot_path",
    sorted(SNAPSHOT_SEARCH_DIR.glob("*.html")),
    ids=lambda path: path.name,
)
def test_watch_search_snapshots(snapshot_path):
    if not snapshot_path.exists():
        pytest.skip("no subtitlecat watch snapshots available")

    api_instance = api.A4kSubtitlesApi({"kodi": True})
    core = api_instance.core
    core.services["subtitlecat"] = subtitlecat_module

    meta = types.SimpleNamespace(
        title="Watcher Snapshot",
        tvshow=None,
        is_tvshow=False,
        year=None,
        languages=["English"],
    )

    response = types.SimpleNamespace(
        status_code=200,
        text=snapshot_path.read_text(encoding="utf-8"),
        url="https://www.subtitlecat.com/layout-watch.html",
    )

    results = subtitlecat_request.parse_search_response(
        core, "subtitlecat", meta, response
    )
    assert results, f"Parser returned no results for snapshot {snapshot_path.name}"
