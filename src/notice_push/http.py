from __future__ import annotations

import re
import threading
import time

import requests


_META_CHARSET_PATTERN = re.compile(br"<meta[^>]+charset=['\"]?([A-Za-z0-9_-]+)", re.IGNORECASE)
_WEAK_ENCODINGS = {"iso-8859-1", "latin-1"}


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
    ):
        self._session = session
        self._session_factory = session_factory or requests.Session
        self._thread_local = threading.local()
        self._timeout = timeout
        self._user_agent = user_agent
        self._max_retries = max(1, max_retries)
        self._initial_retry_delay = max(0.0, initial_retry_delay)
        self._retry_backoff = max(1.0, retry_backoff)

    def get_text(self, url: str) -> str:
        last_error: Exception | None = None
        for attempt in range(self._max_retries):
            try:
                response = self._get_session().get(
                    url,
                    timeout=self._timeout,
                    headers={"User-Agent": self._user_agent},
                )
                response.raise_for_status()
                break
            except Exception as exc:
                last_error = exc
                if attempt + 1 >= self._max_retries:
                    raise
                retry_delay = self._initial_retry_delay * (self._retry_backoff**attempt)
                if retry_delay:
                    time.sleep(retry_delay)
        else:
            raise last_error  # type: ignore[misc]

        encoding = _choose_encoding(response)
        return response.content.decode(encoding, errors="replace")

    def _get_session(self):
        if self._session is not None:
            return self._session
        session = getattr(self._thread_local, "session", None)
        if session is None:
            session = self._session_factory()
            self._thread_local.session = session
        return session


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
