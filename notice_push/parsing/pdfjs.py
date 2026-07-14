from __future__ import annotations

import re
from urllib.parse import parse_qs, unquote, urlparse

from bs4 import Tag

from notice_push.domain import NoticeAsset
from notice_push.parsing.urls import absolute_url, filename_from_url


def extract_pdfjs_assets(root: Tag, page_url: str) -> list[NoticeAsset]:
    assets: list[NoticeAsset] = []
    for node in root.find_all(["iframe", "embed", "object"]):
        raw_url = node.get("src") or node.get("data") or ""
        pdf_url = _pdf_url_from_viewer(raw_url)
        if pdf_url:
            assets.append(_pdf_asset(pdf_url, page_url))

    for script in root.find_all("script"):
        script_text = script.string or script.get_text("", strip=False)
        raw_urls = re.findall(
            r"showVsbpdfIframe\(\s*['\"]([^'\"]+\.pdf(?:\?[^'\"]*)?)['\"]",
            script_text,
            re.I,
        )
        assets.extend(_pdf_asset(unquote(raw_url), page_url) for raw_url in raw_urls)
    return assets


def _pdf_asset(raw_url: str, page_url: str) -> NoticeAsset:
    url = absolute_url(raw_url, page_url)
    return NoticeAsset(
        kind="pdf",
        role="attachment",
        name=filename_from_url(url),
        url=url,
        mime_type="application/pdf",
    )


def _pdf_url_from_viewer(url: str) -> str:
    if not url:
        return ""
    parsed = urlparse(url)
    if "pdfjs" not in parsed.path.lower():
        return ""
    file_values = parse_qs(parsed.query).get("file", [])
    if not file_values:
        return ""
    file_url = unquote(file_values[0])
    return file_url if urlparse(file_url).path.lower().endswith(".pdf") else ""
