from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from datetime import datetime

from notice_push.crawler.list_scanner import items_within_lookback, page_is_before_cutoff
from notice_push.domain import NoticeListItem, NoticeSource, SourceError


@dataclass(frozen=True)
class ScannedListPage:
    url: str
    html: str
    items: tuple[NoticeListItem, ...]
    processable_items: tuple[NoticeListItem, ...]
    before_cutoff: bool


@dataclass(frozen=True)
class SourceScanOutcome:
    source_id: str
    pages: tuple[ScannedListPage, ...]
    stop_reason: str
    source_errors: tuple[SourceError, ...] = ()

    @property
    def page_count(self) -> int:
        return len(self.pages)


PageObserver = Callable[[ScannedListPage], str | None]


def scan_source_pages(
    *,
    source: NoticeSource,
    adapter,
    http_client,
    max_pages: int | float,
    cutoff: datetime | None,
    on_page: PageObserver | None = None,
) -> SourceScanOutcome:
    pages: list[ScannedListPage] = []
    page_url = source.list_url
    visited_page_urls: set[str] = set()
    stop_reason = "no_next_page"
    source_errors: tuple[SourceError, ...] = ()

    while page_url and len(pages) < max_pages:
        if page_url in visited_page_urls:
            stop_reason = "repeated_page_url"
            break
        visited_page_urls.add(page_url)
        try:
            list_html = http_client.get_text(page_url)
            list_items = adapter.parse_list_page(list_html, page_url)
        except Exception as exc:
            source_errors = (
                SourceError(
                    source_id=source.id,
                    source_name=source.name,
                    url=page_url,
                    reason=str(exc),
                ),
            )
            stop_reason = "source_error"
            break

        page = ScannedListPage(
            url=page_url,
            html=list_html,
            items=tuple(list_items),
            processable_items=tuple(items_within_lookback(list_items, cutoff)),
            before_cutoff=page_is_before_cutoff(list_items, cutoff),
        )
        pages.append(page)
        observer_stop_reason = on_page(page) if on_page is not None else None
        if observer_stop_reason:
            stop_reason = observer_stop_reason
            break
        if page.before_cutoff:
            stop_reason = "lookback_cutoff"
            break
        if len(pages) >= max_pages:
            stop_reason = "max_pages"
            break

        try:
            next_page_url = adapter.find_next_page_url(list_html, page_url)
        except Exception as exc:
            source_errors = (
                SourceError(
                    source_id=source.id,
                    source_name=source.name,
                    url=page_url,
                    reason=str(exc),
                ),
            )
            stop_reason = "source_error"
            break
        if not next_page_url:
            stop_reason = "no_next_page"
            break
        page_url = next_page_url

    return SourceScanOutcome(
        source_id=source.id,
        pages=tuple(pages),
        stop_reason=stop_reason,
        source_errors=source_errors,
    )
