from concurrent.futures import ThreadPoolExecutor
import threading
import time

import pytest

from notice_push.http import DownloadedBytes
from notice_push.http_cache import CachedHttpClient, RunScopedTextCache


def test_run_scoped_text_cache_reuses_successful_value():
    cache = RunScopedTextCache()
    calls = 0

    def load():
        nonlocal calls
        calls += 1
        return "content"

    assert cache.get_or_load("https://example.com", load) == "content"
    assert cache.get_or_load("https://example.com", load) == "content"
    assert calls == 1


def test_run_scoped_text_cache_does_not_cache_failures():
    cache = RunScopedTextCache()
    calls = 0

    def load():
        nonlocal calls
        calls += 1
        if calls == 1:
            raise RuntimeError("temporary failure")
        return "recovered"

    with pytest.raises(RuntimeError, match="temporary failure"):
        cache.get_or_load("https://example.com", load)

    assert cache.get_or_load("https://example.com", load) == "recovered"
    assert calls == 2


def test_run_scoped_text_cache_coalesces_concurrent_loads():
    cache = RunScopedTextCache()
    calls = 0
    calls_lock = threading.Lock()

    def load():
        nonlocal calls
        with calls_lock:
            calls += 1
        time.sleep(0.03)
        return "shared"

    with ThreadPoolExecutor(max_workers=4) as executor:
        values = list(executor.map(lambda _: cache.get_or_load("https://example.com", load), range(4)))

    assert values == ["shared"] * 4
    assert calls == 1


def test_run_scoped_text_cache_shares_concurrent_failure_then_allows_later_retry():
    cache = RunScopedTextCache()
    calls = 0
    calls_lock = threading.Lock()
    workers_ready = threading.Barrier(4)
    loader_started = threading.Event()
    release_loader = threading.Event()

    def load():
        nonlocal calls
        with calls_lock:
            calls += 1
        loader_started.set()
        assert release_loader.wait(timeout=1)
        raise RuntimeError("temporary failure")

    def request():
        workers_ready.wait(timeout=1)
        return cache.get_or_load("https://example.com", load)

    with ThreadPoolExecutor(max_workers=4) as executor:
        futures = [executor.submit(request) for _ in range(4)]
        assert loader_started.wait(timeout=1)
        time.sleep(0.03)
        release_loader.set()
        for future in futures:
            with pytest.raises(RuntimeError, match="temporary failure"):
                future.result()

    assert calls == 1
    assert cache.get_or_load("https://example.com", lambda: "recovered") == "recovered"


class _RecordingDelegate:
    def __init__(self):
        self.text_calls = 0
        self.bytes_calls = 0
        self.download_calls = 0

    def get_text(self, url):
        self.text_calls += 1
        return "text"

    def get_bytes(self, url):
        self.bytes_calls += 1
        return b"bytes"

    def get_bytes_limited(self, url, max_bytes):
        self.bytes_calls += 1
        return b"limited"

    def get_download_limited(self, url, max_bytes):
        self.download_calls += 1
        return DownloadedBytes(b"download", "application/pdf")


def test_cached_http_client_only_caches_text_successes():
    delegate = _RecordingDelegate()
    client = CachedHttpClient(delegate)

    assert client.get_text("https://example.com/page") == "text"
    assert client.get_text("https://example.com/page") == "text"
    assert client.get_bytes("https://example.com/file") == b"bytes"
    assert client.get_bytes("https://example.com/file") == b"bytes"
    assert client.get_bytes_limited("https://example.com/file", 10) == b"limited"
    assert client.get_download_limited("https://example.com/file", 10).content == b"download"

    assert delegate.text_calls == 1
    assert delegate.bytes_calls == 3
    assert delegate.download_calls == 1
