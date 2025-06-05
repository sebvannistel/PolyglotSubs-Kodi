import os
from unittest.mock import MagicMock
from a4kSubtitles import download


def test_postprocess_binary_read(tmp_path):
    sample_text = "Hello subtitle"
    p = tmp_path / "sample.srt"
    p.write_bytes(sample_text.encode('utf-8'))

    core_mock = MagicMock()
    core_mock.os = os
    core_mock.kodi.get_bool_setting.return_value = False

    core_mock.utils.default_encoding = 'utf-8'
    core_mock.utils.base_encoding = 'raw_unicode_escape'
    core_mock.utils.py3 = True
    core_mock.utils.code_pages = {}
    core_mock.utils.cp1251_garbled = 'xyz'
    core_mock.utils.koi8r_garbled = 'abc'
    core_mock.utils.cleanup_subtitles.side_effect = lambda core, text: text

    download.__postprocess(core_mock, str(p), 'eng')

    assert p.read_text(encoding='utf-8') == sample_text
