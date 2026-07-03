from __future__ import annotations

from bs4 import BeautifulSoup

from src.notice_push.html_utils import clean_text, extract_assets, extract_text_blocks, infer_content_kind, parse_date, promote_primary_assets, select_main_content
from src.notice_push.models import NoticeDetail, NoticeListItem
from src.notice_push.sources.base import NoticeSourceAdapter


class ManagementSchoolAdapter(NoticeSourceAdapter):
    def parse_list_page(self, html: str, page_url: str) -> list[NoticeListItem]:
        soup = BeautifulSoup(html, "html.parser")
        items: list[NoticeListItem] = []
        for table in soup.select("table.ArtList"):
            anchor = table.select_one("a[href]")
            if not anchor:
                continue
            url = self._absolute_url(anchor.get("href", ""), page_url)
            title = clean_text(anchor.get("title") or anchor.get_text(" ", strip=True))
            if not title:
                continue
            date_text = ""
            for span in table.select("span.linkfont1, span"):
                candidate = clean_text(span.get_text(" ", strip=True))
                if parse_date(candidate):
                    date_text = candidate
                    break
            items.append(
                NoticeListItem(
                    source_id=self.source.id,
                    url=url,
                    canonical_url=url,
                    title=title,
                    published_at=parse_date(date_text),
                )
            )
        return items

    def parse_detail(self, html: str, item: NoticeListItem) -> NoticeDetail:
        soup = BeautifulSoup(html, "html.parser")
        title_node = soup.select_one("#HRCMS_ctr13929_CalendarDetail_lblTitle")
        content_node = select_main_content(soup, [".v_news_content"])
        body_text = clean_text(soup.get_text(" ", strip=True))
        content = extract_text_blocks(content_node) if content_node else ""
        assets = extract_assets(content_node, item.url) if content_node else ()
        content_kind = infer_content_kind(content, assets)
        assets = promote_primary_assets(content_kind, assets)
        return NoticeDetail(
            source_id=item.source_id,
            url=item.url,
            canonical_url=item.canonical_url,
            title=clean_text(title_node.get_text(" ", strip=True)) if title_node else item.title,
            published_at=parse_date(body_text) or item.published_at,
            list_excerpt=item.list_excerpt,
            content=content,
            assets=assets,
            content_kind=content_kind,
        )
