from __future__ import annotations

import sqlite3
from dataclasses import dataclass, replace
from itertools import islice
from typing import Iterable, Mapping

from notice_push.crawler.failures import FailureRetryPolicy, is_retryable_failure_type
from notice_push.domain import NoticeDetail, NoticeListItem
from notice_push.storage.serialization import detail_from_row


SQLITE_URL_CHUNK_SIZE = 400


@dataclass(frozen=True)
class SelectedUpdatedNotice:
    item: NoticeListItem
    notice_id: int
    detail: NoticeDetail


@dataclass(frozen=True)
class PipelineItemSelection:
    new_items: tuple[NoticeListItem, ...]
    retry_items: tuple[NoticeListItem, ...]
    updated_seen: tuple[SelectedUpdatedNotice, ...]
    seen_rows: Mapping[tuple[str, str], sqlite3.Row]


class NoticeSelectionRepository:
    def __init__(self, connection_factory, write_lock):
        self._connection_factory = connection_factory
        self._write_lock = write_lock

    def classify_pipeline_items(
        self,
        items: Iterable[NoticeListItem],
        *,
        retry_failed: bool,
        retry_policy: FailureRetryPolicy,
    ) -> PipelineItemSelection:
        ordered_items = tuple(items)
        if not ordered_items:
            return PipelineItemSelection((), (), (), {})

        rows_by_key: dict[tuple[str, str], sqlite3.Row] = {}
        grouped_items = _group_by_source(ordered_items)
        now = _now()
        with self._write_lock, self._connection_factory() as conn:
            for source_id, source_items in grouped_items.items():
                for chunk in _chunks(source_items, SQLITE_URL_CHUNK_SIZE):
                    placeholders = ", ".join("?" for _ in chunk)
                    rows = conn.execute(
                        f"""
                        select *
                        from notices
                        where source_id = ? and canonical_url in ({placeholders})
                        """,
                        (source_id, *(item.canonical_url for item in chunk)),
                    ).fetchall()
                    rows_by_key.update(
                        ((source_id, str(row["canonical_url"])), row)
                        for row in rows
                    )

            seen_updates = []
            for item in ordered_items:
                row = rows_by_key.get((item.source_id, item.canonical_url))
                if row is not None:
                    seen_updates.append(
                        (
                            item.url,
                            item.title,
                            item.list_excerpt,
                            _dt(item.published_at),
                            now,
                            int(row["id"]),
                        )
                    )
            if seen_updates:
                conn.executemany(
                    """
                    update notices set
                        url = ?,
                        title = ?,
                        list_excerpt = ?,
                        published_at = coalesce(?, published_at),
                        last_seen_at = ?
                    where id = ?
                    """,
                    seen_updates,
                )

        new_items: list[NoticeListItem] = []
        retry_items: list[NoticeListItem] = []
        updated_seen: list[SelectedUpdatedNotice] = []
        seen_rows: dict[tuple[str, str], sqlite3.Row] = {}
        for item in ordered_items:
            row = rows_by_key.get((item.source_id, item.canonical_url))
            if row is None:
                new_items.append(item)
                continue
            seen_rows[(item.source_id, item.canonical_url)] = row
            if retry_failed and _row_retryable(row, retry_policy.limit, now):
                retry_items.append(item)
            elif row["status"] == "updated_seen":
                detail = detail_from_row(row)
                updated_seen.append(
                    SelectedUpdatedNotice(
                        item=item,
                        notice_id=int(row["id"]),
                        detail=replace(
                            detail,
                            url=item.url,
                            title=item.title,
                            list_excerpt=item.list_excerpt,
                            published_at=item.published_at or detail.published_at,
                        ),
                    )
                )

        return PipelineItemSelection(
            new_items=tuple(new_items),
            retry_items=tuple(retry_items),
            updated_seen=tuple(updated_seen),
            seen_rows=seen_rows,
        )


def _group_by_source(items: tuple[NoticeListItem, ...]) -> dict[str, list[NoticeListItem]]:
    grouped: dict[str, list[NoticeListItem]] = {}
    for item in items:
        grouped.setdefault(item.source_id, []).append(item)
    return grouped


def _chunks(items: list[NoticeListItem], size: int):
    iterator = iter(items)
    while chunk := tuple(islice(iterator, size)):
        yield chunk


def _row_retryable(row: sqlite3.Row, retry_limit: int, now: str) -> bool:
    if row["status"] != "failed":
        return False
    if not is_retryable_failure_type(str(row["failure_type"] or "")):
        return False
    if retry_limit <= 0 or int(row["failure_count"] or 0) >= retry_limit:
        return False
    next_retry_at = row["next_retry_at"]
    return not next_retry_at or str(next_retry_at) <= now


def _now() -> str:
    from datetime import datetime, timezone

    return datetime.now(timezone.utc).replace(microsecond=0).isoformat()


def _dt(value):
    return value.replace(microsecond=0).isoformat() if value else None
