from datetime import date
from pathlib import Path

from src.spider.notice_getter import NoticeGetter


FIXTURE_DIR = Path(__file__).parents[1] / "fixtures" / "source_pages"


class _FakeHttpClient:
    def __init__(self, html: str):
        self.html = html

    def get_text(self, url: str) -> str:
        return self.html


def test_fetch_notice_list_uses_fixture_without_network():
    html = (FIXTURE_DIR / "shu_official_list.html").read_text(encoding="utf-8")
    notices = NoticeGetter.fetch_notice_list(http_client=_FakeHttpClient(html))

    assert len(notices) == 1
    assert notices[0].url == "https://www.shu.edu.cn/info/1051/397035.htm"
    assert notices[0].title == "关于宝山校区部分楼宇停电的通知"
    assert isinstance(notices[0].upload_time, date)


def test_dedup_and_save_to_csv_uses_temp_file(tmp_path):
    html = (FIXTURE_DIR / "shu_official_list.html").read_text(encoding="utf-8")
    notices = NoticeGetter.fetch_notice_list(http_client=_FakeHttpClient(html))
    csv_path = tmp_path / "notice_records.csv"

    first = NoticeGetter.dedup_and_save_to_csv(notices, csv_path=csv_path)
    second = NoticeGetter.dedup_and_save_to_csv(notices, csv_path=csv_path)

    assert len(first) == 1
    assert second == []
    assert csv_path.read_text(encoding="utf-8").count("397035") == 1
