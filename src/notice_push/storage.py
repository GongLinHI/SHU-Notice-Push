from __future__ import annotations

import csv
import hashlib
import sqlite3
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Iterable, Optional

from src.notice_push.models import NoticeDetail, NoticeListItem, NoticeSource, NoticeSummary


class NoticeStorage:
    def __init__(self, db_path: Path, sources: Iterable[NoticeSource]):
        self.db_path = Path(db_path)
        self.sources = tuple(sources)

    def initialize(self) -> None:
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        with self._connect() as conn:
            conn.executescript(
                """
                create table if not exists sources (
                    id text primary key,
                    name text not null,
                    base_url text not null,
                    list_url text not null,
                    enabled integer not null,
                    adapter text not null,
                    created_at text not null,
                    updated_at text not null
                );

                create table if not exists notices (
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
                    failure_type text not null default '',
                    failure_count integer not null default 0,
                    last_failed_at text,
                    next_retry_at text,
                    foreign key(source_id) references sources(id),
                    unique(source_id, canonical_url)
                );

                create index if not exists idx_notices_dates
                on notices(published_at, first_seen_at);
                """
            )
            self._ensure_notice_columns(conn)
            now = _now()
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
        new_items: list[NoticeListItem] = []
        now = _now()
        with self._connect() as conn:
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
                        new_items.append(item)
        return new_items

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
        with self._connect() as conn:
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
        content_hash = hashlib.sha256(detail.content.encode("utf-8")).hexdigest()
        with self._connect() as conn:
            conn.execute(
                """
                update notices set
                    title = ?,
                    content = ?,
                    published_at = coalesce(?, published_at),
                    list_excerpt = ?,
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
                    content_hash,
                    _now(),
                    notice_id,
                ),
            )

    def update_seen_detail_if_changed(self, notice_id: int, detail: NoticeDetail) -> bool:
        content_hash = hashlib.sha256(detail.content.encode("utf-8")).hexdigest()
        with self._connect() as conn:
            row = conn.execute("select content_hash from notices where id = ?", (notice_id,)).fetchone()
            if row is None:
                raise KeyError(notice_id)
            if row["content_hash"] == content_hash:
                return False
            conn.execute(
                """
                update notices set
                    title = ?,
                    content = ?,
                    published_at = coalesce(?, published_at),
                    list_excerpt = ?,
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
                    content_hash,
                    _now(),
                    notice_id,
                ),
            )
        return True

    def save_summary(self, notice_id: int, summary: NoticeSummary) -> None:
        with self._connect() as conn:
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
        with self._connect() as conn:
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
        with self._connect() as conn:
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

    def migrate_legacy_csv(self, csv_path: Path) -> int:
        if not Path(csv_path).exists():
            return 0

        migrated = 0
        with Path(csv_path).open("r", encoding="utf-8", newline="") as file, self._connect() as conn:
            for row in csv.reader(file):
                if len(row) < 2 or not row[0] or not row[1]:
                    continue
                now = _now()
                cursor = conn.execute(
                    """
                    insert or ignore into notices(source_id, url, canonical_url, title, content_hash,
                                                  first_seen_at, last_seen_at, status)
                    values ('shu_official', ?, ?, '', ?, ?, ?, 'seen_legacy')
                    """,
                    (row[0], row[0], row[1], now, now),
                )
                migrated += cursor.rowcount
        return migrated

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

    def _connect(self) -> sqlite3.Connection:
        conn = sqlite3.connect(self.db_path, timeout=30)
        conn.row_factory = sqlite3.Row
        return conn

    def _ensure_notice_columns(self, conn: sqlite3.Connection) -> None:
        existing = {row["name"] for row in conn.execute("pragma table_info(notices)").fetchall()}
        columns = {
            "failure_type": "text not null default ''",
            "failure_count": "integer not null default 0",
            "last_failed_at": "text",
            "next_retry_at": "text",
        }
        for name, definition in columns.items():
            if name not in existing:
                conn.execute(f"alter table notices add column {name} {definition}")


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
