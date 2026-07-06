from __future__ import annotations

import sqlite3
import threading
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Iterable, Optional

from notice_push.domain import NoticeDetail, NoticeListItem, NoticeSource, NoticeSummary, StorageHealth
from notice_push.storage.health import storage_health
from notice_push.storage.notices import save_notice_detail, update_seen_notice_detail_if_changed
from notice_push.storage.schema import initialize_schema


class NoticeStorage:
    def __init__(self, db_path: Path, sources: Iterable[NoticeSource]):
        self.db_path = Path(db_path)
        self.sources = tuple(sources)
        self._write_lock = threading.RLock()

    def initialize(self) -> None:
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        with self._write_lock, self._connect() as conn:
            conn.execute("pragma journal_mode = wal")
            now = _now()
            initialize_schema(conn, now)
            for source in self.sources:
                conn.execute(
                    """
                    insert into sources(id, name, base_url, list_url, enabled, adapter, created_at, updated_at)
                    values (?, ?, ?, ?, ?, ?, ?, ?)
                    on conflict(id) do update set
                        name=excluded.name,
                        base_url=excluded.base_url,
                        list_url=excluded.list_url,
                        enabled=excluded.enabled,
                        adapter=excluded.adapter,
                        updated_at=excluded.updated_at
                    """,
                    (
                        source.id,
                        source.name,
                        source.base_url,
                        source.list_url,
                        1 if source.enabled else 0,
                        source.adapter,
                        now,
                        now,
                    ),
                )

    def filter_new_items(self, items: Iterable[NoticeListItem]) -> list[NoticeListItem]:
        return self.filter_processable_items(items, retry_failed=False)

    def filter_processable_items(
        self,
        items: Iterable[NoticeListItem],
        *,
        retry_failed: bool = False,
        failed_retry_limit: int = 0,
    ) -> list[NoticeListItem]:
        new_items, retry_items = self.split_processable_items(
            items,
            retry_failed=retry_failed,
            failed_retry_limit=failed_retry_limit,
        )
        return new_items + retry_items

    def split_processable_items(
        self,
        items: Iterable[NoticeListItem],
        *,
        retry_failed: bool = False,
        failed_retry_limit: int = 0,
    ) -> tuple[list[NoticeListItem], list[NoticeListItem]]:
        new_items: list[NoticeListItem] = []
        retry_items: list[NoticeListItem] = []
        now = _now()
        with self._write_lock, self._connect() as conn:
            for item in items:
                row = conn.execute(
                    """
                    select id, status, failure_count, next_retry_at
                    from notices
                    where source_id = ? and canonical_url = ?
                    """,
                    (item.source_id, item.canonical_url),
                ).fetchone()
                if row is None:
                    new_items.append(item)
                else:
                    conn.execute(
                        """
                        update notices set
                            url = ?,
                            title = ?,
                            list_excerpt = ?,
                            published_at = coalesce(?, published_at),
                            last_seen_at = ?
                        where id = ?
                        """,
                        (
                            item.url,
                            item.title,
                            item.list_excerpt,
                            _dt(item.published_at),
                            now,
                            row["id"],
                        ),
                    )
                    if retry_failed and _row_retryable(row, failed_retry_limit, now):
                        retry_items.append(item)
        return new_items, retry_items

    def find_seen_items(self, items: Iterable[NoticeListItem]) -> dict[str, sqlite3.Row]:
        rows: dict[str, sqlite3.Row] = {}
        with self._connect() as conn:
            for item in items:
                row = conn.execute(
                    "select * from notices where source_id = ? and canonical_url = ?",
                    (item.source_id, item.canonical_url),
                ).fetchone()
                if row is not None:
                    rows[item.canonical_url] = row
        return rows

    def upsert_seen_item(self, item: NoticeListItem, status: str = "seen") -> int:
        now = _now()
        with self._write_lock, self._connect() as conn:
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
        with self._write_lock, self._connect() as conn:
            save_notice_detail(conn, notice_id, detail, _now())

    def update_seen_detail_if_changed(self, notice_id: int, detail: NoticeDetail) -> bool:
        with self._write_lock, self._connect() as conn:
            return update_seen_notice_detail_if_changed(conn, notice_id, detail, _now())

    def save_summary(self, notice_id: int, summary: NoticeSummary) -> None:
        with self._write_lock, self._connect() as conn:
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
        with self._write_lock, self._connect() as conn:
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
        with self._write_lock, self._connect() as conn:
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

    def get_notice(self, notice_id: int) -> sqlite3.Row:
        with self._connect() as conn:
            row = conn.execute("select * from notices where id = ?", (notice_id,)).fetchone()
            if row is None:
                raise KeyError(notice_id)
            return row

    def find_by_source_url(self, source_id: str, canonical_url: str) -> sqlite3.Row:
        with self._connect() as conn:
            row = conn.execute(
                "select * from notices where source_id = ? and canonical_url = ?",
                (source_id, canonical_url),
            ).fetchone()
            if row is None:
                raise KeyError((source_id, canonical_url))
            return row

    def count_sources(self) -> int:
        with self._connect() as conn:
            return int(conn.execute("select count(*) from sources").fetchone()[0])

    def health_check(self) -> StorageHealth:
        if not self.db_path.exists():
            return StorageHealth(
                exists=False,
                source_count=0,
                notice_count=0,
                schema_versions=(),
            )

        with self._connect() as conn:
            source_count, notice_count, schema_versions = storage_health(conn)
        return StorageHealth(
            exists=True,
            source_count=source_count,
            notice_count=notice_count,
            schema_versions=schema_versions,
        )

    def checkpoint(self) -> None:
        if not self.db_path.exists():
            return
        with self._write_lock, self._connect() as conn:
            conn.execute("pragma wal_checkpoint(TRUNCATE)")

    def _connect(self) -> sqlite3.Connection:
        conn = sqlite3.connect(self.db_path, timeout=30)
        conn.row_factory = sqlite3.Row
        conn.execute("pragma busy_timeout = 30000")
        return conn

def _now() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat()


def _dt(value: Optional[datetime]) -> Optional[str]:
    return value.replace(microsecond=0).isoformat() if value else None


def _row_retryable(row: sqlite3.Row, retry_limit: int, now: str) -> bool:
    if row["status"] != "failed":
        return False
    if retry_limit <= 0 or int(row["failure_count"] or 0) >= retry_limit:
        return False
    next_retry_at = row["next_retry_at"]
    return not next_retry_at or str(next_retry_at) <= now
