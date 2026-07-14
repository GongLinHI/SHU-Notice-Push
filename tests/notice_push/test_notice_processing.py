from datetime import datetime
import threading
import time

from notice_push.crawler.detail_fetcher import PreparedNotice
from notice_push.crawler.failures import FailureRetryPolicy
from notice_push.crawler.notice_processing import NoticeProcessor
from notice_push.domain import NoticeDetail, NoticeSource, NoticeSummary


class RecordingStorage:
    def __init__(self):
        self.saved_ids = []

    def save_summary(self, notice_id, summary):
        self.saved_ids.append(notice_id)

    def mark_failed(self, *args, **kwargs):
        raise AssertionError("summary should not fail")


class ConcurrentSummarizer:
    def __init__(self):
        self.active = 0
        self.max_active = 0
        self._lock = threading.Lock()

    def summarize(self, notice_id, detail, source_name=None):
        with self._lock:
            self.active += 1
            self.max_active = max(self.max_active, self.active)
        time.sleep(0.03)
        with self._lock:
            self.active -= 1
        return NoticeSummary(
            notice_id=notice_id,
            markdown=f"## {source_name}|行政|周常事务|{detail.title}",
            model="fake-model",
            prompt_version="test-v1",
            generated_at=datetime(2026, 7, 14, 8, 0),
        )


def test_notice_processor_summary_uses_explicit_worker_limit_and_preserves_order():
    source = NoticeSource(
        id="test_source",
        name="测试来源",
        base_url="https://example.com/",
        list_url="https://example.com/list.htm",
        adapter="tests.fake.Adapter",
    )
    prepared = tuple(
        PreparedNotice(
            source=source,
            notice_id=index,
            detail=NoticeDetail(
                source_id=source.id,
                url=f"https://example.com/{index}",
                canonical_url=f"https://example.com/{index}",
                title=f"通知 {index}",
                content="足够长的测试正文内容",
            ),
        )
        for index in (1, 2)
    )
    storage = RecordingStorage()
    summarizer = ConcurrentSummarizer()
    processor = NoticeProcessor(
        storage=storage,
        http_client=object(),
        summarizer=summarizer,
        detail_min_chars=10,
    )

    outcome = processor.summarize(
        prepared,
        max_workers=2,
        retry_policy=FailureRetryPolicy(limit=3, after_hours=0),
    )

    assert [entry.detail.title for entry in outcome.entries] == ["通知 1", "通知 2"]
    assert storage.saved_ids == [1, 2]
    assert summarizer.max_active == 2
