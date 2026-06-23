from __future__ import annotations

import numpy as np
import pytest

from swell.shared.lru_cache import LRUCache


def test_lru_cache_tracks_current_bytes_across_mutations() -> None:
    cache: LRUCache[str, np.ndarray] = LRUCache(max_items=10, max_bytes=10_000)
    cache["a"] = np.zeros((4,), dtype=np.uint8)
    cache["b"] = np.zeros((8,), dtype=np.uint8)

    assert cache.current_bytes == 12

    cache["a"] = np.zeros((2,), dtype=np.uint8)
    assert cache.current_bytes == 10

    key, value = cache.popitem(last=False)
    assert key == "b"
    assert value.nbytes == 8
    assert cache.current_bytes == 2

    assert cache.pop("missing", None) is None
    with pytest.raises(KeyError):
        cache.pop("missing")

    cache.clear()
    assert cache.current_bytes == 0


def test_lru_cache_byte_eviction_and_gc_update_current_bytes() -> None:
    cache: LRUCache[str, np.ndarray] = LRUCache(max_items=4, max_bytes=10, gc_min_keep=1)
    cache["a"] = np.zeros((4,), dtype=np.uint8)
    cache["b"] = np.zeros((4,), dtype=np.uint8)
    cache["c"] = np.zeros((4,), dtype=np.uint8)

    assert list(cache.keys()) == ["b", "c"]
    assert cache.current_bytes == 8

    cache["d"] = np.zeros((1,), dtype=np.uint8)
    cache["e"] = np.zeros((1,), dtype=np.uint8)
    cache.gc()

    assert list(cache.keys()) == ["d", "e"]
    assert cache.current_bytes == 2
