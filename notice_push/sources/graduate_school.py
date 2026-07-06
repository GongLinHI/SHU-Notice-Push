from __future__ import annotations

from bs4 import BeautifulSoup

from notice_push.parsing.html import clean_text, is_external_video_page, parse_date
from notice_push.domain import Attachment, NoticeDetail, NoticeListItem
from notice_push.sources.base import NoticeSourceAdapter


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
        body_text = clean_text(soup.get_text(" ", strip=True))
        body = self.detail_parser.parse_body(
            soup,
            item.url,
            ["#vsb_content .v_news_content", ".v_news_content"],
            forced_content_kind="video" if is_external_video_page(item.url, rules=self.detail_parser.rules) else None,
        )
        attachments = self._attachments_from_assets(body.assets)
        return NoticeDetail(
            source_id=item.source_id,
            url=item.url,
            canonical_url=item.canonical_url,
            title=item.title,
            published_at=parse_date(body_text) or item.published_at,
            list_excerpt=item.list_excerpt,
            content=body.content,
            attachments=attachments,
            assets=body.assets,
            content_kind=body.content_kind,
        )

    def _attachments_from_assets(self, assets) -> tuple[Attachment, ...]:
        return tuple(
            Attachment(name=asset.name, url=asset.url)
            for asset in assets
            if asset.kind in {"pdf", "file"}
        )
