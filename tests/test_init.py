import importlib
import json
import sys
from pathlib import Path


def test_initialize_adds_third_party_path(monkeypatch):
    third_party = (
        Path(__file__).resolve().parent.parent
        / "a4kSubtitles"
        / "lib"
        / "third_party"
    )

    original_sys_path = sys.path.copy()
    if str(third_party) in sys.path:
        sys.path.remove(str(third_party))

    monkeypatch.setenv("A4KSUBTITLES_API_MODE", json.dumps({"kodi": True}))

    import a4kSubtitles
    importlib.reload(a4kSubtitles)

    assert str(third_party) in sys.path

    sys.path.remove(str(third_party))
    a4kSubtitles.initialize()
    assert str(third_party) in sys.path

    sys.path[:] = original_sys_path
