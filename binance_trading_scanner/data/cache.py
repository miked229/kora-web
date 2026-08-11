"""In-memory TTL cache.

Prevents re-downloading identical market data on every Streamlit rerun. Keyed by
an arbitrary hashable tuple; entries expire after ``ttl`` seconds.
"""
from __future__ import annotations

import threading
import time
from typing import Any, Callable, Hashable, Optional


class TTLCache:
    """A tiny thread-safe time-to-live cache."""

    def __init__(self, ttl: float = 30.0, max_size: int = 512) -> None:
        self.ttl = ttl
        self.max_size = max_size
        self._store: dict[Hashable, tuple[float, Any]] = {}
        self._lock = threading.Lock()

    def get(self, key: Hashable) -> Optional[Any]:
        with self._lock:
            item = self._store.get(key)
            if item is None:
                return None
            expires, value = item
            if time.time() > expires:
                self._store.pop(key, None)
                return None
            return value

    def set(self, key: Hashable, value: Any, ttl: Optional[float] = None) -> None:
        with self._lock:
            if len(self._store) >= self.max_size:
                self._evict_oldest()
            self._store[key] = (time.time() + (ttl if ttl is not None else self.ttl), value)

    def get_or_compute(self, key: Hashable, compute: Callable[[], Any], ttl: Optional[float] = None) -> Any:
        cached = self.get(key)
        if cached is not None:
            return cached
        value = compute()
        self.set(key, value, ttl)
        return value

    def clear(self) -> None:
        with self._lock:
            self._store.clear()

    def _evict_oldest(self) -> None:
        # Called under lock. Drop the entry with the nearest expiry.
        if not self._store:
            return
        oldest = min(self._store.items(), key=lambda kv: kv[1][0])[0]
        self._store.pop(oldest, None)
