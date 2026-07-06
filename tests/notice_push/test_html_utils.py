from datetime import datetime

from bs4 import BeautifulSoup

from notice_push.parsing.html import (
    ParsingRules,
    absolute_url,
    clean_text,
    extract_image_assets,
    extract_pdfjs_assets,
    extract_text_blocks,
    infer_content_kind,
    is_external_video_page,
    parse_date,
    remove_noise_nodes,
)
from notice_push.domain import NoticeAsset


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


def test_infer_content_kind_prefers_substantive_text_over_external_video_asset():
    assets = (
        NoticeAsset(
            kind="external_video",
            role="primary",
            name="看看新闻视频页",
            url="https://www.kankanews.com/detail/dZ2e81vaawR",
            mime_type="text/html",
        ),
    )

    assert infer_content_kind("这是通知正文，已经足够说明事项安排。", assets) == "text"


def test_infer_content_kind_keeps_empty_external_video_page_as_video():
    assets = (
        NoticeAsset(
            kind="external_video",
            role="primary",
            name="看看新闻视频页",
            url="https://www.kankanews.com/detail/dZ2e81vaawR",
            mime_type="text/html",
        ),
    )

    assert infer_content_kind("", assets) == "video"


def test_explicit_parsing_rules_affect_video_domains_and_noise_images():
    rules = ParsingRules(
        external_video_domains=("video.example.edu",),
        noise_image_markers=("tracking",),
    )

    assert is_external_video_page("https://media.video.example.edu/watch/123", rules=rules)
    assert not is_external_video_page("https://www.kankanews.com/detail/dZ2e81vaawR", rules=rules)

    soup = BeautifulSoup(
        """
        <div>
          <img src="/images/notice.png" alt="通知主体">
          <img src="/images/tracking-pixel.png" alt="统计图">
        </div>
        """,
        "html.parser",
    )

    assets = extract_image_assets(soup, "https://example.edu/info/1.htm", rules=rules)

    assert [asset.url for asset in assets] == ["https://example.edu/images/notice.png"]


def test_extract_pdfjs_assets_accepts_file_query_with_pdf_url_query():
    soup = BeautifulSoup(
        """
        <div>
          <iframe src="/pdfjs/web/viewer.html?file=/__local/textbook.pdf%3Ftoken%3Dabc"></iframe>
        </div>
        """,
        "html.parser",
    )

    assets = extract_pdfjs_assets(soup, "https://gs.shu.edu.cn/info/1029/172562.htm")

    assert len(assets) == 1
    assert assets[0].kind == "pdf"
    assert assets[0].url == "https://gs.shu.edu.cn/__local/textbook.pdf?token=abc"


def test_extract_pdfjs_assets_accepts_show_vsbpdfiframe_pdf_with_query():
    soup = BeautifulSoup(
        """
        <script>
          showVsbpdfIframe('/__local/inspection.pdf?download=true');
        </script>
        """,
        "html.parser",
    )

    assets = extract_pdfjs_assets(soup, "https://ms.shu.edu.cn/info/1245/91745.htm")

    assert len(assets) == 1
    assert assets[0].kind == "pdf"
    assert assets[0].url == "https://ms.shu.edu.cn/__local/inspection.pdf?download=true"
