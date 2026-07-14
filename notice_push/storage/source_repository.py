from __future__ import annotations

from datetime import datetime, timezone
from typing import Iterable

from notice_push.domain import NoticeSource


class SourceRepository:
    def __init__(self, connection_factory, write_lock):
        self._connection_factory = connection_factory
        self._write_lock = write_lock

    def upsert_all(self, sources: Iterable[NoticeSource]) -> None:
        now = datetime.now(timezone.utc).replace(microsecond=0).isoformat()
        values = [
            (
                source.id,
                source.name,
                source.base_url,
                source.list_url,
                1 if source.enabled else 0,
                source.adapter,
                now,
                now,
            )
            for source in sources
        ]
        if not values:
            return
        with self._write_lock, self._connection_factory() as conn:
            conn.executemany(
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
                values,
            )

    def count(self) -> int:
        with self._connection_factory() as conn:
            return int(conn.execute("select count(*) from sources").fetchone()[0])
