from __future__ import annotations

from datetime import date, datetime, time, timedelta
from typing import Optional

from notice_push.domain import NoticeListItem


UNBOUNDED_PAGE_SCAN = float("inf")


def cutoff_datetime(report_day: date, lookback_days: Optional[int]) -> Optional[datetime]:
    if lookback_days is None or lookback_days <= 0:
        return None
    return datetime.combine(report_day, time.min) - timedelta(days=lookback_days)


def items_within_lookback(items: list[NoticeListItem], cutoff: Optional[datetime]) -> list[NoticeListItem]:
    if cutoff is None:
        return items
    return [item for item in items if item.published_at is None or item.published_at >= cutoff]


def item_key(item: NoticeListItem) -> tuple[str, str]:
    return item.source_id, item.canonical_url


def page_is_before_cutoff(items: list[NoticeListItem], cutoff: Optional[datetime]) -> bool:
    if cutoff is None or not items:
        return False
    dated_items = [item for item in items if item.published_at is not None]
    return bool(dated_items) and all(item.published_at < cutoff for item in dated_items)
