import csv
import sqlite3
from datetime import datetime

from src.notice_push.config import load_config
from src.notice_push.models import NoticeDetail, NoticeListItem, NoticeSummary
from src.notice_push.storage import NoticeStorage


def make_item(source_id: str, url: str, title: str = "测试通知") -> NoticeListItem:
    return NoticeListItem(
        source_id=source_id,
        url=url,
        canonical_url=url,
        title=title,
        published_at=datetime(2026, 6, 16),
        list_excerpt="列表摘要",
    )


def test_storage_initializes_sources_and_deduplicates_per_source(tmp_path):
    config = load_config(env={}, repo_root=tmp_path)
    storage = NoticeStorage(tmp_path / "state.sqlite3", config.sources)
    storage.initialize()

    item = make_item("shu_official", "https://example.com/notice.htm")
    same_url_other_source = make_item("management_school", "https://example.com/notice.htm")

    assert storage.filter_new_items([item, same_url_other_source]) == [item, same_url_other_source]

    storage.upsert_seen_item(item)

    assert storage.filter_new_items([item, same_url_other_source]) == [same_url_other_source]
    assert storage.count_sources() == 3


def test_storage_touches_seen_items_without_resending(tmp_path):
    config = load_config(env={}, repo_root=tmp_path)
    storage = NoticeStorage(tmp_path / "state.sqlite3", config.sources)
    storage.initialize()
    item = make_item("shu_official", "https://example.com/notice.htm", title="旧标题")
    storage.upsert_seen_item(item)
    before = storage.find_by_source_url(item.source_id, item.canonical_url)

    updated_item = make_item("shu_official", "https://example.com/notice.htm", title="新标题")

    assert storage.filter_new_items([updated_item]) == []

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
    storage.mark_failed(notice_id, "detail too short")

    row = storage.get_notice(notice_id)

    assert row["content"] == "详情页正文"
    assert row["summary"] == "## 官网|行政|周常事务|测试通知"
    assert row["summary_model"] == "deepseek-chat"
    assert row["summary_prompt_version"] == "notice_summary_v1"
    assert row["status"] == "failed"
    assert row["error_message"] == "detail too short"


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


def test_storage_migrates_legacy_csv_and_bootstrap_baseline(tmp_path):
    config = load_config(env={}, repo_root=tmp_path)
    csv_path = tmp_path / "notice_records.csv"
    with csv_path.open("w", encoding="utf-8", newline="") as file:
        writer = csv.writer(file)
        writer.writerow(["https://www.shu.edu.cn/info/1051/old.htm", "abc123"])

    storage = NoticeStorage(tmp_path / "state.sqlite3", config.sources)
    storage.initialize()
    migrated = storage.migrate_legacy_csv(csv_path)

    legacy = storage.find_by_source_url("shu_official", "https://www.shu.edu.cn/info/1051/old.htm")
    assert migrated == 1
    assert legacy["status"] == "seen_legacy"
    assert legacy["content_hash"] == "abc123"

    baseline_item = make_item("graduate_school", "https://gs.shu.edu.cn/info/1026/baseline.htm")
    storage.mark_seen_baseline([baseline_item])

    assert storage.filter_new_items([baseline_item]) == []
    assert storage.find_by_source_url("graduate_school", baseline_item.canonical_url)["status"] == "seen_baseline"


def test_storage_uses_temporary_database_only(tmp_path):
    config = load_config(env={}, repo_root=tmp_path)
    db_path = tmp_path / "state.sqlite3"
    storage = NoticeStorage(db_path, config.sources)
    storage.initialize()

    assert db_path.exists()
    with sqlite3.connect(db_path) as conn:
        assert conn.execute("select count(*) from sources").fetchone()[0] == 3
