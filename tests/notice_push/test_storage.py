import sqlite3
from datetime import datetime

import pytest

pytestmark = pytest.mark.usefixtures("seed_runtime_config_for_temporary_repo")

from notice_push.settings.loader import load_config
from notice_push.crawler import failures
from notice_push.crawler.failures import FailureRetryPolicy
from notice_push.domain import Attachment, NoticeAsset, NoticeDetail, NoticeListItem, NoticeSummary
from notice_push.storage import NoticeStorage


def make_item(source_id: str, url: str, title: str = "测试通知") -> NoticeListItem:
    return NoticeListItem(
        source_id=source_id,
        url=url,
        canonical_url=url,
        title=title,
        published_at=datetime(2026, 6, 16),
        list_excerpt="列表摘要",
    )


def classify(storage, items, *, retry_failed=False, failed_retry_limit=0):
    return storage.classify_pipeline_items(
        items,
        retry_failed=retry_failed,
        retry_policy=FailureRetryPolicy(limit=failed_retry_limit, after_hours=0),
    )


def test_storage_initializes_sources_and_deduplicates_per_source(tmp_path):
    config = load_config(env={}, repo_root=tmp_path)
    storage = NoticeStorage(tmp_path / "state.sqlite3", config.sources)
    storage.initialize()

    item = make_item("shu_official", "https://example.com/notice.htm")
    same_url_other_source = make_item("management_school", "https://example.com/notice.htm")

    selection = classify(storage, [item, same_url_other_source])
    assert selection.new_items == (item, same_url_other_source)
    assert selection.retry_items == ()
    assert selection.updated_seen == ()

    storage.upsert_seen_item(item)

    selection = classify(storage, [item, same_url_other_source])
    assert selection.new_items == (same_url_other_source,)
    assert selection.retry_items == ()
    assert selection.updated_seen == ()
    assert storage.count_sources() == 3


def test_storage_touches_seen_items_without_resending(tmp_path):
    config = load_config(env={}, repo_root=tmp_path)
    storage = NoticeStorage(tmp_path / "state.sqlite3", config.sources)
    storage.initialize()
    item = make_item("shu_official", "https://example.com/notice.htm", title="旧标题")
    storage.upsert_seen_item(item)
    before = storage.find_by_source_url(item.source_id, item.canonical_url)

    updated_item = make_item("shu_official", "https://example.com/notice.htm", title="新标题")

    selection = classify(storage, [updated_item])
    assert selection.new_items == ()
    assert selection.retry_items == ()
    assert selection.updated_seen == ()

    after = storage.find_by_source_url(item.source_id, item.canonical_url)
    assert after["title"] == "新标题"
    assert after["first_seen_at"] == before["first_seen_at"]
    assert after["last_seen_at"] >= before["last_seen_at"]


def test_storage_saves_detail_summary_and_failure(tmp_path):
    config = load_config(env={}, repo_root=tmp_path)
    storage = NoticeStorage(tmp_path / "state.sqlite3", config.sources)
    storage.initialize()
    item = make_item("shu_official", "https://example.com/detail.htm")
    notice_id = storage.upsert_seen_item(item)

    storage.save_detail(
        notice_id,
        NoticeDetail(
            source_id=item.source_id,
            url=item.url,
            canonical_url=item.canonical_url,
            title=item.title,
            content="详情页正文",
            published_at=item.published_at,
            list_excerpt=item.list_excerpt,
        ),
    )
    storage.save_summary(
        notice_id,
        NoticeSummary(
            notice_id=notice_id,
            markdown="## 官网|行政|周常事务|测试通知",
            model="deepseek-chat",
            prompt_version="notice_summary_v1",
            generated_at=datetime(2026, 6, 16, 8, 0),
        ),
    )
    storage.mark_failed(notice_id, "detail too short", failure_type="detail_empty", retry_after_hours=0, retry_limit=3)

    row = storage.get_notice(notice_id)

    assert row["content"] == "详情页正文"
    assert row["summary"] == "## 官网|行政|周常事务|测试通知"
    assert row["summary_model"] == "deepseek-chat"
    assert row["summary_prompt_version"] == "notice_summary_v1"
    assert row["status"] == "failed"
    assert row["error_message"] == "detail too short"
    assert row["failure_type"] == "detail_empty"
    assert row["failure_count"] == 1
    assert row["next_retry_at"] is not None


def test_storage_returns_retryable_failed_items_until_retry_limit(tmp_path):
    config = load_config(env={}, repo_root=tmp_path)
    storage = NoticeStorage(tmp_path / "state.sqlite3", config.sources)
    storage.initialize()
    item = make_item("shu_official", "https://example.com/retry.htm")
    notice_id = storage.upsert_seen_item(item)
    storage.mark_failed(notice_id, "temporary empty detail", failure_type="detail_empty", retry_after_hours=0, retry_limit=2)

    selection = classify(storage, [item], retry_failed=True, failed_retry_limit=2)
    assert selection.retry_items == (item,)

    storage.mark_failed(notice_id, "temporary empty detail again", failure_type="detail_empty", retry_after_hours=0, retry_limit=2)

    selection = classify(storage, [item], retry_failed=True, failed_retry_limit=2)
    assert selection.new_items == ()
    assert selection.retry_items == ()
    assert selection.updated_seen == ()


def test_storage_uses_central_failure_retry_classification(monkeypatch, tmp_path):
    config = load_config(env={}, repo_root=tmp_path)
    storage = NoticeStorage(tmp_path / "state.sqlite3", config.sources)
    storage.initialize()
    item = make_item("shu_official", "https://example.com/permanent.htm")
    notice_id = storage.upsert_seen_item(item)
    storage.mark_failed(notice_id, "permanent", failure_type="custom_permanent", retry_after_hours=0, retry_limit=3)
    monkeypatch.setattr(failures, "PERMANENT_FAILURE_TYPES", {"custom_permanent"})

    selection = classify(storage, [item], retry_failed=True, failed_retry_limit=3)
    assert selection.new_items == ()
    assert selection.retry_items == ()
    assert selection.updated_seen == ()


def test_storage_splits_first_seen_and_retryable_failed_items(tmp_path):
    config = load_config(env={}, repo_root=tmp_path)
    storage = NoticeStorage(tmp_path / "state.sqlite3", config.sources)
    storage.initialize()
    retry_item = make_item("shu_official", "https://example.com/retry.htm")
    new_item = make_item("shu_official", "https://example.com/new.htm")
    notice_id = storage.upsert_seen_item(retry_item)
    storage.mark_failed(notice_id, "temporary empty detail", failure_type="detail_empty", retry_after_hours=0, retry_limit=3)

    selection = classify(
        storage,
        [retry_item, new_item],
        retry_failed=True,
        failed_retry_limit=3,
    )

    assert selection.new_items == (new_item,)
    assert selection.retry_items == (retry_item,)
    assert selection.updated_seen == ()


def test_storage_updates_changed_seen_detail_without_resending(tmp_path):
    config = load_config(env={}, repo_root=tmp_path)
    storage = NoticeStorage(tmp_path / "state.sqlite3", config.sources)
    storage.initialize()
    item = make_item("shu_official", "https://example.com/detail.htm")
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
    before = storage.get_notice(notice_id)

    changed = storage.update_seen_detail_if_changed(
        notice_id,
        NoticeDetail(
            source_id=item.source_id,
            url=item.url,
            canonical_url=item.canonical_url,
            title=item.title,
            content="新详情正文",
            published_at=item.published_at,
            list_excerpt=item.list_excerpt,
        ),
    )

    after = storage.get_notice(notice_id)
    assert changed is True
    assert after["content"] == "新详情正文"
    assert after["content_hash"] != before["content_hash"]
    assert after["status"] == "updated_seen"
    assert after["summary"] == ""


def test_storage_clears_failure_metadata_when_seen_detail_is_updated(tmp_path):
    config = load_config(env={}, repo_root=tmp_path)
    storage = NoticeStorage(tmp_path / "state.sqlite3", config.sources)
    storage.initialize()
    item = make_item("shu_official", "https://example.com/detail.htm")
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
    storage.mark_failed(notice_id, "temporary failure", failure_type="detail_empty", retry_after_hours=1, retry_limit=3)

    storage.update_seen_detail_if_changed(
        notice_id,
        NoticeDetail(
            source_id=item.source_id,
            url=item.url,
            canonical_url=item.canonical_url,
            title=item.title,
            content="这是一段足够长的新详情正文，用于清理失败重试元数据。",
            published_at=item.published_at,
            list_excerpt=item.list_excerpt,
        ),
    )

    row = storage.get_notice(notice_id)
    assert row["status"] == "updated_seen"
    assert row["error_message"] == ""
    assert row["failure_type"] == ""
    assert row["failure_count"] == 0
    assert row["last_failed_at"] is None
    assert row["next_retry_at"] is None


def test_storage_save_detail_keeps_summary_failure_retry_state(tmp_path):
    config = load_config(env={}, repo_root=tmp_path)
    storage = NoticeStorage(tmp_path / "state.sqlite3", config.sources)
    storage.initialize()
    item = make_item("shu_official", "https://example.com/detail.htm")
    notice_id = storage.upsert_seen_item(item)
    storage.mark_failed(notice_id, "rate limited", failure_type="llm_rate_limit", retry_after_hours=0, retry_limit=3)

    storage.save_detail(
        notice_id,
        NoticeDetail(
            source_id=item.source_id,
            url=item.url,
            canonical_url=item.canonical_url,
            title=item.title,
            content="这是一段足够长的详情正文，准备再次提交给摘要模型。",
            published_at=item.published_at,
            list_excerpt=item.list_excerpt,
        ),
    )

    row = storage.get_notice(notice_id)
    assert row["status"] == "failed"
    assert row["failure_type"] == "llm_rate_limit"
    assert row["failure_count"] == 1
    assert row["next_retry_at"] is not None


def test_storage_save_detail_clears_generic_detail_failure_state(tmp_path):
    config = load_config(env={}, repo_root=tmp_path)
    storage = NoticeStorage(tmp_path / "state.sqlite3", config.sources)
    storage.initialize()
    item = make_item("shu_official", "https://example.com/detail.htm")
    notice_id = storage.upsert_seen_item(item)
    storage.mark_failed(notice_id, "connection reset", failure_type="detail_RuntimeError", retry_after_hours=0, retry_limit=3)

    storage.save_detail(
        notice_id,
        NoticeDetail(
            source_id=item.source_id,
            url=item.url,
            canonical_url=item.canonical_url,
            title=item.title,
            content="这是一段足够长的详情正文，说明详情阶段已经恢复。",
            published_at=item.published_at,
            list_excerpt=item.list_excerpt,
        ),
    )

    row = storage.get_notice(notice_id)
    assert row["status"] == "detailed"
    assert row["failure_type"] == ""
    assert row["failure_count"] == 0
    assert row["next_retry_at"] is None


def test_storage_marks_bootstrap_baseline(tmp_path):
    config = load_config(env={}, repo_root=tmp_path)
    storage = NoticeStorage(tmp_path / "state.sqlite3", config.sources)
    storage.initialize()
    baseline_item = make_item("graduate_school", "https://gs.shu.edu.cn/info/1026/baseline.htm")
    storage.mark_seen_baseline([baseline_item])

    selection = classify(storage, [baseline_item])
    assert selection.new_items == ()
    assert selection.retry_items == ()
    assert selection.updated_seen == ()
    assert storage.find_by_source_url("graduate_school", baseline_item.canonical_url)["status"] == "seen_baseline"


def test_storage_uses_temporary_database_only(tmp_path):
    config = load_config(env={}, repo_root=tmp_path)
    db_path = tmp_path / "state.sqlite3"
    storage = NoticeStorage(db_path, config.sources)
    storage.initialize()

    assert db_path.exists()
    with sqlite3.connect(db_path) as conn:
        assert conn.execute("select count(*) from sources").fetchone()[0] == 3


def test_storage_records_schema_migration_version(tmp_path):
    config = load_config(env={}, repo_root=tmp_path)
    db_path = tmp_path / "state.sqlite3"
    storage = NoticeStorage(db_path, config.sources)

    storage.initialize()

    with sqlite3.connect(db_path) as conn:
        versions = [row[0] for row in conn.execute("select version from schema_migrations")]

    assert "2026_07_06_baseline" in versions


def test_storage_health_reports_existing_database(tmp_path):
    config = load_config(env={}, repo_root=tmp_path)
    db_path = tmp_path / "state.sqlite3"
    storage = NoticeStorage(db_path, config.sources)
    storage.initialize()

    health = storage.health_check()

    assert health.exists is True
    assert health.source_count == 3
    assert health.notice_count == 0
    assert health.schema_versions == ("2026_07_06_baseline",)


def test_storage_initializes_media_metadata_columns(tmp_path):
    config = load_config(env={}, repo_root=tmp_path)
    db_path = tmp_path / "state.sqlite3"
    storage = NoticeStorage(db_path, config.sources)

    storage.initialize()

    with sqlite3.connect(db_path) as conn:
        columns = {row[1] for row in conn.execute("pragma table_info(notices)").fetchall()}

    assert {"content_kind", "assets_json", "attachments_json"} <= columns


def test_storage_configures_sqlite_for_concurrent_writes(tmp_path):
    config = load_config(env={}, repo_root=tmp_path)
    db_path = tmp_path / "state.sqlite3"
    storage = NoticeStorage(db_path, config.sources)

    storage.initialize()

    with storage._connect() as conn:
        assert conn.execute("pragma busy_timeout").fetchone()[0] == 30000
        assert conn.execute("pragma journal_mode").fetchone()[0].lower() == "wal"

    assert storage._write_lock.acquire(blocking=False)
    storage._write_lock.release()


def test_storage_checkpoint_truncates_wal_file(tmp_path):
    config = load_config(env={}, repo_root=tmp_path)
    db_path = tmp_path / "state.sqlite3"
    storage = NoticeStorage(db_path, config.sources)
    storage.initialize()
    storage.upsert_seen_item(make_item("shu_official", "https://example.com/wal.htm"))

    storage.checkpoint()

    wal_path = tmp_path / "state.sqlite3-wal"
    assert not wal_path.exists() or wal_path.stat().st_size == 0


def test_storage_saves_media_metadata_for_detail(tmp_path):
    config = load_config(env={}, repo_root=tmp_path)
    storage = NoticeStorage(tmp_path / "state.sqlite3", config.sources)
    storage.initialize()
    item = NoticeListItem(
        source_id="management_school",
        url="https://ms.shu.edu.cn/info/1245/91745.htm",
        canonical_url="https://ms.shu.edu.cn/info/1245/91745.htm",
        title="巡察公告",
    )
    notice_id = storage.upsert_seen_item(item)

    storage.save_detail(
        notice_id,
        NoticeDetail(
            source_id=item.source_id,
            url=item.url,
            canonical_url=item.canonical_url,
            title=item.title,
            content="",
            attachments=(Attachment(name="巡察公告.pdf", url="https://ms.shu.edu.cn/__local/inspection.pdf"),),
            assets=(
                NoticeAsset(
                    kind="pdf",
                    role="primary",
                    name="巡察公告.pdf",
                    url="https://ms.shu.edu.cn/__local/inspection.pdf",
                    mime_type="application/pdf",
                ),
            ),
            content_kind="pdf",
        ),
    )

    row = storage.get_notice(notice_id)

    assert row["content_kind"] == "pdf"
    assert '"kind": "pdf"' in row["assets_json"]
    assert '"巡察公告.pdf"' in row["attachments_json"]


def test_storage_content_hash_changes_when_asset_url_changes_even_with_empty_content(tmp_path):
    config = load_config(env={}, repo_root=tmp_path)
    storage = NoticeStorage(tmp_path / "state.sqlite3", config.sources)
    storage.initialize()
    item = NoticeListItem(
        source_id="management_school",
        url="https://ms.shu.edu.cn/info/1245/91745.htm",
        canonical_url="https://ms.shu.edu.cn/info/1245/91745.htm",
        title="巡察公告",
    )
    notice_id = storage.upsert_seen_item(item)

    first_detail = NoticeDetail(
        source_id=item.source_id,
        url=item.url,
        canonical_url=item.canonical_url,
        title=item.title,
        content="",
        assets=(
            NoticeAsset(
                "pdf",
                "primary",
                "巡察公告.pdf",
                "https://ms.shu.edu.cn/__local/inspection-v1.pdf",
                "application/pdf",
            ),
        ),
        content_kind="pdf",
    )
    second_detail = NoticeDetail(
        source_id=item.source_id,
        url=item.url,
        canonical_url=item.canonical_url,
        title=item.title,
        content="",
        assets=(
            NoticeAsset(
                "pdf",
                "primary",
                "巡察公告.pdf",
                "https://ms.shu.edu.cn/__local/inspection-v2.pdf",
                "application/pdf",
            ),
        ),
        content_kind="pdf",
    )

    storage.save_detail(notice_id, first_detail)
    first_hash = storage.get_notice(notice_id)["content_hash"]
    storage.save_detail(notice_id, second_detail)
    second_hash = storage.get_notice(notice_id)["content_hash"]

    assert first_hash != second_hash


def test_storage_migrates_existing_database_with_retry_columns(tmp_path):
    config = load_config(env={}, repo_root=tmp_path)
    db_path = tmp_path / "state.sqlite3"
    with sqlite3.connect(db_path) as conn:
        conn.executescript(
            """
            create table notices (
                id integer primary key autoincrement,
                source_id text not null,
                url text not null,
                canonical_url text not null,
                title text not null,
                list_excerpt text not null default '',
                content text not null default '',
                published_at text,
                first_seen_at text not null,
                last_seen_at text not null,
                content_hash text not null default '',
                status text not null,
                summary text not null default '',
                summary_model text not null default '',
                summary_prompt_version text not null default '',
                summary_generated_at text,
                detail_fetched_at text,
                error_message text not null default '',
                unique(source_id, canonical_url)
            );
            """
        )

    storage = NoticeStorage(db_path, config.sources)
    storage.initialize()

    with sqlite3.connect(db_path) as conn:
        columns = {row[1] for row in conn.execute("pragma table_info(notices)").fetchall()}

    assert {"failure_type", "failure_count", "last_failed_at", "next_retry_at"} <= columns
