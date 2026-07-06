from __future__ import annotations

import sqlite3
from datetime import datetime
from typing import Optional

from notice_push.domain import NoticeDetail
from notice_push.storage.serialization import assets_json, attachments_json, content_hash


def save_notice_detail(conn: sqlite3.Connection, notice_id: int, detail: NoticeDetail, fetched_at: str) -> None:
    conn.execute(
        """
        update notices set
            title = ?,
            content = ?,
            published_at = coalesce(?, published_at),
            list_excerpt = ?,
            content_kind = ?,
            assets_json = ?,
            attachments_json = ?,
            content_hash = ?,
            detail_fetched_at = ?,
            status = case
                when status = 'failed' and failure_type != '' and failure_type not like 'detail_%' then status
                else 'detailed'
            end,
            error_message = case
                when failure_type = '' or failure_type like 'detail_%' then ''
                else error_message
            end,
            failure_type = case
                when failure_type = '' or failure_type like 'detail_%' then ''
                else failure_type
            end,
            failure_count = case
                when failure_type = '' or failure_type like 'detail_%' then 0
                else failure_count
            end,
            last_failed_at = case
                when failure_type = '' or failure_type like 'detail_%' then null
                else last_failed_at
            end,
            next_retry_at = case
                when failure_type = '' or failure_type like 'detail_%' then null
                else next_retry_at
            end
        where id = ?
        """,
        (
            detail.title,
            detail.content,
            _dt(detail.published_at),
            detail.list_excerpt,
            detail.content_kind or "text",
            assets_json(detail),
            attachments_json(detail),
            content_hash(detail),
            fetched_at,
            notice_id,
        ),
    )


def update_seen_notice_detail_if_changed(
    conn: sqlite3.Connection,
    notice_id: int,
    detail: NoticeDetail,
    fetched_at: str,
) -> bool:
    detail_content_hash = content_hash(detail)
    row = conn.execute("select content_hash from notices where id = ?", (notice_id,)).fetchone()
    if row is None:
        raise KeyError(notice_id)
    if row["content_hash"] == detail_content_hash:
        return False
    conn.execute(
        """
        update notices set
            title = ?,
            content = ?,
            published_at = coalesce(?, published_at),
            list_excerpt = ?,
            content_kind = ?,
            assets_json = ?,
            attachments_json = ?,
            content_hash = ?,
            detail_fetched_at = ?,
            status = 'updated_seen',
            summary = '',
            summary_model = '',
            summary_prompt_version = '',
            summary_generated_at = null,
            error_message = '',
            failure_type = '',
            failure_count = 0,
            last_failed_at = null,
            next_retry_at = null
        where id = ?
        """,
        (
            detail.title,
            detail.content,
            _dt(detail.published_at),
            detail.list_excerpt,
            detail.content_kind or "text",
            assets_json(detail),
            attachments_json(detail),
            detail_content_hash,
            fetched_at,
            notice_id,
        ),
    )
    return True


def _dt(value: Optional[datetime]) -> Optional[str]:
    return value.replace(microsecond=0).isoformat() if value else None
