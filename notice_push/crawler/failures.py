from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class FailureRetryPolicy:
    limit: int = 0
    after_hours: int = 0


class UnsupportedContentError(ValueError):
    pass


def classify_failure(exc: Exception, *, stage: str = "") -> str:
    message = str(exc).lower()
    if isinstance(exc, UnsupportedContentError) or "unsupported video content" in message:
        return "unsupported_video_content"
    if "empty or too short" in message:
        return "detail_empty"
    if "timeout" in message:
        return f"{stage}_timeout" if stage else "timeout"
    if "rate" in message or "429" in message:
        return "llm_rate_limit"
    failure_name = type(exc).__name__
    return f"{stage}_{failure_name}" if stage else failure_name
