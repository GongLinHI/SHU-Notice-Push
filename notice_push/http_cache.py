from __future__ import annotations

from collections.abc import Callable
from concurrent.futures import Future
import threading


class RunScopedTextCache:
    def __init__(self):
        self._values: dict[str, str] = {}
        self._inflight: dict[str, Future[str]] = {}
        self._lock = threading.Lock()

    def get_or_load(self, url: str, loader: Callable[[], str]) -> str:
        with self._lock:
            if url in self._values:
                return self._values[url]
            future = self._inflight.get(url)
            if future is None:
                future = Future()
                self._inflight[url] = future
                owns_load = True
            else:
                owns_load = False

        if not owns_load:
            return future.result()

        try:
            value = loader()
        except BaseException as exc:
            with self._lock:
                self._inflight.pop(url, None)
            future.set_exception(exc)
            raise
        else:
            with self._lock:
                self._values[url] = value
                self._inflight.pop(url, None)
            future.set_result(value)
            return value


class CachedHttpClient:
    def __init__(self, delegate, cache: RunScopedTextCache | None = None):
        self._delegate = delegate
        self._cache = cache or RunScopedTextCache()

    def get_text(self, url: str) -> str:
        return self._cache.get_or_load(url, lambda: self._delegate.get_text(url))

    def get_bytes(self, url: str) -> bytes:
        return self._delegate.get_bytes(url)

    def get_bytes_limited(self, url: str, max_bytes: int) -> bytes:
        return self._delegate.get_bytes_limited(url, max_bytes)

    def get_download_limited(self, url: str, max_bytes: int):
        return self._delegate.get_download_limited(url, max_bytes)
