from __future__ import annotations

from bs4 import BeautifulSoup, Tag

from src.notice_push.html_utils import absolute_url, clean_text, extract_text_blocks, parse_date, select_main_content
from src.notice_push.models import Attachment, NoticeDetail, NoticeListItem
from src.notice_push.sources.base import NoticeSourceAdapter


class GraduateSchoolAdapter(NoticeSourceAdapter):
    def parse_list_page(self, html: str, page_url: str) -> list[NoticeListItem]:
        soup = BeautifulSoup(html, "html.parser")
        items: list[NoticeListItem] = []
        for row in soup.select("tr[id^='line_u17_']"):
            anchor = row.select_one("a[href]")
            cells = [clean_text(cell.get_text(" ", strip=True)) for cell in row.find_all("td")]
            if not anchor or len(cells) < 2:
                continue
            url = self._absolute_url(anchor.get("href", ""), page_url)
            title = clean_text(anchor.get_text(" ", strip=True))
            if not title:
                continue
            items.append(
                NoticeListItem(
                    source_id=self.source.id,
                    url=url,
                    canonical_url=url,
                    title=title,
                    published_at=parse_date(cells[1]),
                )
            )
        return items

    def parse_detail(self, html: str, item: NoticeListItem) -> NoticeDetail:
        soup = BeautifulSoup(html, "html.parser")
        content_node = select_main_content(soup, ["#vsb_content .v_news_content", ".v_news_content"])
        body_text = clean_text(soup.get_text(" ", strip=True))
        content = extract_text_blocks(content_node) if content_node else ""
        attachments = self._extract_attachments(content_node, item.url) if content_node else ()
        return NoticeDetail(
            source_id=item.source_id,
            url=item.url,
            canonical_url=item.canonical_url,
            title=item.title,
            published_at=parse_date(body_text) or item.published_at,
            list_excerpt=item.list_excerpt,
            content=content,
            attachments=attachments,
        )

    def _extract_attachments(self, content_node: Tag, page_url: str) -> tuple[Attachment, ...]:
        attachments: list[Attachment] = []
        for anchor in content_node.find_all("a", href=True):
            href = anchor.get("href", "")
            text = clean_text(anchor.get_text(" ", strip=True))
            lower = href.lower()
            if "附件" not in text and not lower.endswith((".pdf", ".doc", ".docx", ".xls", ".xlsx", ".zip", ".rar")):
                continue
            attachments.append(Attachment(name=text, url=absolute_url(href, page_url)))
        return tuple(attachments)
