from __future__ import annotations

import hashlib
import json
from datetime import datetime

from notice_push.domain import Attachment, NoticeAsset, NoticeDetail


def attachments_json(detail: NoticeDetail) -> str:
    return json.dumps(
        [{"name": item.name, "url": item.url} for item in detail.attachments],
        ensure_ascii=False,
        sort_keys=True,
    )


def assets_json(detail: NoticeDetail) -> str:
    return json.dumps(
        [
            {
                "kind": item.kind,
                "role": item.role,
                "name": item.name,
                "url": item.url,
                "mime_type": item.mime_type,
            }
            for item in detail.assets
        ],
        ensure_ascii=False,
        sort_keys=True,
    )


def content_hash(detail: NoticeDetail) -> str:
    digest = hashlib.sha256()
    digest.update((detail.content or "").encode("utf-8"))
    digest.update((detail.content_kind or "text").encode("utf-8"))
    digest.update(assets_json(detail).encode("utf-8"))
    digest.update(attachments_json(detail).encode("utf-8"))
    return digest.hexdigest()


def detail_from_row(row) -> NoticeDetail:
    attachments = tuple(
        Attachment(name=str(item.get("name", "")), url=str(item.get("url", "")))
        for item in _loads_list(row["attachments_json"])
    )
    assets = tuple(
        NoticeAsset(
            kind=str(item.get("kind", "")),
            role=str(item.get("role", "")),
            name=str(item.get("name", "")),
            url=str(item.get("url", "")),
            mime_type=str(item.get("mime_type", "")),
        )
        for item in _loads_list(row["assets_json"])
    )
    return NoticeDetail(
        source_id=row["source_id"],
        url=row["url"],
        canonical_url=row["canonical_url"],
        title=row["title"],
        content=row["content"],
        published_at=_parse_datetime(row["published_at"]),
        list_excerpt=row["list_excerpt"],
        attachments=attachments,
        assets=assets,
        content_kind=row["content_kind"] or "text",
    )


def _loads_list(raw: str) -> list[dict]:
    try:
        loaded = json.loads(raw or "[]")
    except json.JSONDecodeError:
        return []
    return loaded if isinstance(loaded, list) else []


def _parse_datetime(raw: str | None) -> datetime | None:
    if not raw:
        return None
    return datetime.fromisoformat(str(raw))
