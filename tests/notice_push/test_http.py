import pytest
import threading

from notice_push.http import HttpClient


class _FakeResponse:
    def __init__(self, content: bytes, encoding: str | None = None, headers=None):
        self.content = content
        self.encoding = encoding
        self.apparent_encoding = "utf-8"
        self.headers = headers or {}
        self.raised = False

    def raise_for_status(self):
        self.raised = True

    def iter_content(self, chunk_size=8192):
        yield self.content


class _FakeSession:
    def __init__(self, response: _FakeResponse):
        self.response = response
        self.last_request = None
        self.calls = 0

    def get(self, url, **kwargs):
        self.calls += 1
        self.last_request = (url, kwargs)
        return self.response


class _FlakySession:
    def __init__(self, response: _FakeResponse):
        self.response = response
        self.calls = 0

    def get(self, url, **kwargs):
        self.calls += 1
        if self.calls == 1:
            raise RuntimeError("temporary network error")
        return self.response


class _AlwaysFailSession:
    def __init__(self):
        self.calls = 0

    def get(self, url, **kwargs):
        self.calls += 1
        raise RuntimeError("network down")


def test_http_client_get_text_uses_timeout_headers_and_encoding():
    response = _FakeResponse("通知正文".encode("utf-8"))
    session = _FakeSession(response)
    client = HttpClient(session=session, timeout=8, user_agent="test-agent")

    text = client.get_text("https://www.shu.edu.cn/tzgg.htm")

    assert text == "通知正文"
    assert response.raised is True
    assert session.last_request == (
        "https://www.shu.edu.cn/tzgg.htm",
        {"timeout": 8, "headers": {"User-Agent": "test-agent"}},
    )


def test_http_client_prefers_response_encoding():
    response = _FakeResponse("通知正文".encode("gbk"), encoding="gbk")
    client = HttpClient(session=_FakeSession(response))

    assert client.get_text("https://example.com") == "通知正文"


def test_http_client_uses_meta_charset_when_response_encoding_is_weak():
    html = '<html><head><meta charset="utf-8"></head><body>通知正文</body></html>'
    response = _FakeResponse(html.encode("utf-8"), encoding="ISO-8859-1")
    client = HttpClient(session=_FakeSession(response))

    assert "通知正文" in client.get_text("https://example.com")


def test_http_client_retries_transient_request_errors():
    response = _FakeResponse("通知正文".encode("utf-8"))
    session = _FlakySession(response)
    client = HttpClient(session=session, max_retries=2, initial_retry_delay=0)

    assert client.get_text("https://example.com") == "通知正文"
    assert session.calls == 2


def test_http_client_uses_exponential_backoff_between_retries(monkeypatch):
    session = _AlwaysFailSession()
    sleep_calls = []

    monkeypatch.setattr("notice_push.http.time.sleep", sleep_calls.append)
    client = HttpClient(
        session=session,
        max_retries=3,
        initial_retry_delay=0.5,
        retry_backoff=2.0,
    )

    with pytest.raises(RuntimeError, match="network down"):
        client.get_text("https://example.com")

    assert session.calls == 3
    assert sleep_calls == [0.5, 1.0]


def test_http_client_uses_thread_local_sessions_from_factory():
    created_sessions = []
    lock = threading.Lock()

    def session_factory():
        session = _FakeSession(_FakeResponse("通知正文".encode("utf-8")))
        with lock:
            created_sessions.append(session)
        return session

    client = HttpClient(session_factory=session_factory)

    threads = [
        threading.Thread(target=lambda: client.get_text("https://example.com")),
        threading.Thread(target=lambda: client.get_text("https://example.com")),
    ]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join()

    assert len(created_sessions) == 2
    assert all(session.calls == 1 for session in created_sessions)


def test_http_client_get_bytes_limited_streams_until_limit():
    response = _FakeResponse(b"abcde")
    session = _FakeSession(response)
    client = HttpClient(session=session, timeout=8, user_agent="test-agent")

    content = client.get_bytes_limited("https://example.com/file.pdf", max_bytes=5)

    assert content == b"abcde"
    assert session.last_request == (
        "https://example.com/file.pdf",
        {"timeout": 8, "headers": {"User-Agent": "test-agent"}, "stream": True},
    )


def test_http_client_get_bytes_limited_rejects_oversized_download():
    response = _FakeResponse(b"abcdef")
    client = HttpClient(session=_FakeSession(response))

    with pytest.raises(ValueError, match="download exceeds max_bytes"):
        client.get_bytes_limited("https://example.com/file.pdf", max_bytes=5)


def test_http_client_get_download_limited_returns_content_type():
    response = _FakeResponse(
        b"%PDF-1.7",
        headers={"content-type": "application/pdf; charset=binary"},
    )
    client = HttpClient(session=_FakeSession(response))

    downloaded = client.get_download_limited("https://example.com/download?id=1", max_bytes=1024)

    assert downloaded.content == b"%PDF-1.7"
    assert downloaded.content_type == "application/pdf"
