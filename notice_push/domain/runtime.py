from __future__ import annotations

from dataclasses import dataclass
from datetime import date
from typing import Optional


@dataclass(frozen=True)
class PipelineRunOptions:
    source_ids: tuple[str, ...] = ()
    dry_run: bool = False
    limit: Optional[int] = None
    report_date: Optional[date] = None
    max_pages_per_source: Optional[int] = None
    stop_after_seen_pages: Optional[int] = None
    detail_max_workers: int = 1
    summary_max_workers: int = 1
    lookback_days: Optional[int] = None
    retry_failed: bool = False
    failed_retry_limit: int = 0
    failed_retry_after_hours: int = 0
    refresh_seen_details: bool = False
    refresh_seen_max_workers: int = 1
    refresh_seen_limit: int = 0
    bootstrap_seen: bool = False
    audit_sources: bool = True
    git_sha: str = ""


@dataclass(frozen=True)
class NoticeRuntimeProfile:
    name: str
    max_pages_per_source: Optional[int]
    stop_after_seen_pages: Optional[int]
    detail_max_workers: int
    summary_max_workers: int
    http_timeout: int
    http_max_retries: int
    http_initial_retry_delay: float
    http_retry_backoff: float
    http_max_retry_delay_seconds: int
    lookback_days: Optional[int]
    retry_failed: bool
    failed_retry_limit: int
    failed_retry_after_hours: int
    refresh_seen_details: bool
    refresh_seen_max_workers: int
    refresh_seen_limit: int
    llm_timeout: int
    llm_max_retries: int
    llm_initial_retry_delay: float
    llm_retry_backoff: float


@dataclass(frozen=True)
class LLMProviderConfig:
    name: str
    base_url: str
    api_key_env: str
    model_env: str
    default_model: str
    kind: str


@dataclass(frozen=True)
class ParsingConfig:
    external_video_domains: tuple[str, ...] = ("kankanews.com",)
    noise_image_markers: tuple[str, ...] = ("logo", "icon", "wx", "weixin", "qr", "blank", "spacer")


@dataclass(frozen=True)
class MediaPolicy:
    pdf_max_bytes: int = 20971520
    image_max_bytes: int = 8388608
    pdf_extracted_text_max_chars: int = 50000
