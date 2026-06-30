from __future__ import annotations

import csv
import hashlib
from datetime import datetime
from pathlib import Path
from typing import Iterable

from src.entry.notice import Notice
from src.notice_push.config import load_config
from src.notice_push.http import HttpClient
from src.notice_push.models import NoticeListItem
from src.notice_push.sources.shu_official import ShuOfficialAdapter
from src.notice_push.storage import NoticeStorage


class NoticeGetter:
    """Compatibility wrapper for the legacy Shanghai University notice getter."""

    @classmethod
    def fetch_notice_list(cls, http_client: HttpClient | None = None) -> list[Notice]:
        config = load_config(env={})
        source = config.source_by_id("shu_official")
        adapter = ShuOfficialAdapter(source)
        html = (http_client or HttpClient()).get_text(source.list_url)
        return [_notice_from_item(item) for item in adapter.parse_list_page(html, source.list_url)]

    @classmethod
    def dedup_and_save_to_csv(cls, notices: Iterable[Notice], csv_path: str | Path | None = None) -> list[Notice]:
        notices = list(notices)
        if csv_path is None:
            return cls._dedup_with_sqlite(notices)
        return cls._dedup_with_explicit_csv(notices, csv_path)

    @classmethod
    def get_notice_list(cls) -> list[Notice]:
        return cls.dedup_and_save_to_csv(cls.fetch_notice_list())

    @classmethod
    def _dedup_with_sqlite(cls, notices: list[Notice]) -> list[Notice]:
        config = load_config(env={})
        storage = NoticeStorage(config.state_path, config.sources)
        storage.initialize()
        storage.migrate_legacy_csv(config.repo_root / "resources" / "notice_records.csv")

        items = [_item_from_notice(notice) for notice in notices]
        new_items = storage.filter_new_items(items)
        for item in new_items:
            storage.upsert_seen_item(item)
        new_urls = {item.url for item in new_items}
        return [notice for notice in notices if notice.url in new_urls]

    @classmethod
    def _dedup_with_explicit_csv(cls, notices: list[Notice], csv_path: str | Path) -> list[Notice]:
        config = load_config(env={})
        path = Path(csv_path)
        if not path.is_absolute():
            path = config.repo_root / path

        existing_records: list[tuple[str, str]] = []
        existing_hashes: set[str] = set()
        if path.exists():
            with path.open("r", encoding="utf-8", newline="") as file:
                for row in csv.reader(file):
                    if len(row) >= 2 and row[0] and row[1]:
                        existing_records.append((row[0], row[1]))
                        existing_hashes.add(row[1])

        deduped: list[Notice] = []
        new_records: list[tuple[str, str]] = []
        for notice in notices:
            digest = _notice_hash(notice)
            if digest in existing_hashes:
                continue
            deduped.append(notice)
            new_records.append((notice.url, digest))
            existing_hashes.add(digest)

        if new_records:
            path.parent.mkdir(parents=True, exist_ok=True)
            with path.open("w", encoding="utf-8", newline="") as file:
                writer = csv.writer(file)
                writer.writerows(existing_records + new_records)

        return deduped


def _notice_from_item(item: NoticeListItem) -> Notice:
    return Notice(
        url=item.url,
        title=item.title,
        upload_time=item.published_at.date() if item.published_at else None,
    )


def _item_from_notice(notice: Notice) -> NoticeListItem:
    published_at = datetime.combine(notice.upload_time, datetime.min.time()) if notice.upload_time else None
    return NoticeListItem(
        source_id="shu_official",
        url=notice.url,
        canonical_url=notice.url,
        title=notice.title or "",
        published_at=published_at,
    )


def _notice_hash(notice: Notice) -> str:
    digest = hashlib.sha256()
    digest.update((notice.url or "").encode("utf-8"))
    digest.update((notice.title or "").encode("utf-8"))
    return digest.hexdigest()
