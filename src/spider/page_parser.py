from __future__ import annotations

from datetime import datetime

from src.entry.notice import Notice
from src.notice_push.config import load_config
from src.notice_push.http import HttpClient
from src.notice_push.models import NoticeListItem
from src.notice_push.sources.shu_official import ShuOfficialAdapter


class PageParser:
    """Compatibility wrapper for the legacy Shanghai University detail parser."""

    @classmethod
    def parse(cls, notice: Notice, http_client: HttpClient | None = None) -> Notice:
        config = load_config(env={})
        source = config.source_by_id("shu_official")
        adapter = ShuOfficialAdapter(source)
        item = NoticeListItem(
            source_id=source.id,
            url=notice.url,
            canonical_url=notice.url,
            title=notice.title or "",
            published_at=datetime.combine(notice.upload_time, datetime.min.time()) if notice.upload_time else None,
        )
        html = (http_client or HttpClient()).get_text(notice.url)
        detail = adapter.parse_detail(html, item)
        return Notice(
            url=detail.url,
            title=detail.title,
            content=detail.content,
            upload_time=detail.published_at.date() if detail.published_at else None,
        )
