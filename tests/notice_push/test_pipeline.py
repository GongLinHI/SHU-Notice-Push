from datetime import date, datetime
import threading

from src.notice_push.config import load_config
from src.notice_push.models import NoticeDetail, NoticeListItem, NoticeSummary
from src.notice_push.pipeline import NoticePipeline, create_adapter
from src.notice_push.storage import NoticeStorage


class FakeHttp:
    def __init__(self, pages):
        self.pages = pages
        self.requested = []

    def get_text(self, url):
        self.requested.append(url)
        return self.pages[url]


class FakeAdapter:
    def __init__(self, source):
        self.source = source

    def parse_list_page(self, html, page_url):
        if html == "list-1":
            return [
                NoticeListItem(
                    source_id=self.source.id,
                    url="https://example.com/detail-1.htm",
                    canonical_url="https://example.com/detail-1.htm",
                    title="测试通知 1",
                    published_at=datetime(2026, 6, 16),
                    list_excerpt="列表摘要",
                )
            ]
        return []

    def find_next_page_url(self, html, page_url):
        return "https://example.com/page-2.htm" if html == "list-1" else None

    def parse_detail(self, html, item):
        return NoticeDetail(
            source_id=item.source_id,
            url=item.url,
            canonical_url=item.canonical_url,
            title=item.title,
            content="这是一段足够长的详情页正文，用于测试摘要链路，并确保超过最小正文长度限制。",
            published_at=item.published_at,
            list_excerpt=item.list_excerpt,
        )


class FakeSummarizer:
    def __init__(self):
        self.details = []

    def summarize(self, notice_id, detail, source_name=None):
        self.details.append(detail)
        return NoticeSummary(
            notice_id=notice_id,
            markdown=f"## {source_name}|行政|周常事务|{detail.title}",
            model="fake-model",
            prompt_version="notice_summary_v1",
            generated_at=datetime(2026, 6, 30, 8, 0),
        )


class FailingSummarizer:
    def summarize(self, notice_id, detail, source_name=None):
        raise RuntimeError("rate limited")


class MultiItemAdapter(FakeAdapter):
    def parse_list_page(self, html, page_url):
        if html == "list-1":
            return [
                NoticeListItem(
                    source_id=self.source.id,
                    url=f"https://example.com/detail-{index}.htm",
                    canonical_url=f"https://example.com/detail-{index}.htm",
                    title=f"测试通知 {index}",
                    published_at=datetime(2026, 6, 16),
                    list_excerpt="列表摘要",
                )
                for index in range(1, 5)
            ]
        return []


class DatedPagingAdapter(FakeAdapter):
    def parse_list_page(self, html, page_url):
        if html == "recent":
            return [
                NoticeListItem(
                    source_id=self.source.id,
                    url="https://example.com/recent.htm",
                    canonical_url="https://example.com/recent.htm",
                    title="近一年通知",
                    published_at=datetime(2026, 6, 1),
                )
            ]
        if html == "old":
            return [
                NoticeListItem(
                    source_id=self.source.id,
                    url="https://example.com/old.htm",
                    canonical_url="https://example.com/old.htm",
                    title="一年以前通知",
                    published_at=datetime(2024, 12, 31),
                )
            ]
        return []

    def find_next_page_url(self, html, page_url):
        if html == "recent":
            return "https://example.com/page-old.htm"
        return None


class FivePageAdapter(FakeAdapter):
    def parse_list_page(self, html, page_url):
        if html.startswith("list-"):
            page_number = int(html.removeprefix("list-"))
            return [
                NoticeListItem(
                    source_id=self.source.id,
                    url=f"https://example.com/detail-{page_number}.htm",
                    canonical_url=f"https://example.com/detail-{page_number}.htm",
                    title=f"测试通知 {page_number}",
                    published_at=datetime(2026, 6, 16),
                    list_excerpt="列表摘要",
                )
            ]
        return []

    def find_next_page_url(self, html, page_url):
        page_number = int(html.removeprefix("list-"))
        if page_number >= 5:
            return None
        return f"https://example.com/page-{page_number + 1}.htm"


class LoopingAdapter(FakeAdapter):
    def find_next_page_url(self, html, page_url):
        return page_url


class RecordingHttp:
    def __init__(self, source_list_url):
        self.source_list_url = source_list_url
        self.events = []
        self._lock = threading.Lock()

    def get_text(self, url):
        with self._lock:
            self.events.append(("start", url))
        if url == self.source_list_url:
            return "list-1"
        with self._lock:
            self.events.append(("end", url))
        return "detail"


def test_pipeline_dry_run_fetches_list_and_detail_without_mutating_state(tmp_path):
    config = load_config(
        env={},
        repo_root=tmp_path,
        state_path=tmp_path / "state.sqlite3",
        output_dir=tmp_path / "results",
    )
    source = config.source_by_id("shu_official")
    http = FakeHttp(
        {
            source.list_url: "list-1",
            "https://example.com/detail-1.htm": "detail",
            "https://example.com/page-2.htm": "list-2",
        }
    )
    storage = NoticeStorage(config.state_path, config.sources)
    summarizer = FakeSummarizer()
    pipeline = NoticePipeline(
        config=config,
        storage=storage,
        http_client=http,
        summarizer=summarizer,
        adapter_factory=lambda selected_source: FakeAdapter(selected_source),
    )

    result = pipeline.run(
        source_ids=["shu_official"],
        dry_run=True,
        limit=1,
        max_pages_per_source=2,
        report_date=date(2026, 6, 30),
    )

    assert result.new_count == 1
    assert result.summarized_count == 0
    assert summarizer.details == []
    assert config.state_path.exists() is False
    assert config.output_dir.exists() is False
    assert http.requested == [source.list_url, "https://example.com/detail-1.htm", "https://example.com/page-2.htm"]


def test_pipeline_run_persists_summary_and_writes_report(tmp_path):
    config = load_config(
        env={},
        repo_root=tmp_path,
        state_path=tmp_path / "state.sqlite3",
        output_dir=tmp_path / "results",
    )
    source = config.source_by_id("shu_official")
    http = FakeHttp({source.list_url: "list-1", "https://example.com/detail-1.htm": "detail"})
    storage = NoticeStorage(config.state_path, config.sources)
    summarizer = FakeSummarizer()
    pipeline = NoticePipeline(
        config=config,
        storage=storage,
        http_client=http,
        summarizer=summarizer,
        adapter_factory=lambda selected_source: FakeAdapter(selected_source),
    )

    result = pipeline.run(
        source_ids=["shu_official"],
        dry_run=False,
        limit=1,
        max_pages_per_source=1,
        report_date=date(2026, 6, 30),
    )

    assert result.new_count == 1
    assert result.summarized_count == 1
    assert result.report_path == tmp_path / "results" / "2026-06-30.md"
    assert "## 上海大学官网|行政|周常事务|测试通知 1" in result.report_path.read_text(encoding="utf-8")
    assert storage.find_by_source_url("shu_official", "https://example.com/detail-1.htm")["status"] == "summarized"


def test_pipeline_retries_failed_notices_when_retry_policy_allows(tmp_path):
    config = load_config(
        env={},
        repo_root=tmp_path,
        state_path=tmp_path / "state.sqlite3",
        output_dir=tmp_path / "results",
    )
    source = config.source_by_id("shu_official")
    item = NoticeListItem(
        source_id=source.id,
        url="https://example.com/detail-1.htm",
        canonical_url="https://example.com/detail-1.htm",
        title="测试通知 1",
        published_at=datetime(2026, 6, 16),
        list_excerpt="列表摘要",
    )
    storage = NoticeStorage(config.state_path, config.sources)
    storage.initialize()
    notice_id = storage.upsert_seen_item(item)
    storage.mark_failed(notice_id, "temporary detail error", failure_type="detail_empty", retry_after_hours=0, retry_limit=3)

    http = FakeHttp({source.list_url: "list-1", "https://example.com/detail-1.htm": "detail"})
    summarizer = FakeSummarizer()
    pipeline = NoticePipeline(
        config=config,
        storage=storage,
        http_client=http,
        summarizer=summarizer,
        adapter_factory=lambda selected_source: FakeAdapter(selected_source),
    )

    result = pipeline.run(
        source_ids=["shu_official"],
        dry_run=False,
        limit=1,
        max_pages_per_source=1,
        report_date=date(2026, 6, 30),
        retry_failed=True,
        failed_retry_limit=3,
    )

    assert result.new_count == 1
    assert result.summarized_count == 1
    assert storage.find_by_source_url("shu_official", item.canonical_url)["status"] == "summarized"


def test_pipeline_preserves_failure_count_across_summary_retries(tmp_path):
    config = load_config(
        env={},
        repo_root=tmp_path,
        state_path=tmp_path / "state.sqlite3",
        output_dir=tmp_path / "results",
    )
    source = config.source_by_id("shu_official")
    storage = NoticeStorage(config.state_path, config.sources)
    pipeline = NoticePipeline(
        config=config,
        storage=storage,
        http_client=FakeHttp({source.list_url: "list-1", "https://example.com/detail-1.htm": "detail"}),
        summarizer=FailingSummarizer(),
        adapter_factory=lambda selected_source: FakeAdapter(selected_source),
    )

    for _ in range(2):
        pipeline.run(
            source_ids=["shu_official"],
            dry_run=False,
            limit=1,
            max_pages_per_source=1,
            report_date=date(2026, 6, 30),
            retry_failed=True,
            failed_retry_limit=3,
            failed_retry_after_hours=0,
        )

    row = storage.find_by_source_url("shu_official", "https://example.com/detail-1.htm")
    assert row["status"] == "failed"
    assert row["failure_type"] == "llm_rate_limit"
    assert row["failure_count"] == 2


def test_pipeline_defaults_to_daily_retry_failed_when_not_explicit(tmp_path):
    config = load_config(
        env={},
        repo_root=tmp_path,
        state_path=tmp_path / "state.sqlite3",
        output_dir=tmp_path / "results",
    )
    source = config.source_by_id("shu_official")
    item = NoticeListItem(
        source_id=source.id,
        url="https://example.com/detail-1.htm",
        canonical_url="https://example.com/detail-1.htm",
        title="测试通知 1",
        published_at=datetime(2026, 6, 16),
        list_excerpt="列表摘要",
    )
    storage = NoticeStorage(config.state_path, config.sources)
    storage.initialize()
    notice_id = storage.upsert_seen_item(item)
    storage.mark_failed(notice_id, "temporary detail error", failure_type="detail_empty", retry_after_hours=0, retry_limit=3)

    pipeline = NoticePipeline(
        config=config,
        storage=storage,
        http_client=FakeHttp({source.list_url: "list-1", "https://example.com/detail-1.htm": "detail"}),
        summarizer=FakeSummarizer(),
        adapter_factory=lambda selected_source: FakeAdapter(selected_source),
    )

    result = pipeline.run(
        source_ids=["shu_official"],
        dry_run=False,
        limit=1,
        max_pages_per_source=1,
        report_date=date(2026, 6, 30),
    )

    assert result.new_count == 1
    assert storage.find_by_source_url("shu_official", item.canonical_url)["status"] == "summarized"


def test_pipeline_continues_when_one_source_directory_page_fails(tmp_path):
    config = load_config(
        env={},
        repo_root=tmp_path,
        state_path=tmp_path / "state.sqlite3",
        output_dir=tmp_path / "results",
    )
    management_source = config.source_by_id("management_school")
    http = FakeHttp({management_source.list_url: "list-1", "https://example.com/detail-1.htm": "detail"})
    storage = NoticeStorage(config.state_path, config.sources)
    pipeline = NoticePipeline(
        config=config,
        storage=storage,
        http_client=http,
        summarizer=FakeSummarizer(),
        adapter_factory=lambda selected_source: FakeAdapter(selected_source),
    )

    result = pipeline.run(
        source_ids=["shu_official", "management_school"],
        dry_run=False,
        limit=1,
        max_pages_per_source=1,
        report_date=date(2026, 6, 30),
    )

    markdown = result.report_path.read_text(encoding="utf-8")
    assert result.new_count == 1
    assert result.summarized_count == 1
    assert result.failed == ()
    assert len(result.source_errors) == 1
    assert result.source_errors[0].source_name == "上海大学官网"
    assert "上海大学管理学院|行政|周常事务|测试通知 1" in markdown
    assert "上海大学官网目录页抓取失败" not in markdown


def test_pipeline_records_source_directory_failure_without_creating_report(tmp_path):
    config = load_config(
        env={},
        repo_root=tmp_path,
        state_path=tmp_path / "state.sqlite3",
        output_dir=tmp_path / "results",
    )
    source = config.source_by_id("shu_official")
    http = FakeHttp({})
    storage = NoticeStorage(config.state_path, config.sources)
    pipeline = NoticePipeline(
        config=config,
        storage=storage,
        http_client=http,
        summarizer=FakeSummarizer(),
        adapter_factory=lambda selected_source: FakeAdapter(selected_source),
    )

    result = pipeline.run(
        source_ids=["shu_official"],
        dry_run=False,
        limit=1,
        max_pages_per_source=1,
        report_date=date(2026, 6, 30),
    )

    assert result.new_count == 0
    assert result.failed == ()
    assert len(result.source_errors) == 1
    assert result.source_errors[0].source_id == source.id
    assert result.report_path is None


def test_pipeline_allows_unbounded_page_scan_when_profile_requests_backfill(tmp_path):
    config = load_config(
        env={},
        repo_root=tmp_path,
        state_path=tmp_path / "state.sqlite3",
        output_dir=tmp_path / "results",
    )
    source = config.source_by_id("shu_official")
    http = FakeHttp(
        {
            source.list_url: "list-1",
            "https://example.com/detail-1.htm": "detail",
            "https://example.com/page-2.htm": "list-2",
        }
    )
    storage = NoticeStorage(config.state_path, config.sources)
    pipeline = NoticePipeline(
        config=config,
        storage=storage,
        http_client=http,
        summarizer=FakeSummarizer(),
        adapter_factory=lambda selected_source: FakeAdapter(selected_source),
    )

    pipeline.run(
        source_ids=["shu_official"],
        dry_run=False,
        limit=None,
        max_pages_per_source=None,
        stop_after_seen_pages=None,
        report_date=date(2026, 6, 30),
    )

    assert http.requested == [source.list_url, "https://example.com/detail-1.htm", "https://example.com/page-2.htm"]


def test_pipeline_defaults_to_daily_profile_when_runtime_limits_are_not_explicit(tmp_path):
    config = load_config(
        env={},
        repo_root=tmp_path,
        state_path=tmp_path / "state.sqlite3",
        output_dir=tmp_path / "results",
    )
    source = config.source_by_id("shu_official")
    http = FakeHttp(
        {
            source.list_url: "list-1",
            "https://example.com/detail-1.htm": "detail",
            "https://example.com/page-2.htm": "list-2",
            "https://example.com/detail-2.htm": "detail",
            "https://example.com/page-3.htm": "list-3",
            "https://example.com/detail-3.htm": "detail",
            "https://example.com/page-4.htm": "list-4",
            "https://example.com/detail-4.htm": "detail",
            "https://example.com/page-5.htm": "list-5",
            "https://example.com/detail-5.htm": "detail",
        }
    )
    pipeline = NoticePipeline(
        config=config,
        storage=NoticeStorage(config.state_path, config.sources),
        http_client=http,
        summarizer=FakeSummarizer(),
        adapter_factory=lambda selected_source: FivePageAdapter(selected_source),
    )

    result = pipeline.run(
        source_ids=["shu_official"],
        dry_run=False,
        stop_after_seen_pages=None,
        report_date=date(2026, 6, 30),
    )

    requested_list_pages = [url for url in http.requested if "detail-" not in url]
    assert result.new_count == 5
    assert requested_list_pages == [
        source.list_url,
        "https://example.com/page-2.htm",
        "https://example.com/page-3.htm",
        "https://example.com/page-4.htm",
        "https://example.com/page-5.htm",
    ]


def test_pipeline_stops_backfill_after_notices_older_than_window(tmp_path):
    config = load_config(
        env={},
        repo_root=tmp_path,
        state_path=tmp_path / "state.sqlite3",
        output_dir=tmp_path / "results",
    )
    source = config.source_by_id("shu_official")
    http = FakeHttp(
        {
            source.list_url: "recent",
            "https://example.com/recent.htm": "detail",
            "https://example.com/page-old.htm": "old",
        }
    )
    pipeline = NoticePipeline(
        config=config,
        storage=NoticeStorage(config.state_path, config.sources),
        http_client=http,
        summarizer=FakeSummarizer(),
        adapter_factory=lambda selected_source: DatedPagingAdapter(selected_source),
    )

    result = pipeline.run(
        source_ids=["shu_official"],
        dry_run=False,
        max_pages_per_source=None,
        stop_after_seen_pages=None,
        report_date=date(2026, 7, 1),
        lookback_days=365,
    )

    assert result.new_count == 1
    assert "https://example.com/old.htm" not in http.requested


def test_pipeline_defaults_to_daily_lookback_when_not_explicit(tmp_path):
    config = load_config(
        env={},
        repo_root=tmp_path,
        state_path=tmp_path / "state.sqlite3",
        output_dir=tmp_path / "results",
    )
    source = config.source_by_id("shu_official")
    http = FakeHttp(
        {
            source.list_url: "recent",
            "https://example.com/recent.htm": "detail",
            "https://example.com/page-old.htm": "old",
        }
    )
    pipeline = NoticePipeline(
        config=config,
        storage=NoticeStorage(config.state_path, config.sources),
        http_client=http,
        summarizer=FakeSummarizer(),
        adapter_factory=lambda selected_source: DatedPagingAdapter(selected_source),
    )

    result = pipeline.run(
        source_ids=["shu_official"],
        dry_run=False,
        report_date=date(2026, 7, 1),
    )

    assert result.new_count == 1
    assert "https://example.com/old.htm" not in http.requested


def test_pipeline_stops_when_next_page_repeats_current_url(tmp_path):
    config = load_config(
        env={},
        repo_root=tmp_path,
        state_path=tmp_path / "state.sqlite3",
        output_dir=tmp_path / "results",
    )
    source = config.source_by_id("shu_official")
    http = FakeHttp({source.list_url: "list-1", "https://example.com/detail-1.htm": "detail"})
    pipeline = NoticePipeline(
        config=config,
        storage=NoticeStorage(config.state_path, config.sources),
        http_client=http,
        summarizer=FakeSummarizer(),
        adapter_factory=lambda selected_source: LoopingAdapter(selected_source),
    )

    pipeline.run(
        source_ids=["shu_official"],
        dry_run=False,
        max_pages_per_source=None,
        stop_after_seen_pages=None,
        report_date=date(2026, 7, 1),
    )

    assert http.requested.count(source.list_url) == 1


def test_pipeline_fetches_detail_pages_with_small_thread_pool(tmp_path):
    config = load_config(
        env={},
        repo_root=tmp_path,
        state_path=tmp_path / "state.sqlite3",
        output_dir=tmp_path / "results",
    )
    source = config.source_by_id("shu_official")
    http = RecordingHttp(source.list_url)
    storage = NoticeStorage(config.state_path, config.sources)
    pipeline = NoticePipeline(
        config=config,
        storage=storage,
        http_client=http,
        summarizer=FakeSummarizer(),
        adapter_factory=lambda selected_source: MultiItemAdapter(selected_source),
    )

    result = pipeline.run(
        source_ids=["shu_official"],
        dry_run=False,
        limit=None,
        max_pages_per_source=1,
        stop_after_seen_pages=1,
        detail_max_workers=2,
        summary_max_workers=1,
        report_date=date(2026, 6, 30),
    )

    detail_starts = [url for event, url in http.events if event == "start" and url != source.list_url]
    detail_ends = [url for event, url in http.events if event == "end"]

    assert result.new_count == 4
    assert result.summarized_count == 4
    assert len(detail_starts) == 4
    assert len(detail_ends) == 4


def test_pipeline_updates_seen_notice_detail_hash_without_resummarizing(tmp_path):
    config = load_config(
        env={},
        repo_root=tmp_path,
        state_path=tmp_path / "state.sqlite3",
        output_dir=tmp_path / "results",
    )
    source = config.source_by_id("shu_official")
    storage = NoticeStorage(config.state_path, config.sources)
    storage.initialize()
    item = NoticeListItem(
        source_id=source.id,
        url="https://example.com/detail-1.htm",
        canonical_url="https://example.com/detail-1.htm",
        title="测试通知 1",
        published_at=datetime(2026, 6, 16),
        list_excerpt="列表摘要",
    )
    notice_id = storage.upsert_seen_item(item)
    storage.save_detail(
        notice_id,
        NoticeDetail(
            source_id=item.source_id,
            url=item.url,
            canonical_url=item.canonical_url,
            title=item.title,
            content="旧详情正文",
            published_at=item.published_at,
            list_excerpt=item.list_excerpt,
        ),
    )

    class ChangedDetailAdapter(FakeAdapter):
        def parse_detail(self, html, item):
            detail = super().parse_detail(html, item)
            return NoticeDetail(
                source_id=detail.source_id,
                url=detail.url,
                canonical_url=detail.canonical_url,
                title=detail.title,
                content="这是一段足够长的新详情页正文，用于更新已见通知的 content_hash。",
                published_at=detail.published_at,
                list_excerpt=detail.list_excerpt,
            )

    http = FakeHttp({source.list_url: "list-1", "https://example.com/detail-1.htm": "detail"})
    summarizer = FakeSummarizer()
    pipeline = NoticePipeline(
        config=config,
        storage=storage,
        http_client=http,
        summarizer=summarizer,
        adapter_factory=lambda selected_source: ChangedDetailAdapter(selected_source),
    )

    result = pipeline.run(
        source_ids=["shu_official"],
        dry_run=False,
        limit=1,
        max_pages_per_source=1,
        stop_after_seen_pages=1,
        refresh_seen_details=True,
        report_date=date(2026, 6, 30),
    )

    row = storage.find_by_source_url("shu_official", item.canonical_url)
    assert result.new_count == 0
    assert result.report_path is None
    assert summarizer.details == []
    assert row["status"] == "updated_seen"
    assert "新详情页正文" in row["content"]


def test_pipeline_skips_seen_detail_refresh_when_disabled(tmp_path):
    config = load_config(
        env={},
        repo_root=tmp_path,
        state_path=tmp_path / "state.sqlite3",
        output_dir=tmp_path / "results",
    )
    source = config.source_by_id("shu_official")
    storage = NoticeStorage(config.state_path, config.sources)
    storage.initialize()
    item = NoticeListItem(
        source_id=source.id,
        url="https://example.com/detail-1.htm",
        canonical_url="https://example.com/detail-1.htm",
        title="测试通知 1",
        published_at=datetime(2026, 6, 16),
        list_excerpt="列表摘要",
    )
    notice_id = storage.upsert_seen_item(item)
    storage.save_detail(
        notice_id,
        NoticeDetail(
            source_id=item.source_id,
            url=item.url,
            canonical_url=item.canonical_url,
            title=item.title,
            content="旧详情正文",
            published_at=item.published_at,
            list_excerpt=item.list_excerpt,
        ),
    )
    http = FakeHttp({source.list_url: "list-1", "https://example.com/detail-1.htm": "detail"})
    pipeline = NoticePipeline(
        config=config,
        storage=storage,
        http_client=http,
        summarizer=FakeSummarizer(),
        adapter_factory=lambda selected_source: FakeAdapter(selected_source),
    )

    pipeline.run(
        source_ids=["shu_official"],
        dry_run=False,
        max_pages_per_source=1,
        stop_after_seen_pages=1,
        refresh_seen_details=False,
        report_date=date(2026, 6, 30),
    )

    row = storage.find_by_source_url("shu_official", item.canonical_url)
    assert row["status"] == "detailed"
    assert http.requested == [source.list_url]


def test_create_adapter_loads_adapter_from_import_path(tmp_path):
    config = load_config(env={}, repo_root=tmp_path)
    source = config.source_by_id("shu_official")
    import_path_source = type(source)(
        id=source.id,
        name=source.name,
        base_url=source.base_url,
        list_url=source.list_url,
        adapter="src.notice_push.sources.shu_official.ShuOfficialAdapter",
        enabled=source.enabled,
    )

    from src.notice_push.sources.shu_official import ShuOfficialAdapter

    adapter = create_adapter(import_path_source)

    assert isinstance(adapter, ShuOfficialAdapter)
