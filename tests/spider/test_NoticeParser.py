from pathlib import Path

from src.entry.notice import Notice
from src.spider.page_parser import PageParser


FIXTURE_DIR = Path(__file__).parents[1] / "fixtures" / "source_pages"


class _FakeResponse:
    def __init__(self, html: str):
        self.content = html.encode("utf-8")

    def raise_for_status(self):
        return None


class _FakeHttpClient:
    def __init__(self, html: str):
        self.html = html

    def get_text(self, url: str) -> str:
        return self.html


def test_parse_notice_detail_uses_fixture_without_network():
    html = (FIXTURE_DIR / "shu_official_detail.html").read_text(encoding="utf-8")
    notice = Notice.Builder().set_url("https://www.shu.edu.cn/info/1051/397035.htm").build()

    page = PageParser.parse(notice, http_client=_FakeHttpClient(html))

    assert page.title == "关于宝山校区部分楼宇停电的通知"
    assert "因电力检修" in page.content
    assert page.upload_time.isoformat() == "2026-06-16"
