from __future__ import annotations

from src.notice_push.models import NoticeDetail


def visible_notice_resources(detail: NoticeDetail) -> tuple[tuple[str, str], ...]:
    resources: list[tuple[str, str]] = []
    seen_urls: set[str] = set()
    for attachment in detail.attachments:
        if attachment.url and attachment.url not in seen_urls:
            resources.append((attachment.name or "通知附件", attachment.url))
            seen_urls.add(attachment.url)
    for asset in detail.assets:
        if asset.url and asset.url not in seen_urls:
            resources.append((asset.name or "通知资源", asset.url))
            seen_urls.add(asset.url)
    return tuple(resources)
