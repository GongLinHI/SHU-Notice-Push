from datetime import datetime

from notice_push.crawler.source_scan import scan_source_pages
from notice_push.domain import NoticeListItem, NoticeSource


class RecordingHttp:
    def __init__(self, pages):
        self.pages = pages
        self.requested = []

    def get_text(self, url):
        self.requested.append(url)
        return self.pages[url]


class LoopingAdapter:
    def __init__(self, source):
        self.source = source

    def parse_list_page(self, html, page_url):
        index = int(html.removeprefix("page-"))
        return [
            NoticeListItem(
                source_id=self.source.id,
                url=f"https://example.com/detail-{index}.htm",
                canonical_url=f"https://example.com/detail-{index}.htm",
                title=f"测试通知 {index}",
                published_at=datetime(2026, 7, index),
            )
        ]

    def find_next_page_url(self, html, page_url):
        if html == "page-1":
            return "https://example.com/page-2.htm"
        return page_url


def test_scan_source_stops_on_repeated_page_url():
    source = NoticeSource(
        id="test_source",
        name="测试来源",
        base_url="https://example.com/",
        list_url="https://example.com/list.htm",
        adapter="tests.fake.Adapter",
    )
    http = RecordingHttp(
        {
            source.list_url: "page-1",
            "https://example.com/page-2.htm": "page-2",
        }
    )

    outcome = scan_source_pages(
        source=source,
        adapter=LoopingAdapter(source),
        http_client=http,
        max_pages=5,
        cutoff=None,
    )

    assert outcome.page_count == 2
    assert outcome.stop_reason == "repeated_page_url"
    assert outcome.source_errors == ()
    assert http.requested == [source.list_url, "https://example.com/page-2.htm"]


def test_scan_source_respects_hard_page_limit():
    source = NoticeSource(
        id="test_source",
        name="测试来源",
        base_url="https://example.com/",
        list_url="https://example.com/list.htm",
        adapter="tests.fake.Adapter",
    )
    http = RecordingHttp(
        {
            source.list_url: "page-1",
            "https://example.com/page-2.htm": "page-2",
        }
    )

    outcome = scan_source_pages(
        source=source,
        adapter=LoopingAdapter(source),
        http_client=http,
        max_pages=1,
        cutoff=None,
    )

    assert outcome.page_count == 1
    assert outcome.stop_reason == "max_pages"
    assert http.requested == [source.list_url]
