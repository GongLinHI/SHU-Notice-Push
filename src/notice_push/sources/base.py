from __future__ import annotations

from abc import ABC, abstractmethod

from bs4 import BeautifulSoup

from src.notice_push.detail_parser import DetailParser
from src.notice_push.html_utils import absolute_url, clean_text
from src.notice_push.models import NoticeDetail, NoticeListItem, NoticeSource


class NoticeSourceAdapter(ABC):
    def __init__(self, source: NoticeSource, detail_parser: DetailParser | None = None):
        self.source = source
        self.detail_parser = detail_parser or DetailParser()

    @abstractmethod
    def parse_list_page(self, html: str, page_url: str) -> list[NoticeListItem]:
        raise NotImplementedError

    @abstractmethod
    def parse_detail(self, html: str, item: NoticeListItem) -> NoticeDetail:
        raise NotImplementedError

    def find_next_page_url(self, html: str, page_url: str) -> str | None:
        soup = BeautifulSoup(html, "html.parser")
        for anchor in soup.find_all("a", href=True):
            if clean_text(anchor.get_text()) == "下页":
                href = anchor.get("href", "")
                if href and not href.lower().startswith("javascript"):
                    return absolute_url(href, page_url)
        return None

    def _absolute_url(self, href: str, page_url: str) -> str:
        return absolute_url(href, page_url)
