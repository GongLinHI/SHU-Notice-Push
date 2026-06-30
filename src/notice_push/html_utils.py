from __future__ import annotations

import re
from datetime import datetime
from typing import Optional
from urllib.parse import urljoin

from bs4 import Tag


def absolute_url(href: str, base_url: str) -> str:
    return urljoin(base_url, href.strip())


def clean_text(text: str) -> str:
    return re.sub(r"\s+", " ", text or "").strip()


def remove_noise_nodes(root: Tag) -> None:
    for node in root.select("script, style, noscript"):
        node.decompose()


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
