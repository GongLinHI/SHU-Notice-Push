from datetime import datetime

from bs4 import BeautifulSoup

from src.notice_push.html_utils import (
    absolute_url,
    clean_text,
    extract_text_blocks,
    parse_date,
    remove_noise_nodes,
)


def test_absolute_url_resolves_relative_paths():
    assert (
        absolute_url("info/1051/397035.htm", "https://www.shu.edu.cn/tzgg.htm")
        == "https://www.shu.edu.cn/info/1051/397035.htm"
    )
    assert (
        absolute_url("../info/1245/92085.htm", "https://ms.shu.edu.cn/syzl/zytz.htm")
        == "https://ms.shu.edu.cn/info/1245/92085.htm"
    )
    assert (
        absolute_url("https://gs.shu.edu.cn/info/1026/173112.htm", "https://gs.shu.edu.cn/xwlb/sy.htm")
        == "https://gs.shu.edu.cn/info/1026/173112.htm"
    )


def test_clean_text_normalizes_whitespace():
    assert clean_text(" 广大师生：\n\n  请\t注意  停电安排。 ") == "广大师生： 请 注意 停电安排。"


def test_parse_date_supports_observed_source_formats():
    assert parse_date("2026.06.25") == datetime(2026, 6, 25)
    assert parse_date("2026-06-09") == datetime(2026, 6, 9)
    assert parse_date("2026/06/29 14:52:03") == datetime(2026, 6, 29, 14, 52, 3)
    assert parse_date("时间: 2026年06月29日 14:52") == datetime(2026, 6, 29, 14, 52)
    assert parse_date("发布时间：2026-06-16投稿：钱杰妮") == datetime(2026, 6, 16)
    assert parse_date("") is None


def test_remove_noise_nodes_and_extract_text_blocks():
    soup = BeautifulSoup(
        """
        <div class="v_news_content">
          <style>.x{}</style>
          <script>alert(1)</script>
          <p>广大师生：</p>
          <p>请注意停电安排。</p>
          <table>
            <tr><td>停电时间</td><td>2026年6月16日</td></tr>
          </table>
        </div>
        """,
        "html.parser",
    )
    content = soup.select_one(".v_news_content")

    remove_noise_nodes(content)

    assert "alert" not in content.get_text()
    assert extract_text_blocks(content) == "广大师生：\n请注意停电安排。\n停电时间 2026年6月16日"
