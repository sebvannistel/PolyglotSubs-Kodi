from a4kSubtitles.services.subtitlecat.translation import (
    _protect_subtitle_tags,
    _restore_subtitle_tags,
)
from a4kSubtitles.services.subtitlecat.utils import LRUCache


def test_lru_cache_eviction():
    cache = LRUCache(maxsize=2)
    cache["a"] = 1
    cache["b"] = 2
    cache["c"] = 3
    assert "a" not in cache
    assert cache["b"] == 2


def test_protect_restore_tags_roundtrip():
    text = "<i>Hello</i>"
    protected, tags, is_all_tag = _protect_subtitle_tags(text)
    assert not is_all_tag
    restored = _restore_subtitle_tags(protected, tags)
    assert restored == text
