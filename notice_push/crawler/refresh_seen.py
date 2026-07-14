from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor
from typing import Optional

from notice_push.crawler.detail_fetcher import PreparedNotice, is_summarizable_detail
from notice_push.domain import NoticeListItem, NoticeSource, RefreshSeenError


def update_seen_details_if_changed(
    *,
    source: NoticeSource,
    adapter,
    items: list[NoticeListItem],
    seen_rows: dict[tuple[str, str], object],
    http_client,
    storage,
    detail_min_chars: int,
    max_workers: Optional[int] = None,
) -> tuple[list[PreparedNotice], list[RefreshSeenError]]:
    if not items:
        return [], []

    worker_count = min(max(1, max_workers or 1), len(items))

    def update_one(item: NoticeListItem) -> tuple[PreparedNotice | None, RefreshSeenError | None]:
        try:
            detail_html = http_client.get_text(item.url)
            detail = adapter.parse_detail(detail_html, item)
            if not is_summarizable_detail(detail, detail_min_chars):
                return None, None
            notice_id = int(seen_rows[(item.source_id, item.canonical_url)]["id"])
            changed = storage.update_seen_detail_if_changed(notice_id, detail)
            if changed:
                return PreparedNotice(source=source, notice_id=notice_id, detail=detail), None
            return None, None
        except Exception as exc:
            return (
                None,
                RefreshSeenError(
                    source_id=source.id,
                    source_name=source.name,
                    title=item.title,
                    url=item.url,
                    reason=str(exc),
                ),
            )

    with ThreadPoolExecutor(max_workers=worker_count) as executor:
        results = list(executor.map(update_one, items))
    prepared = [result[0] for result in results if result[0] is not None]
    errors = [result[1] for result in results if result[1] is not None]
    return prepared, errors
