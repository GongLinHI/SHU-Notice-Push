from __future__ import annotations

import hashlib
import json
from datetime import datetime

from pydantic import BaseModel, ConfigDict, TypeAdapter, ValidationError

from notice_push.domain import Attachment, NoticeAsset, NoticeDetail


class _AttachmentRecord(BaseModel):
    model_config = ConfigDict(extra="ignore", frozen=True)

    name: str = ""
    url: str = ""


class _AssetRecord(_AttachmentRecord):
    kind: str = ""
    role: str = ""
    mime_type: str = ""


_ATTACHMENTS_ADAPTER = TypeAdapter(list[_AttachmentRecord])
_ASSETS_ADAPTER = TypeAdapter(list[_AssetRecord])


def attachments_json(detail: NoticeDetail) -> str:
    records = [
        _AttachmentRecord(name=item.name, url=item.url)
        for item in detail.attachments
    ]
    return _canonical_json(
        [record.model_dump(mode="json") for record in records]
    )


def assets_json(detail: NoticeDetail) -> str:
    records = [
        _AssetRecord(
            kind=item.kind,
            role=item.role,
            name=item.name,
            url=item.url,
            mime_type=item.mime_type,
        )
        for item in detail.assets
    ]
    return _canonical_json(
        [record.model_dump(mode="json") for record in records]
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
        Attachment(name=item.name, url=item.url)
        for item in _load_records(row["attachments_json"], _ATTACHMENTS_ADAPTER)
    )
    assets = tuple(
        NoticeAsset(
            kind=item.kind,
            role=item.role,
            name=item.name,
            url=item.url,
            mime_type=item.mime_type,
        )
        for item in _load_records(row["assets_json"], _ASSETS_ADAPTER)
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


def _load_records(raw: str, adapter: TypeAdapter):
    try:
        return adapter.validate_json(raw or "[]")
    except ValidationError:
        return []


def _canonical_json(payload: list[dict[str, object]]) -> str:
    # This byte representation participates in content_hash; keep key ordering stable.
    return json.dumps(payload, ensure_ascii=False, sort_keys=True)


def _parse_datetime(raw: str | None) -> datetime | None:
    if not raw:
        return None
    return datetime.fromisoformat(str(raw))
