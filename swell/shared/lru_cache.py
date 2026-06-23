from __future__ import annotations

from collections import OrderedDict
from typing import Generic, TypeVar

K = TypeVar("K")
V = TypeVar("V")


class LRUCache(OrderedDict, Generic[K, V]):
    """OrderedDict-based LRU cache with item-count and optional byte-size eviction.

    ``__setitem__`` automatically moves the key to the most-recently-used end
    and evicts the least-recently-used entries when either the item count limit
    or (optionally) the byte-size limit is exceeded.

    Parameters
    ----------
    max_items:
        Maximum number of entries to keep before evicting the oldest.
    max_bytes:
        Optional byte ceiling.  When set, entries whose values have an
        ``nbytes`` attribute (e.g. numpy arrays) are evicted oldest-first
        until the total falls below this limit.  Applied on every write.
    gc_min_keep:
        Minimum entries to retain during a :meth:`gc` pass.  Defaults to
        ``max(1, max_items // 4)``.
    """

    def __init__(
        self,
        max_items: int,
        max_bytes: int | None = None,
        gc_min_keep: int | None = None,
    ) -> None:
        super().__init__()
        self.max_items = int(max_items)
        self.max_bytes = max_bytes
        self._gc_min_keep = int(gc_min_keep) if gc_min_keep is not None else max(1, self.max_items // 4)

    # ------------------------------------------------------------------
    # Core LRU write — promotes key to MRU end then enforces limits
    # ------------------------------------------------------------------

    def __setitem__(self, key: K, value: V) -> None:  # type: ignore[override]
        super().__setitem__(key, value)
        self.move_to_end(key)
        self._evict_by_count()
        if self.max_bytes is not None:
            self._evict_by_bytes(self.max_bytes)

    # ------------------------------------------------------------------
    # Eviction helpers
    # ------------------------------------------------------------------

    def _evict_by_count(self) -> None:
        while len(self) > self.max_items:
            self.popitem(last=False)

    def _evict_by_bytes(self, max_bytes: int) -> None:
        total = sum(int(getattr(v, "nbytes", 0)) for v in self.values())
        while self and total > int(max_bytes):
            _k, old = self.popitem(last=False)
            total -= int(getattr(old, "nbytes", 0))

    # ------------------------------------------------------------------
    # Convenience: read with LRU promotion in a single call
    # ------------------------------------------------------------------

    def promote(self, key: K) -> V:
        """Return the value for *key* and promote it to the MRU position.

        Raises ``KeyError`` if the key is not present — callers should guard
        with ``key in cache`` beforehand.
        """
        value = OrderedDict.__getitem__(self, key)
        self.move_to_end(key)
        return value  # type: ignore[return-value]

    # ------------------------------------------------------------------
    # Periodic GC — called by the host app's cache-GC scheduler
    # ------------------------------------------------------------------

    def gc(self, aggressive: bool = False) -> None:
        """Trim the cache.

        *aggressive* clears the cache entirely; otherwise trims to half of
        ``max_items`` (but never below ``gc_min_keep``) and re-applies the
        byte limit if configured.
        """
        if aggressive:
            self.clear()
            return
        target = max(self._gc_min_keep, self.max_items // 2)
        while len(self) > target:
            self.popitem(last=False)
        if self.max_bytes is not None:
            self._evict_by_bytes(self.max_bytes)
