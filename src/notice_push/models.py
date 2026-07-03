from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Optional


@dataclass(frozen=True)
class NoticeSource:
    id: str
    name: str
    base_url: str
    list_url: str
    adapter: str
    enabled: bool = True


@dataclass(frozen=True)
class Attachment:
    name: str
    url: str


@dataclass(frozen=True)
class NoticeAsset:
    kind: str
    role: str
    name: str
    url: str
    mime_type: str = ""


@dataclass(frozen=True)
class NoticeListItem:
    source_id: str
    url: str
    canonical_url: str
    title: str
    published_at: Optional[datetime] = None
    list_excerpt: str = ""


@dataclass(frozen=True)
class NoticeDetail:
    source_id: str
    url: str
    canonical_url: str
    title: str
    content: str
    published_at: Optional[datetime] = None
    list_excerpt: str = ""
    attachments: tuple[Attachment, ...] = field(default_factory=tuple)
    assets: tuple[NoticeAsset, ...] = field(default_factory=tuple)
    content_kind: str = "text"


@dataclass(frozen=True)
class NoticeSummary:
    notice_id: int
    markdown: str
    model: str
    prompt_version: str
    generated_at: datetime


@dataclass(frozen=True)
class FailedNotice:
    source_id: str
    title: str
    url: str
    reason: str
    published_at: Optional[datetime] = None
    source_name: str = ""


@dataclass(frozen=True)
class SourceError:
    source_id: str
    source_name: str
    url: str
    reason: str


@dataclass(frozen=True)
class PipelineResult:
    report_path: Optional[Path]
    new_count: int
    summarized_count: int
    failed: tuple[FailedNotice, ...] = field(default_factory=tuple)
    source_errors: tuple[SourceError, ...] = field(default_factory=tuple)


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


@dataclass(frozen=True)
class AppConfig:
    repo_root: Path
    state_path: Path
    output_dir: Path
    prompt_name: str
    deepseek_model: str
    llm_providers: dict[str, LLMProviderConfig]
    llm_routing: dict[str, str]
    detail_min_chars: int
    runtime_profiles: dict[str, NoticeRuntimeProfile]
    sources: tuple[NoticeSource, ...]

    def source_by_id(self, source_id: str) -> NoticeSource:
        for source in self.sources:
            if source.id == source_id:
                return source
        raise KeyError(source_id)

    def runtime_profile(self, profile_name: str) -> NoticeRuntimeProfile:
        try:
            return self.runtime_profiles[profile_name]
        except KeyError as exc:
            raise KeyError(profile_name) from exc
