from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
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
    failure_type: str = ""


@dataclass(frozen=True)
class SourceError:
    source_id: str
    source_name: str
    url: str
    reason: str
