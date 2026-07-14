from datetime import datetime, timedelta, timezone
from email.utils import format_datetime
from types import SimpleNamespace

import pytest
import requests

from notice_push.http import HttpClient
from notice_push.http_retry import is_retryable_http_status, retry_delay_seconds
from notice_push import app_factory


@pytest.mark.parametrize(
    ("status", "should_retry"),
    [(401, False), (404, False), (408, True), (429, True), (500, True), (503, True)],
)
def test_http_status_retry_policy(status, should_retry):
    assert is_retryable_http_status(status) is should_retry


def test_retry_after_seconds_is_capped_by_profile_limit():
    assert retry_delay_seconds("120", fallback_delay=1.0, max_delay=30.0) == 30.0


def test_retry_after_http_date_is_supported_and_capped():
    now = datetime(2026, 7, 13, tzinfo=timezone.utc)
    retry_at = format_datetime(now + timedelta(seconds=45), usegmt=True)

    assert retry_delay_seconds(retry_at, fallback_delay=1.0, max_delay=30.0, now=now) == 30.0


class _StatusResponse:
    def __init__(self, status_code: int, *, retry_after: str | None = None):
        self.status_code = status_code
        self.headers = {"Retry-After": retry_after} if retry_after else {}
        self.content = b"ok"
        self.encoding = "utf-8"
        self.apparent_encoding = "utf-8"
        self.closed = False

    def raise_for_status(self):
        if self.status_code >= 400:
            raise requests.HTTPError(f"status {self.status_code}", response=self)

    def close(self):
        self.closed = True


class _SequenceSession:
    def __init__(self, responses):
        self.responses = list(responses)
        self.calls = 0

    def get(self, url, **kwargs):
        response = self.responses[self.calls]
        self.calls += 1
        return response


class _InvalidUrlSession:
    def __init__(self):
        self.calls = 0

    def get(self, url, **kwargs):
        self.calls += 1
        raise requests.exceptions.InvalidURL("invalid URL")


def test_http_client_does_not_retry_permanent_404_and_closes_response(monkeypatch):
    response = _StatusResponse(404)
    session = _SequenceSession([response])
    sleep_calls = []
    monkeypatch.setattr("notice_push.http.time.sleep", sleep_calls.append)
    client = HttpClient(session=session, max_retries=3, initial_retry_delay=1)

    with pytest.raises(requests.HTTPError, match="status 404"):
        client.get_text("https://example.com/missing")

    assert session.calls == 1
    assert response.closed is True
    assert sleep_calls == []


def test_http_client_does_not_retry_non_transport_request_exception(monkeypatch):
    session = _InvalidUrlSession()
    sleep_calls = []
    monkeypatch.setattr("notice_push.http.time.sleep", sleep_calls.append)
    client = HttpClient(session=session, max_retries=3, initial_retry_delay=1)

    with pytest.raises(requests.exceptions.InvalidURL, match="invalid URL"):
        client.get_text("not-a-url")

    assert session.calls == 1
    assert sleep_calls == []


def test_http_client_retries_429_using_capped_retry_after_and_closes_failed_response(monkeypatch):
    rate_limited = _StatusResponse(429, retry_after="120")
    success = _StatusResponse(200)
    session = _SequenceSession([rate_limited, success])
    sleep_calls = []
    monkeypatch.setattr("notice_push.http.time.sleep", sleep_calls.append)
    client = HttpClient(
        session=session,
        max_retries=2,
        initial_retry_delay=1,
        retry_backoff=2,
        max_retry_delay_seconds=30,
    )

    assert client.get_text("https://example.com/notices") == "ok"
    assert session.calls == 2
    assert rate_limited.closed is True
    assert sleep_calls == [30.0]


def test_build_http_client_passes_all_profile_retry_parameters(monkeypatch):
    captured = {}
    monkeypatch.setattr(app_factory, "HttpClient", lambda **kwargs: captured.update(kwargs) or kwargs)
    profile = SimpleNamespace(
        http_timeout=12,
        http_max_retries=3,
        http_initial_retry_delay=0.8,
        http_retry_backoff=2.5,
        http_max_retry_delay_seconds=25,
    )

    client = app_factory.build_http_client(profile)

    assert client == {
        "timeout": 12,
        "max_retries": 3,
        "initial_retry_delay": 0.8,
        "retry_backoff": 2.5,
        "max_retry_delay_seconds": 25,
    }
