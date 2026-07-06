from __future__ import annotations

import time
from typing import Optional


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
    last_error: Optional[Exception] = None
    attempts = max(1, max_retries)
    for attempt in range(attempts):
        try:
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
        except Exception as exc:
            last_error = exc
            if attempt + 1 >= attempts:
                break
            retry_delay = max(0.0, initial_retry_delay) * (max(1.0, retry_backoff) ** attempt)
            if retry_delay:
                time.sleep(retry_delay)
    raise last_error  # type: ignore[misc]
