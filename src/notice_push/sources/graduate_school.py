from __future__ import annotations

from bs4 import BeautifulSoup

from src.notice_push.html_utils import clean_text, extract_detail_assets, extract_text_blocks, infer_content_kind, is_external_video_page, parse_date, promote_primary_assets, select_main_content
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
        assets = extract_detail_assets(content_node, soup, item.url)
        content = extract_text_blocks(content_node) if content_node else ""
        content_kind = infer_content_kind(content, assets)
        if is_external_video_page(item.url):
            content_kind = "video"
            assets = ()
        assets = promote_primary_assets(content_kind, assets)
        attachments = self._attachments_from_assets(assets)
        return NoticeDetail(
            source_id=item.source_id,
            url=item.url,
            canonical_url=item.canonical_url,
            title=item.title,
            published_at=parse_date(body_text) or item.published_at,
            list_excerpt=item.list_excerpt,
            content=content,
            attachments=attachments,
            assets=assets,
            content_kind=content_kind,
        )

    def _attachments_from_assets(self, assets) -> tuple[Attachment, ...]:
        return tuple(
            Attachment(name=asset.name, url=asset.url)
            for asset in assets
            if asset.kind in {"pdf", "file"}
        )
