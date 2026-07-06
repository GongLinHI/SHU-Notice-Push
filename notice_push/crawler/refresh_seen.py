from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor
from typing import Optional

from notice_push.crawler.detail_fetcher import is_summarizable_detail
from notice_push.domain import NoticeListItem, NoticeSource, RefreshSeenError


def update_seen_details_if_changed(
    *,
    source: NoticeSource,
    adapter,
    items: list[NoticeListItem],
    seen_rows: dict[str, object],
    http_client,
    storage,
    detail_min_chars: int,
    max_workers: Optional[int] = None,
) -> list[RefreshSeenError]:
    if not items:
        return []

    worker_count = min(max(1, max_workers or 1), len(items))

    def update_one(item: NoticeListItem) -> RefreshSeenError | None:
        try:
            detail_html = http_client.get_text(item.url)
            detail = adapter.parse_detail(detail_html, item)
            if not is_summarizable_detail(detail, detail_min_chars):
                return None
            notice_id = int(seen_rows[item.canonical_url]["id"])
            storage.update_seen_detail_if_changed(notice_id, detail)
            return None
        except Exception as exc:
            return RefreshSeenError(
                source_id=source.id,
                source_name=source.name,
                title=item.title,
                url=item.url,
                reason=str(exc),
            )

    with ThreadPoolExecutor(max_workers=worker_count) as executor:
        results = list(executor.map(update_one, items))
    return [error for error in results if error is not None]
