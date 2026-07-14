from __future__ import annotations

import sqlite3
from datetime import datetime, timedelta, timezone
from typing import Iterable, Optional

from notice_push.domain import NoticeDetail, NoticeListItem, NoticeSummary
from notice_push.storage.notices import save_notice_detail, update_seen_notice_detail_if_changed


class NoticeRepository:
    def __init__(self, connection_factory, write_lock):
        self._connection_factory = connection_factory
        self._write_lock = write_lock

    def upsert_seen_item(self, item: NoticeListItem, status: str = "seen") -> int:
        now = _now()
        with self._write_lock, self._connection_factory() as conn:
            conn.execute(
                """
                insert into notices(source_id, url, canonical_url, title, list_excerpt, published_at,
                                    first_seen_at, last_seen_at, status)
                values (?, ?, ?, ?, ?, ?, ?, ?, ?)
                on conflict(source_id, canonical_url) do update set
                    url=excluded.url,
                    title=excluded.title,
                    list_excerpt=excluded.list_excerpt,
                    published_at=coalesce(excluded.published_at, notices.published_at),
                    last_seen_at=excluded.last_seen_at
                """,
                (
                    item.source_id,
                    item.url,
                    item.canonical_url,
                    item.title,
                    item.list_excerpt,
                    _dt(item.published_at),
                    now,
                    now,
                    status,
                ),
            )
            return int(
                conn.execute(
                    "select id from notices where source_id = ? and canonical_url = ?",
                    (item.source_id, item.canonical_url),
                ).fetchone()["id"]
            )

    def save_detail(self, notice_id: int, detail: NoticeDetail) -> None:
        with self._write_lock, self._connection_factory() as conn:
            save_notice_detail(conn, notice_id, detail, _now())

    def update_seen_detail_if_changed(self, notice_id: int, detail: NoticeDetail) -> bool:
        with self._write_lock, self._connection_factory() as conn:
            return update_seen_notice_detail_if_changed(conn, notice_id, detail, _now())

    def save_summary(self, notice_id: int, summary: NoticeSummary) -> None:
        with self._write_lock, self._connection_factory() as conn:
            conn.execute(
                """
                update notices set
                    summary = ?,
                    summary_model = ?,
                    summary_prompt_version = ?,
                    summary_generated_at = ?,
                    status = 'summarized',
                    error_message = '',
                    failure_type = '',
                    failure_count = 0,
                    last_failed_at = null,
                    next_retry_at = null
                where id = ?
                """,
                (
                    summary.markdown,
                    summary.model,
                    summary.prompt_version,
                    _dt(summary.generated_at),
                    notice_id,
                ),
            )

    def mark_failed(
        self,
        notice_id: int,
        reason: str,
        *,
        failure_type: str = "unknown",
        retry_after_hours: int = 0,
        retry_limit: int = 3,
    ) -> None:
        failed_at = _now()
        next_retry_at = (
            _dt(datetime.now(timezone.utc) + timedelta(hours=max(0, retry_after_hours)))
            if retry_after_hours >= 0
            else None
        )
        with self._write_lock, self._connection_factory() as conn:
            conn.execute(
                """
                update notices set
                    status = 'failed',
                    error_message = ?,
                    failure_type = ?,
                    failure_count = failure_count + 1,
                    last_failed_at = ?,
                    next_retry_at = case
                        when failure_count + 1 < ? then ?
                        else null
                    end
                where id = ?
                """,
                (reason, failure_type, failed_at, retry_limit, next_retry_at, notice_id),
            )

    def mark_seen_baseline(self, items: Iterable[NoticeListItem]) -> int:
        count = 0
        with self._write_lock, self._connection_factory() as conn:
            for item in items:
                now = _now()
                cursor = conn.execute(
                    """
                    insert or ignore into notices(source_id, url, canonical_url, title, list_excerpt,
                                                  published_at, first_seen_at, last_seen_at, status)
                    values (?, ?, ?, ?, ?, ?, ?, ?, 'seen_baseline')
                    """,
                    (
                        item.source_id,
                        item.url,
                        item.canonical_url,
                        item.title,
                        item.list_excerpt,
                        _dt(item.published_at),
                        now,
                        now,
                    ),
                )
                count += cursor.rowcount
        return count

    def get(self, notice_id: int) -> sqlite3.Row:
        with self._connection_factory() as conn:
            row = conn.execute("select * from notices where id = ?", (notice_id,)).fetchone()
            if row is None:
                raise KeyError(notice_id)
            return row

    def find_by_source_url(self, source_id: str, canonical_url: str) -> sqlite3.Row:
        with self._connection_factory() as conn:
            row = conn.execute(
                "select * from notices where source_id = ? and canonical_url = ?",
                (source_id, canonical_url),
            ).fetchone()
            if row is None:
                raise KeyError((source_id, canonical_url))
            return row

    def checkpoint(self) -> None:
        with self._write_lock, self._connection_factory() as conn:
            conn.execute("pragma wal_checkpoint(TRUNCATE)")


def _now() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat()


def _dt(value: Optional[datetime]) -> Optional[str]:
    return value.replace(microsecond=0).isoformat() if value else None
