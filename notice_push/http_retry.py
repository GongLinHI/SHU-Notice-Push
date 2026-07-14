from __future__ import annotations

from datetime import datetime, timezone
from email.utils import parsedate_to_datetime
import math


RETRYABLE_HTTP_STATUS_CODES = frozenset({408, 425, 429, 500, 502, 503, 504})


def is_retryable_http_status(status_code: int | None) -> bool:
    return status_code in RETRYABLE_HTTP_STATUS_CODES


def retry_delay_seconds(
    retry_after: str | None,
    *,
    fallback_delay: float,
    max_delay: float,
    now: datetime | None = None,
) -> float:
    delay = _retry_after_delay(retry_after, now=now) if retry_after else None
    if delay is None:
        delay = max(0.0, float(fallback_delay))
    return min(delay, max(0.0, float(max_delay)))


def _retry_after_delay(value: str, *, now: datetime | None) -> float | None:
    try:
        seconds = float(value.strip())
    except ValueError:
        seconds = None
    if seconds is not None:
        return max(0.0, seconds) if math.isfinite(seconds) else None

    try:
        retry_at = parsedate_to_datetime(value)
    except (TypeError, ValueError, OverflowError):
        return None
    if retry_at.tzinfo is None:
        retry_at = retry_at.replace(tzinfo=timezone.utc)
    current = now or datetime.now(timezone.utc)
    if current.tzinfo is None:
        current = current.replace(tzinfo=timezone.utc)
    return max(0.0, (retry_at - current).total_seconds())
