from __future__ import annotations

from dataclasses import dataclass

from bs4 import BeautifulSoup, Tag

from notice_push.parsing.html import (
    DEFAULT_PARSING_RULES,
    ParsingRules,
    extract_detail_assets,
    extract_text_blocks,
    infer_content_kind,
    promote_primary_assets,
    select_main_content,
)
from notice_push.domain import NoticeAsset


@dataclass(frozen=True)
class ParsedDetailBody:
    content: str
    assets: tuple[NoticeAsset, ...]
    content_kind: str
    content_node: Tag | None


class DetailParser:
    def __init__(self, rules: ParsingRules = DEFAULT_PARSING_RULES):
        self.rules = rules

    def parse_body(
        self,
        soup: BeautifulSoup,
        page_url: str,
        selectors: list[str],
        forced_content_kind: str | None = None,
    ) -> ParsedDetailBody:
        content_node = select_main_content(soup, selectors)
        assets = extract_detail_assets(content_node, soup, page_url, rules=self.rules)
        content = extract_text_blocks(content_node) if content_node else ""
        content_kind = forced_content_kind or infer_content_kind(content, assets)
        if forced_content_kind == "video":
            assets = ()
        else:
            assets = promote_primary_assets(content_kind, assets)
        return ParsedDetailBody(
            content=content,
            assets=assets,
            content_kind=content_kind,
            content_node=content_node,
        )
