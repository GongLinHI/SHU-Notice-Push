from __future__ import annotations

import time
from collections.abc import Callable
from typing import Optional, TypeVar


T = TypeVar("T")


def call_with_retry(
    operation: Callable[[], T],
    *,
    max_retries: int,
    initial_retry_delay: float,
    retry_backoff: float,
) -> T:
    last_error: Optional[Exception] = None
    attempts = max(1, max_retries)
    for attempt in range(attempts):
        try:
            return operation()
        except Exception as exc:
            last_error = exc
            if attempt + 1 >= attempts:
                break
            retry_delay = max(0.0, initial_retry_delay) * (max(1.0, retry_backoff) ** attempt)
            if retry_delay:
                time.sleep(retry_delay)
    raise last_error  # type: ignore[misc]


def create_chat_completion_with_retry(
    client,
    *,
    model: str,
    messages: list[dict],
    timeout: int,
    max_retries: int,
    initial_retry_delay: float,
    retry_backoff: float,
) -> str:
    def create_completion() -> str:
        response = client.chat.completions.create(
            model=model,
            messages=messages,
            stream=False,
            timeout=timeout,
        )
        content = response.choices[0].message.content
        if not content or not content.strip():
            raise ValueError("empty summary response from model")
        return content

    return call_with_retry(
        create_completion,
        max_retries=max_retries,
        initial_retry_delay=initial_retry_delay,
        retry_backoff=retry_backoff,
    )
