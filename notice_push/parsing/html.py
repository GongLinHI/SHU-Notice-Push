from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import datetime
from pathlib import PurePosixPath
from typing import Optional
from urllib.parse import parse_qs, unquote, urljoin, urlparse

from bs4 import Tag

from notice_push.domain import NoticeAsset


GENERIC_CONTENT_SELECTORS = (
    "#vsb_content .v_news_content",
    "#vsb_content",
    ".v_news_content",
    "main article",
    "article",
    "main",
    ".content",
    ".article",
    ".article-content",
    ".news_content",
    ".news-content",
)
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
DEFAULT_EXTERNAL_VIDEO_DOMAINS = ("kankanews.com",)
DEFAULT_NOISE_IMAGE_MARKERS = ("logo", "icon", "wx", "weixin", "qr", "blank", "spacer")


@dataclass(frozen=True)
class ParsingRules:
    external_video_domains: tuple[str, ...] = DEFAULT_EXTERNAL_VIDEO_DOMAINS
    noise_image_markers: tuple[str, ...] = DEFAULT_NOISE_IMAGE_MARKERS


DEFAULT_PARSING_RULES = ParsingRules()


def absolute_url(href: str, base_url: str) -> str:
    return urljoin(base_url, href.strip())


def clean_text(text: str) -> str:
    return re.sub(r"\s+", " ", text or "").strip()


def remove_noise_nodes(root: Tag) -> None:
    for node in root.select("script, style, noscript"):
        node.decompose()


def has_content_signal(root: Tag) -> bool:
    if clean_text(root.get_text(" ", strip=True)):
        return True
    for script in root.find_all("script"):
        script_text = script.string or script.get_text("", strip=False)
        if "showVsbpdfIframe" in script_text:
            return True
    return root.select_one("img[src], video, source[src], iframe[src]") is not None


def extract_text_blocks(root: Tag) -> str:
    remove_noise_nodes(root)
    blocks: list[str] = []
    seen_nodes: set[int] = set()

    for node in root.find_all(["p", "li", "tr"], recursive=True):
        seen_nodes.add(id(node))
        if node.name == "tr":
            cells = [clean_text(cell.get_text(" ", strip=True)) for cell in node.find_all(["td", "th"])]
            text = " ".join(cell for cell in cells if cell)
        else:
            text = clean_text(node.get_text(" ", strip=True))
        if text and (not blocks or blocks[-1] != text):
            blocks.append(text)

    if not blocks:
        text = clean_text(root.get_text(" ", strip=True))
        if text:
            blocks.append(text)

    return "\n".join(blocks)


def select_main_content(soup, selectors: list[str]) -> Tag | None:
    seen_selectors: set[str] = set()
    for selector in tuple(selectors) + GENERIC_CONTENT_SELECTORS:
        if selector in seen_selectors:
            continue
        seen_selectors.add(selector)
        node = soup.select_one(selector)
        if node is not None and has_content_signal(node):
            return node
    return None


def extract_assets(root: Tag, page_url: str, rules: ParsingRules = DEFAULT_PARSING_RULES) -> tuple[NoticeAsset, ...]:
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
    if content_node is None:
        return extract_assets(soup, page_url, rules=rules)
    return extract_assets(content_node, page_url, rules=rules)


def extract_link_assets(root: Tag, page_url: str) -> list[NoticeAsset]:
    assets: list[NoticeAsset] = []
    for anchor in root.find_all("a", href=True):
        href = anchor.get("href", "")
        text = clean_text(anchor.get_text(" ", strip=True))
        absolute = absolute_url(href, page_url)
        lower_path = urlparse(absolute).path.lower()
        suffix = PurePosixPath(lower_path).suffix
        if suffix in VIDEO_EXTENSIONS:
            assets.append(
                NoticeAsset(
                    kind="video",
                    role="primary",
                    name=text or _filename_from_url(absolute),
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
                name=text or _filename_from_url(absolute),
                url=absolute,
                mime_type=mime_type,
            )
        )
    return assets


def extract_image_assets(root: Tag, page_url: str, rules: ParsingRules = DEFAULT_PARSING_RULES) -> list[NoticeAsset]:
    assets: list[NoticeAsset] = []
    for image in root.find_all("img", src=True):
        src = image.get("src", "")
        absolute = absolute_url(src, page_url)
        lower_url = absolute.lower()
        if any(marker in lower_url for marker in rules.noise_image_markers):
            continue
        suffix = PurePosixPath(urlparse(absolute).path.lower()).suffix
        mime_type = IMAGE_EXTENSIONS.get(suffix, "")
        if suffix and suffix not in IMAGE_EXTENSIONS:
            continue
        alt = clean_text(image.get("alt", ""))
        assets.append(
            NoticeAsset(
                kind="image",
                role="primary",
                name=alt or _filename_from_url(absolute),
                url=absolute,
                mime_type=mime_type,
            )
        )
    return assets


def extract_video_assets(root: Tag, page_url: str, rules: ParsingRules = DEFAULT_PARSING_RULES) -> list[NoticeAsset]:
    assets: list[NoticeAsset] = []
    for node in root.find_all(["video", "source", "iframe"], src=True):
        src = node.get("src", "")
        absolute = absolute_url(src, page_url)
        if _is_external_video_url(absolute, rules):
            assets.append(
                NoticeAsset(
                    kind="external_video",
                    role="primary",
                    name=_filename_from_url(absolute) or absolute,
                    url=absolute,
                    mime_type="text/html",
                )
            )
            continue
        suffix = PurePosixPath(urlparse(absolute).path.lower()).suffix
        if suffix not in VIDEO_EXTENSIONS:
            continue
        assets.append(
            NoticeAsset(
                kind="video",
                role="primary",
                name=_filename_from_url(absolute),
                url=absolute,
                mime_type=VIDEO_EXTENSIONS[suffix],
            )
        )
    return assets


def extract_pdfjs_assets(root: Tag, page_url: str) -> list[NoticeAsset]:
    assets: list[NoticeAsset] = []
    for node in root.find_all(["iframe", "embed", "object"]):
        raw_url = node.get("src") or node.get("data") or ""
        pdf_url = _pdf_url_from_pdfjs_viewer(raw_url)
        if not pdf_url:
            continue
        absolute = absolute_url(pdf_url, page_url)
        assets.append(
            NoticeAsset(
                kind="pdf",
                role="attachment",
                name=_filename_from_url(absolute),
                url=absolute,
                mime_type="application/pdf",
            )
        )

    for script in root.find_all("script"):
        script_text = script.string or script.get_text("", strip=False)
        for raw_url in re.findall(r"showVsbpdfIframe\(\s*['\"]([^'\"]+\.pdf)['\"]", script_text, re.I):
            absolute = absolute_url(unquote(raw_url), page_url)
            assets.append(
                NoticeAsset(
                    kind="pdf",
                    role="attachment",
                    name=_filename_from_url(absolute),
                    url=absolute,
                    mime_type="application/pdf",
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


def is_external_video_page(url: str, rules: ParsingRules = DEFAULT_PARSING_RULES) -> bool:
    return _is_external_video_url(url, rules)


def promote_primary_assets(content_kind: str, assets: tuple[NoticeAsset, ...]) -> tuple[NoticeAsset, ...]:
    if content_kind not in {"pdf", "image", "video"}:
        return assets
    promoted: list[NoticeAsset] = []
    for asset in assets:
        if content_kind == "pdf" and asset.kind == "pdf":
            promoted.append(NoticeAsset(asset.kind, "primary", asset.name, asset.url, asset.mime_type))
        elif content_kind == "image" and asset.kind == "image":
            promoted.append(NoticeAsset(asset.kind, "primary", asset.name, asset.url, asset.mime_type))
        elif content_kind == "video" and asset.kind in {"video", "external_video"}:
            promoted.append(NoticeAsset(asset.kind, "primary", asset.name, asset.url, asset.mime_type))
        else:
            promoted.append(asset)
    return tuple(promoted)


def _dedupe_assets(assets: list[NoticeAsset]) -> list[NoticeAsset]:
    deduped: list[NoticeAsset] = []
    seen: set[tuple[str, str]] = set()
    for asset in assets:
        key = (asset.kind, asset.url)
        if key in seen:
            continue
        seen.add(key)
        deduped.append(asset)
    return deduped


def _filename_from_url(url: str) -> str:
    return PurePosixPath(urlparse(url).path).name


def _is_external_video_url(url: str, rules: ParsingRules) -> bool:
    hostname = (urlparse(url).hostname or "").lower()
    return any(hostname == domain or hostname.endswith(f".{domain}") for domain in rules.external_video_domains)


def _pdf_url_from_pdfjs_viewer(url: str) -> str:
    if not url:
        return ""
    parsed = urlparse(url)
    if "pdfjs" not in parsed.path.lower():
        return ""
    file_values = parse_qs(parsed.query).get("file", [])
    if not file_values:
        return ""
    file_url = unquote(file_values[0])
    return file_url if file_url.lower().endswith(".pdf") else ""


def parse_date(text: str) -> Optional[datetime]:
    if not text:
        return None

    patterns = [
        (r"(\d{4})\.(\d{1,2})\.(\d{1,2})", "%Y %m %d"),
        (r"(\d{4})-(\d{1,2})-(\d{1,2})", "%Y %m %d"),
        (r"(\d{4})/(\d{1,2})/(\d{1,2})\s+(\d{1,2}):(\d{1,2}):(\d{1,2})", "%Y %m %d %H %M %S"),
        (r"(\d{4})/(\d{1,2})/(\d{1,2})", "%Y %m %d"),
        (r"(\d{4})年\s*(\d{1,2})\s*月\s*(\d{1,2})\s*日\s+(\d{1,2}):(\d{1,2})", "%Y %m %d %H %M"),
        (r"(\d{4})年\s*(\d{1,2})\s*月\s*(\d{1,2})\s*日", "%Y %m %d"),
    ]

    for pattern, fmt in patterns:
        match = re.search(pattern, text)
        if not match:
            continue
        normalized = " ".join(match.groups())
        return datetime.strptime(normalized, fmt)
    return None
