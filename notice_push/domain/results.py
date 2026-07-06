from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Optional

from notice_push.domain.audit import SourceAuditResult
from notice_push.domain.notices import FailedNotice, SourceError


@dataclass(frozen=True)
class RefreshSeenError:
    source_id: str
    source_name: str
    title: str
    url: str
    reason: str


@dataclass(frozen=True)
class PipelineSourceStats:
    source_id: str
    source_name: str
    summarized_count: int = 0
    failed_count: int = 0
    source_error_count: int = 0
    audit_error_count: int = 0
    audit_warning_count: int = 0
    refresh_seen_error_count: int = 0


@dataclass(frozen=True)
class StorageHealth:
    exists: bool
    source_count: int
    notice_count: int
    schema_versions: tuple[str, ...]


@dataclass(frozen=True)
class PipelineResult:
    report_path: Optional[Path]
    new_count: int
    summarized_count: int
    updated_count: int = 0
    retried_count: int = 0
    manual_review_count: int = 0
    failed: tuple[FailedNotice, ...] = field(default_factory=tuple)
    source_errors: tuple[SourceError, ...] = field(default_factory=tuple)
    audit_results: tuple[SourceAuditResult, ...] = field(default_factory=tuple)
    run_summary_path: Optional[Path] = None
    refresh_seen_errors: tuple[RefreshSeenError, ...] = field(default_factory=tuple)
    source_stats: tuple[PipelineSourceStats, ...] = field(default_factory=tuple)
    models_used: tuple[str, ...] = field(default_factory=tuple)
    media_counts: dict[str, int] = field(default_factory=dict)
    started_at: str = ""
    finished_at: str = ""
    duration_seconds: float = 0.0
    git_sha: str = ""


@dataclass(frozen=True)
class PipelineCounters:
    new_count: int
    updated_count: int
    retried_count: int
    summarized_count: int
    failed_count: int
    manual_review_count: int
    source_error_count: int
    audit_error_count: int
    audit_warning_count: int
    refresh_seen_error_count: int = 0


@dataclass(frozen=True)
class ReportStats:
    new_count: int
    retried_count: int
    summarized_count: int
    manual_review_count: int
    updated_count: int = 0
