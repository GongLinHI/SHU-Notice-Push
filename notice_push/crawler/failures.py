from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class FailureRetryPolicy:
    limit: int = 0
    after_hours: int = 0


PERMANENT_FAILURE_TYPES = {"unsupported_video_content"}


class UnsupportedContentError(ValueError):
    pass


def classify_failure(exc: Exception, *, stage: str = "") -> str:
    message = str(exc).lower()
    if isinstance(exc, UnsupportedContentError) or "unsupported video content" in message:
        return "unsupported_video_content"
    if "api_key" in message or "must be provided for real" in message:
        return "api_key_missing"
    if "file upload" in message:
        return "kimi_file_upload"
    if "file extract" in message or "pdf extraction" in message:
        return "kimi_file_extract"
    if "downloaded media" in message or "media" in message and "download" in message:
        return "media_download"
    if "empty or too short" in message:
        return "detail_empty"
    if "timeout" in message:
        return f"{stage}_timeout" if stage else "timeout"
    if "rate" in message or "429" in message:
        return "llm_rate_limit"
    failure_name = type(exc).__name__
    return f"{stage}_{failure_name}" if stage else failure_name


def retry_limit_for_failure(failure_type: str, retry_limit: int) -> int:
    return 0 if failure_type in PERMANENT_FAILURE_TYPES else retry_limit


def is_retryable_failure_type(failure_type: str) -> bool:
    return failure_type not in PERMANENT_FAILURE_TYPES
