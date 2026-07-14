from contextlib import contextmanager
from datetime import datetime

import pytest

pytestmark = pytest.mark.usefixtures("seed_runtime_config_for_temporary_repo")

from notice_push.crawler.failures import FailureRetryPolicy
from notice_push.domain import NoticeDetail, NoticeListItem
from notice_push.settings.loader import load_config
from notice_push.storage import NoticeStorage


def make_item(index: int) -> NoticeListItem:
    url = f"https://example.com/notice-{index}.htm"
    return NoticeListItem(
        source_id="shu_official",
        url=url,
        canonical_url=url,
        title=f"测试通知 {index}",
        published_at=datetime(2026, 7, 14),
    )


def test_classify_pipeline_items_uses_one_select_per_chunk(tmp_path):
    config = load_config(env={}, repo_root=tmp_path)
    storage = NoticeStorage(tmp_path / "state.sqlite3", config.sources)
    storage.initialize()
    statements = []
    original_connect = storage._connect

    @contextmanager
    def traced_connect():
        with original_connect() as conn:
            conn.set_trace_callback(statements.append)
            yield conn

    storage._connect = traced_connect
    items = [make_item(index) for index in range(401)]

    selection = storage.classify_pipeline_items(
        items,
        retry_failed=True,
        retry_policy=FailureRetryPolicy(limit=3, after_hours=0),
    )

    notice_selects = [
        statement
        for statement in statements
        if statement.lstrip().lower().startswith("select") and "from notices" in statement.lower()
    ]
    assert selection.new_items == tuple(items)
    assert len(notice_selects) == 2


def test_classify_pipeline_items_returns_retry_and_updated_details_in_input_order(tmp_path):
    config = load_config(env={}, repo_root=tmp_path)
    storage = NoticeStorage(tmp_path / "state.sqlite3", config.sources)
    storage.initialize()
    retry_item = make_item(1)
    updated_item = make_item(2)
    new_item = make_item(3)

    retry_id = storage.upsert_seen_item(retry_item)
    storage.mark_failed(
        retry_id,
        "temporary failure",
        failure_type="detail_empty",
        retry_after_hours=0,
        retry_limit=3,
    )
    updated_id = storage.upsert_seen_item(updated_item)
    storage.save_detail(
        updated_id,
        NoticeDetail(
            source_id=updated_item.source_id,
            url=updated_item.url,
            canonical_url=updated_item.canonical_url,
            title=updated_item.title,
            content="旧正文",
        ),
    )
    storage.update_seen_detail_if_changed(
        updated_id,
        NoticeDetail(
            source_id=updated_item.source_id,
            url=updated_item.url,
            canonical_url=updated_item.canonical_url,
            title=updated_item.title,
            content="这是更新后需要重新摘要的完整正文内容。",
        ),
    )

    selection = storage.classify_pipeline_items(
        [updated_item, new_item, retry_item],
        retry_failed=True,
        retry_policy=FailureRetryPolicy(limit=3, after_hours=0),
    )

    assert selection.new_items == (new_item,)
    assert selection.retry_items == (retry_item,)
    assert [selected.item for selected in selection.updated_seen] == [updated_item]
    assert selection.updated_seen[0].notice_id == updated_id
    assert "更新后" in selection.updated_seen[0].detail.content
