from __future__ import annotations

from dataclasses import dataclass, field


@dataclass(frozen=True)
class SourceAuditIssue:
    source_id: str
    source_name: str
    url: str
    severity: str
    reason: str


@dataclass(frozen=True)
class SourceAuditSample:
    title: str
    url: str
    content_kind: str
    content_length: int
    asset_count: int


@dataclass(frozen=True)
class SourceAuditResult:
    source_id: str
    source_name: str
    list_url: str
    list_item_count: int
    sampled_detail_url: str = ""
    detail_content_kind: str = ""
    samples: tuple[SourceAuditSample, ...] = field(default_factory=tuple)
    issues: tuple[SourceAuditIssue, ...] = field(default_factory=tuple)


@dataclass(frozen=True)
class AuditPolicy:
    min_list_items: int = 1
    sample_detail_count: int = 3
    required_content_kinds: tuple[str, ...] = ("text", "pdf", "image")
