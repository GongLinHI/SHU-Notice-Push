from __future__ import annotations

import sqlite3
import threading
from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path
from typing import Iterable

from notice_push.crawler.failures import FailureRetryPolicy
from notice_push.domain import NoticeDetail, NoticeListItem, NoticeSource, NoticeSummary, StorageHealth
from notice_push.storage.health import storage_health
from notice_push.storage.notice_repository import NoticeRepository
from notice_push.storage.schema import initialize_schema
from notice_push.storage.selection import NoticeSelectionRepository, PipelineItemSelection
from notice_push.storage.source_repository import SourceRepository


class NoticeStorage:
    """Stable storage facade composed from focused SQLite repositories."""

    def __init__(self, db_path: Path, sources: Iterable[NoticeSource]):
        self.db_path = Path(db_path)
        self.sources = tuple(sources)
        self._write_lock = threading.RLock()
        connection_factory = lambda: self._connect()
        self._sources = SourceRepository(connection_factory, self._write_lock)
        self._notices = NoticeRepository(connection_factory, self._write_lock)
        self._selection = NoticeSelectionRepository(connection_factory, self._write_lock)

    def initialize(self) -> None:
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        with self._write_lock, self._connect() as conn:
            conn.execute("pragma journal_mode = wal")
            initialize_schema(conn, _now())
        self._sources.upsert_all(self.sources)

    def classify_pipeline_items(
        self,
        items: Iterable[NoticeListItem],
        *,
        retry_failed: bool = False,
        retry_policy: FailureRetryPolicy = FailureRetryPolicy(),
    ) -> PipelineItemSelection:
        return self._selection.classify_pipeline_items(
            items,
            retry_failed=retry_failed,
            retry_policy=retry_policy,
        )

    def upsert_seen_item(self, item: NoticeListItem, status: str = "seen") -> int:
        return self._notices.upsert_seen_item(item, status)

    def save_detail(self, notice_id: int, detail: NoticeDetail) -> None:
        self._notices.save_detail(notice_id, detail)

    def update_seen_detail_if_changed(self, notice_id: int, detail: NoticeDetail) -> bool:
        return self._notices.update_seen_detail_if_changed(notice_id, detail)

    def save_summary(self, notice_id: int, summary: NoticeSummary) -> None:
        self._notices.save_summary(notice_id, summary)

    def mark_failed(
        self,
        notice_id: int,
        reason: str,
        *,
        failure_type: str = "unknown",
        retry_after_hours: int = 0,
        retry_limit: int = 3,
    ) -> None:
        self._notices.mark_failed(
            notice_id,
            reason,
            failure_type=failure_type,
            retry_after_hours=retry_after_hours,
            retry_limit=retry_limit,
        )

    def mark_seen_baseline(self, items: Iterable[NoticeListItem]) -> int:
        return self._notices.mark_seen_baseline(items)

    def get_notice(self, notice_id: int) -> sqlite3.Row:
        return self._notices.get(notice_id)

    def find_by_source_url(self, source_id: str, canonical_url: str) -> sqlite3.Row:
        return self._notices.find_by_source_url(source_id, canonical_url)

    def count_sources(self) -> int:
        return self._sources.count()

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
        if self.db_path.exists():
            self._notices.checkpoint()

    @contextmanager
    def _connect(self):
        conn = sqlite3.connect(self.db_path, timeout=30)
        conn.row_factory = sqlite3.Row
        conn.execute("pragma busy_timeout = 30000")
        try:
            yield conn
            conn.commit()
        except Exception:
            conn.rollback()
            raise
        finally:
            conn.close()


def _now() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat()
