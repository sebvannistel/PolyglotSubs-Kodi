# -*- coding: utf-8 -*-

import json

from a4kSubtitles.lib import logger, utils
from tests.utils import spy_fn


def test_get_json_logs_on_invalid_json(tmp_path):
    invalid = tmp_path / "data.json"
    invalid.write_text("{ invalid", encoding="utf-8")

    spy = spy_fn(logger, "error")
    result = utils.get_json(str(tmp_path), "data.json")
    spy.restore()

    assert result is None
    assert spy.call_count >= 1


def test_get_json_returns_data_on_valid_json(tmp_path):
    data = {"key": "value"}
    valid = tmp_path / "data.json"
    valid.write_text(json.dumps(data), encoding="utf-8")

    result = utils.get_json(str(tmp_path), "data.json")

    assert result == data
