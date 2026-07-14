from __future__ import annotations

import re
from dataclasses import dataclass

from bs4 import Tag


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
@dataclass(frozen=True)
class ParsingRules:
    external_video_domains: tuple[str, ...] = ()
    noise_image_markers: tuple[str, ...] = ()


DEFAULT_PARSING_RULES = ParsingRules()


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
    for node in root.find_all(["p", "li", "tr"], recursive=True):
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
