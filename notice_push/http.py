from __future__ import annotations

import re
import threading
import time
from collections.abc import Callable
from dataclasses import dataclass
from typing import TypeVar

import requests

from notice_push.http_retry import is_retryable_http_status, retry_delay_seconds


_META_CHARSET_PATTERN = re.compile(br"<meta[^>]+charset=['\"]?([A-Za-z0-9_-]+)", re.IGNORECASE)
_WEAK_ENCODINGS = {"iso-8859-1", "latin-1"}
_ResponseValue = TypeVar("_ResponseValue")


@dataclass(frozen=True)
class DownloadedBytes:
    content: bytes
    content_type: str = ""


class HttpClient:
    def __init__(
        self,
        session=None,
        session_factory=None,
        timeout: int = 15,
        user_agent: str = "SHU-Notice-Push/2.0",
        max_retries: int = 2,
        initial_retry_delay: float = 0.5,
        retry_backoff: float = 2.0,
        max_retry_delay_seconds: float = 30.0,
    ):
        self._session = session
        self._session_factory = session_factory or requests.Session
        self._thread_local = threading.local()
        self._timeout = timeout
        self._user_agent = user_agent
        self._max_retries = max(1, max_retries)
        self._initial_retry_delay = max(0.0, initial_retry_delay)
        self._retry_backoff = max(1.0, retry_backoff)
        self._max_retry_delay_seconds = max(0.0, max_retry_delay_seconds)

    def get_text(self, url: str) -> str:
        return self._request_with_retry(url, consume=_decode_response)

    def get_bytes(self, url: str) -> bytes:
        return self._request_with_retry(url, consume=lambda response: response.content)

    def get_bytes_limited(self, url: str, max_bytes: int) -> bytes:
        return self.get_download_limited(url, max_bytes).content

    def get_download_limited(self, url: str, max_bytes: int) -> DownloadedBytes:
        return self._request_with_retry(
            url,
            stream=True,
            consume=lambda response: _read_download(response, max_bytes),
        )

    def _request_with_retry(
        self,
        url: str,
        *,
        stream: bool = False,
        consume: Callable[[object], _ResponseValue] | None = None,
    ):
        for attempt in range(self._max_retries):
            response = None
            try:
                kwargs = {
                    "timeout": self._timeout,
                    "headers": {"User-Agent": self._user_agent},
                }
                if stream:
                    kwargs["stream"] = True
                response = self._get_session().get(url, **kwargs)
                response.raise_for_status()
                if consume is None:
                    return response
                value = consume(response)
                _close_response(response)
                return value
            except requests.RequestException as exc:
                failed_response = response if response is not None else getattr(exc, "response", None)
                status_code = getattr(failed_response, "status_code", None)
                retry_after = (
                    _header_value(failed_response, "Retry-After")
                    if status_code in {429, 503}
                    else None
                )
                _close_response(failed_response)
                retryable = is_retryable_http_status(status_code) or isinstance(
                    exc,
                    (requests.ConnectionError, requests.Timeout),
                )
                if not retryable:
                    raise
                if attempt + 1 >= self._max_retries:
                    raise
                fallback_delay = self._initial_retry_delay * (self._retry_backoff**attempt)
                delay = retry_delay_seconds(
                    retry_after,
                    fallback_delay=fallback_delay,
                    max_delay=self._max_retry_delay_seconds,
                )
                if delay:
                    time.sleep(delay)
            except Exception:
                _close_response(response)
                raise

        raise RuntimeError("HTTP retry loop exited unexpectedly")

    def _get_session(self):
        if self._session is not None:
            return self._session
        session = getattr(self._thread_local, "session", None)
        if session is None:
            session = self._session_factory()
            self._thread_local.session = session
        return session


def _read_download(response, max_bytes: int) -> DownloadedBytes:
    chunks: list[bytes] = []
    total = 0
    for chunk in response.iter_content(chunk_size=8192):
        if not chunk:
            continue
        total += len(chunk)
        if total > max_bytes:
            raise ValueError("download exceeds max_bytes")
        chunks.append(chunk)
    content_type = ""
    headers = getattr(response, "headers", None)
    if headers:
        content_type = str(headers.get("content-type", "")).split(";", 1)[0].strip().lower()
    return DownloadedBytes(content=b"".join(chunks), content_type=content_type)


def _decode_response(response) -> str:
    encoding = _choose_encoding(response)
    return response.content.decode(encoding, errors="replace")


def _choose_encoding(response) -> str:
    response_encoding = (response.encoding or "").strip()
    if response_encoding and response_encoding.lower() not in _WEAK_ENCODINGS:
        return response_encoding

    meta_encoding = _encoding_from_meta(response.content)
    if meta_encoding:
        return meta_encoding

    apparent_encoding = (getattr(response, "apparent_encoding", None) or "").strip()
    if apparent_encoding and apparent_encoding.lower() not in _WEAK_ENCODINGS:
        return apparent_encoding

    return response_encoding or apparent_encoding or "utf-8"


def _encoding_from_meta(content: bytes) -> str | None:
    head = content[:4096]
    match = _META_CHARSET_PATTERN.search(head)
    if match:
        return match.group(1).decode("ascii", errors="ignore")
    return None


def _header_value(response, name: str) -> str | None:
    headers = getattr(response, "headers", None)
    if not headers:
        return None
    value = headers.get(name)
    if value is None:
        value = headers.get(name.lower())
    return str(value) if value is not None else None


def _close_response(response) -> None:
    close = getattr(response, "close", None)
    if callable(close):
        close()
