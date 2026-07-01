from __future__ import annotations

from bs4 import BeautifulSoup

from src.notice_push.html_utils import clean_text, extract_text_blocks, parse_date, select_main_content
from src.notice_push.models import NoticeDetail, NoticeListItem
from src.notice_push.sources.base import NoticeSourceAdapter


class ShuOfficialAdapter(NoticeSourceAdapter):
    def parse_list_page(self, html: str, page_url: str) -> list[NoticeListItem]:
        soup = BeautifulSoup(html, "html.parser")
        items: list[NoticeListItem] = []
        for anchor in soup.select(".ej_main ul li a[href]"):
            url = self._absolute_url(anchor.get("href", ""), page_url)
            title = clean_text(anchor.select_one(".bt").get_text(" ", strip=True) if anchor.select_one(".bt") else anchor.get_text(" ", strip=True))
            if not title:
                continue
            excerpt_node = anchor.select_one(".zy")
            date_node = anchor.select_one(".sj")
            items.append(
                NoticeListItem(
                    source_id=self.source.id,
                    url=url,
                    canonical_url=url,
                    title=title,
                    published_at=parse_date(clean_text(date_node.get_text(" ", strip=True)) if date_node else ""),
                    list_excerpt=clean_text(excerpt_node.get_text(" ", strip=True)) if excerpt_node else "",
                )
            )
        return items

    def parse_detail(self, html: str, item: NoticeListItem) -> NoticeDetail:
        soup = BeautifulSoup(html, "html.parser")
        title_node = soup.select_one("h1[align='center'], h1")
        meta_node = soup.select_one(".xx")
        content_node = select_main_content(soup, [".v_news_content"])
        content = extract_text_blocks(content_node) if content_node else ""
        return NoticeDetail(
            source_id=item.source_id,
            url=item.url,
            canonical_url=item.canonical_url,
            title=clean_text(title_node.get_text(" ", strip=True)) if title_node else item.title,
            published_at=parse_date(clean_text(meta_node.get_text(" ", strip=True)) if meta_node else "") or item.published_at,
            list_excerpt=item.list_excerpt,
            content=content,
        )
