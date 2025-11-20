import os
import runpy
import sys
from unittest import mock

import pytest


def test_main_clears_env_and_calls_core_main():
    env_var = "A4KSUBTITLES_API_MODE"
    os.environ[env_var] = "1"
    fake_core = mock.Mock()
    with mock.patch("importlib.import_module", return_value=fake_core) as import_mod:
        argv = ["main.py", "7", "?param"]
        with mock.patch.object(sys, "argv", argv):
            runpy.run_module("main", run_name="__main__")
    import_mod.assert_called_once_with("a4kSubtitles.core")
    fake_core.main.assert_called_once_with(7, "param")
    assert env_var not in os.environ


@pytest.mark.parametrize(
    "argv, exc",
    [
        (["main.py"], IndexError),
        (["main.py", "7"], IndexError),
        (["main.py", "bad", "?param"], ValueError),
    ],
)
def test_main_with_missing_or_invalid_args(argv, exc):
    fake_core = mock.Mock()
    with mock.patch("importlib.import_module", return_value=fake_core):
        with mock.patch.object(sys, "argv", argv):
            with pytest.raises(exc):
                runpy.run_module("main", run_name="__main__")
    fake_core.main.assert_not_called()


def test_main_service_starts_api_service():
    with mock.patch("a4kSubtitles.service.start") as mock_start:
        with mock.patch("a4kSubtitles.api.A4kSubtitlesApi") as mock_api:
            runpy.run_module("main_service", run_name="__main__")
    mock_api.assert_called_once_with()
    mock_start.assert_called_once_with(mock_api.return_value)
