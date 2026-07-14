from __future__ import annotations

from pathlib import PurePosixPath
from urllib.parse import urlparse

from bs4 import Tag

from notice_push.domain import NoticeAsset
from notice_push.parsing.content import DEFAULT_PARSING_RULES, ParsingRules, clean_text
from notice_push.parsing.pdfjs import extract_pdfjs_assets
from notice_push.parsing.urls import absolute_url, filename_from_url, is_external_video_url


DOCUMENT_EXTENSIONS = {
    ".pdf": ("pdf", "application/pdf"),
    ".doc": ("file", "application/msword"),
    ".docx": ("file", "application/vnd.openxmlformats-officedocument.wordprocessingml.document"),
    ".xls": ("file", "application/vnd.ms-excel"),
    ".xlsx": ("file", "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"),
}
IMAGE_EXTENSIONS = {
    ".png": "image/png",
    ".jpg": "image/jpeg",
    ".jpeg": "image/jpeg",
    ".webp": "image/webp",
    ".gif": "image/gif",
}
VIDEO_EXTENSIONS = {
    ".mp4": "video/mp4",
    ".mov": "video/quicktime",
    ".webm": "video/webm",
}


def extract_assets(
    root: Tag,
    page_url: str,
    rules: ParsingRules = DEFAULT_PARSING_RULES,
) -> tuple[NoticeAsset, ...]:
    assets: list[NoticeAsset] = []
    assets.extend(extract_link_assets(root, page_url))
    assets.extend(extract_image_assets(root, page_url, rules=rules))
    assets.extend(extract_video_assets(root, page_url, rules=rules))
    assets.extend(extract_pdfjs_assets(root, page_url))
    return tuple(_dedupe_assets(assets))


def extract_detail_assets(
    content_node: Tag | None,
    soup,
    page_url: str,
    rules: ParsingRules = DEFAULT_PARSING_RULES,
) -> tuple[NoticeAsset, ...]:
    root = soup if content_node is None else content_node
    return extract_assets(root, page_url, rules=rules)


def extract_link_assets(root: Tag, page_url: str) -> list[NoticeAsset]:
    assets: list[NoticeAsset] = []
    for anchor in root.find_all("a", href=True):
        absolute = absolute_url(anchor.get("href", ""), page_url)
        text = clean_text(anchor.get_text(" ", strip=True))
        suffix = PurePosixPath(urlparse(absolute).path.lower()).suffix
        if suffix in VIDEO_EXTENSIONS:
            assets.append(
                NoticeAsset(
                    kind="video",
                    role="primary",
                    name=text or filename_from_url(absolute),
                    url=absolute,
                    mime_type=VIDEO_EXTENSIONS[suffix],
                )
            )
            continue
        if suffix not in DOCUMENT_EXTENSIONS and "附件" not in text:
            continue
        kind, mime_type = DOCUMENT_EXTENSIONS.get(suffix, ("file", ""))
        assets.append(
            NoticeAsset(
                kind=kind,
                role="attachment",
                name=text or filename_from_url(absolute),
                url=absolute,
                mime_type=mime_type,
            )
        )
    return assets


def extract_image_assets(
    root: Tag,
    page_url: str,
    rules: ParsingRules = DEFAULT_PARSING_RULES,
) -> list[NoticeAsset]:
    assets: list[NoticeAsset] = []
    for image in root.find_all("img", src=True):
        absolute = absolute_url(image.get("src", ""), page_url)
        if any(marker in absolute.lower() for marker in rules.noise_image_markers):
            continue
        suffix = PurePosixPath(urlparse(absolute).path.lower()).suffix
        if suffix and suffix not in IMAGE_EXTENSIONS:
            continue
        assets.append(
            NoticeAsset(
                kind="image",
                role="primary",
                name=clean_text(image.get("alt", "")) or filename_from_url(absolute),
                url=absolute,
                mime_type=IMAGE_EXTENSIONS.get(suffix, ""),
            )
        )
    return assets


def extract_video_assets(
    root: Tag,
    page_url: str,
    rules: ParsingRules = DEFAULT_PARSING_RULES,
) -> list[NoticeAsset]:
    assets: list[NoticeAsset] = []
    for node in root.find_all(["video", "source", "iframe"], src=True):
        absolute = absolute_url(node.get("src", ""), page_url)
        if is_external_video_url(absolute, rules):
            assets.append(
                NoticeAsset(
                    kind="external_video",
                    role="primary",
                    name=filename_from_url(absolute) or absolute,
                    url=absolute,
                    mime_type="text/html",
                )
            )
            continue
        suffix = PurePosixPath(urlparse(absolute).path.lower()).suffix
        if suffix in VIDEO_EXTENSIONS:
            assets.append(
                NoticeAsset(
                    kind="video",
                    role="primary",
                    name=filename_from_url(absolute),
                    url=absolute,
                    mime_type=VIDEO_EXTENSIONS[suffix],
                )
            )
    return assets


def infer_content_kind(content: str, assets: tuple[NoticeAsset, ...]) -> str:
    substantive_text = clean_text(content)
    asset_names = {clean_text(asset.name) for asset in assets if clean_text(asset.name)}
    text_is_only_asset_label = bool(substantive_text) and substantive_text in asset_names
    kinds = {asset.kind for asset in assets}
    if substantive_text and not text_is_only_asset_label:
        return "text"
    if "pdf" in kinds:
        return "pdf"
    if "image" in kinds:
        return "image"
    if "video" in kinds or "external_video" in kinds:
        return "video"
    return "empty"


def promote_primary_assets(
    content_kind: str,
    assets: tuple[NoticeAsset, ...],
) -> tuple[NoticeAsset, ...]:
    if content_kind not in {"pdf", "image", "video"}:
        return assets
    promoted: list[NoticeAsset] = []
    for asset in assets:
        should_promote = (
            content_kind == "pdf" and asset.kind == "pdf"
            or content_kind == "image" and asset.kind == "image"
            or content_kind == "video" and asset.kind in {"video", "external_video"}
        )
        promoted.append(
            NoticeAsset(asset.kind, "primary", asset.name, asset.url, asset.mime_type)
            if should_promote
            else asset
        )
    return tuple(promoted)


def _dedupe_assets(assets: list[NoticeAsset]) -> list[NoticeAsset]:
    deduped: list[NoticeAsset] = []
    seen: set[tuple[str, str]] = set()
    for asset in assets:
        key = (asset.kind, asset.url)
        if key not in seen:
            seen.add(key)
            deduped.append(asset)
    return deduped
