from __future__ import annotations

import hashlib
import json

from notice_push.domain import NoticeDetail


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
