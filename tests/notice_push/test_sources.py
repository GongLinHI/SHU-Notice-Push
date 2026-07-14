from pathlib import Path

import pytest

pytestmark = pytest.mark.usefixtures("seed_runtime_config_for_temporary_repo")

from notice_push.app_factory import build_detail_parser
from notice_push.parsing.detail import ParsedDetailBody
from notice_push.domain import NoticeListItem
from notice_push.settings.loader import load_config
from notice_push.sources.graduate_school import GraduateSchoolAdapter
from notice_push.sources.management_school import ManagementSchoolAdapter
from notice_push.sources.shu_official import ShuOfficialAdapter


FIXTURE_DIR = Path(__file__).parents[1] / "fixtures" / "sources"


def _source_and_adapter(tmp_path, source_id, adapter_type):
    config = load_config(env={}, repo_root=tmp_path)
    source = config.source_by_id(source_id)
    return source, adapter_type(source, detail_parser=build_detail_parser(config))


def read_fixture(name: str) -> str:
    return (FIXTURE_DIR / name).read_text(encoding="utf-8")


def test_shu_official_adapter_parses_list_next_page_and_detail(tmp_path):
    source, adapter = _source_and_adapter(tmp_path, "shu_official", ShuOfficialAdapter)

    items = adapter.parse_list_page(read_fixture("shu_official/list.html"), source.list_url)
    detail = adapter.parse_detail(read_fixture("shu_official/detail_text.html"), items[0])

    assert len(items) == 1
    assert items[0].title == "关于宝山校区部分楼宇停电的通知"
    assert items[0].canonical_url == "https://www.shu.edu.cn/info/1051/397035.htm"
    assert items[0].published_at.year == 2026
    assert adapter.find_next_page_url(read_fixture("shu_official/list.html"), source.list_url) == "https://www.shu.edu.cn/tzgg/123.htm"
    assert detail.content == "广大师生：\n因电力检修，将会对宝山校区部分楼宇的用电产生影响。\n联系人：甲老师、乙老师"
    assert detail.list_excerpt == "目录页摘要不应作为正文。"


def test_source_adapter_uses_injected_detail_parser(tmp_path):
    class FakeDetailParser:
        def parse_body(self, soup, page_url, selectors, forced_content_kind=None):
            return ParsedDetailBody(
                content="由注入解析器产生的正文",
                assets=(),
                content_kind="text",
                content_node=None,
            )

    source = load_config(env={}, repo_root=tmp_path).source_by_id("shu_official")
    adapter = ShuOfficialAdapter(source, detail_parser=FakeDetailParser())
    item = NoticeListItem(
        source_id=source.id,
        url="https://www.shu.edu.cn/info/1051/397035.htm",
        canonical_url="https://www.shu.edu.cn/info/1051/397035.htm",
        title="注入解析器测试",
    )

    detail = adapter.parse_detail("<html><body><h1>注入解析器测试</h1></body></html>", item)

    assert detail.content == "由注入解析器产生的正文"


def test_management_school_adapter_parses_table_list_next_page_and_detail(tmp_path):
    source, adapter = _source_and_adapter(tmp_path, "management_school", ManagementSchoolAdapter)

    items = adapter.parse_list_page(read_fixture("management_school/list.html"), source.list_url)
    detail = adapter.parse_detail(read_fixture("management_school/detail_text.html"), items[0])

    assert len(items) == 1
    assert items[0].title == "管理学院关于2026年度本科生校长奖学金学院推荐名单公示"
    assert items[0].canonical_url == "https://ms.shu.edu.cn/info/1245/91925.htm"
    assert items[0].published_at.month == 4
    assert adapter.find_next_page_url(read_fixture("management_school/list.html"), source.list_url) == "https://ms.shu.edu.cn/syzl/zytz/52.htm"
    assert "经学生申请和学院评审" in detail.content
    assert "创建时间" not in detail.content


def test_management_school_adapter_extracts_pdf_body_asset(tmp_path):
    source, adapter = _source_and_adapter(tmp_path, "management_school", ManagementSchoolAdapter)
    item = NoticeListItem(
        source_id=source.id,
        url="https://ms.shu.edu.cn/info/1245/91745.htm",
        canonical_url="https://ms.shu.edu.cn/info/1245/91745.htm",
        title="巡察公告",
    )

    detail = adapter.parse_detail(read_fixture("management_school/detail_pdf.html"), item)

    assert detail.content_kind == "pdf"
    assert detail.assets[0].kind == "pdf"
    assert detail.assets[0].role == "primary"
    assert detail.assets[0].name == "巡察公告.pdf"
    assert detail.assets[0].url == "https://ms.shu.edu.cn/__local/inspection.pdf"


def test_management_school_adapter_extracts_pdfjs_iframe_body_asset(tmp_path):
    source, adapter = _source_and_adapter(tmp_path, "management_school", ManagementSchoolAdapter)
    item = NoticeListItem(
        source_id=source.id,
        url="https://ms.shu.edu.cn/info/1245/91745.htm",
        canonical_url="https://ms.shu.edu.cn/info/1245/91745.htm",
        title="巡察公告",
    )

    detail = adapter.parse_detail(read_fixture("management_school/detail_pdfjs.html"), item)

    assert detail.content_kind == "pdf"
    assert detail.assets[0].kind == "pdf"
    assert detail.assets[0].role == "primary"
    assert detail.assets[0].url == "https://ms.shu.edu.cn/__local/2/23/64/inspection.pdf"


def test_management_school_adapter_extracts_image_body_asset(tmp_path):
    source, adapter = _source_and_adapter(tmp_path, "management_school", ManagementSchoolAdapter)
    item = NoticeListItem(
        source_id=source.id,
        url="https://ms.shu.edu.cn/info/1245/91475.htm",
        canonical_url="https://ms.shu.edu.cn/info/1245/91475.htm",
        title="管理学院2026年寒假值班安排",
    )

    detail = adapter.parse_detail(read_fixture("management_school/detail_image.html"), item)

    assert detail.content_kind == "image"
    assert detail.assets[0].kind == "image"
    assert detail.assets[0].role == "primary"
    assert detail.assets[0].name == "值班安排.png"
    assert detail.assets[0].url == "https://ms.shu.edu.cn/__local/duty.png"


def test_graduate_school_adapter_extracts_pdfjs_script_body_asset(tmp_path):
    source, adapter = _source_and_adapter(tmp_path, "graduate_school", GraduateSchoolAdapter)
    item = NoticeListItem(
        source_id=source.id,
        url="https://gs.shu.edu.cn/info/1029/172562.htm",
        canonical_url="https://gs.shu.edu.cn/info/1029/172562.htm",
        title="第二届全国教材建设奖推荐申报公示",
    )

    detail = adapter.parse_detail(read_fixture("graduate_school/detail_pdfjs_script.html"), item)

    assert detail.content_kind == "pdf"
    assert detail.assets[0].kind == "pdf"
    assert detail.assets[0].role == "primary"
    assert detail.assets[0].url == "https://gs.shu.edu.cn/__local/C/DC/99/textbook.pdf"
    assert all("unrelated-form.pdf" not in asset.url for asset in detail.assets)


def test_graduate_school_adapter_extracts_external_video_asset(tmp_path):
    source, adapter = _source_and_adapter(tmp_path, "graduate_school", GraduateSchoolAdapter)
    item = NoticeListItem(
        source_id=source.id,
        url="https://www.kankanews.com/detail/dZ2e81vaawR",
        canonical_url="https://www.kankanews.com/detail/dZ2e81vaawR",
        title="卓越工程师学院承办上海市工程硕博士培养改革2026年招生工作校企对接会",
    )

    detail = adapter.parse_detail(read_fixture("graduate_school/detail_video.html"), item)

    assert detail.content_kind == "video"
    assert detail.assets == ()


def test_graduate_school_adapter_marks_kankanews_static_detail_as_external_video(tmp_path):
    source, adapter = _source_and_adapter(tmp_path, "graduate_school", GraduateSchoolAdapter)
    item = NoticeListItem(
        source_id=source.id,
        url="https://www.kankanews.com/detail/dZ2e81vaawR",
        canonical_url="https://www.kankanews.com/detail/dZ2e81vaawR",
        title="卓越工程师学院承办上海市工程硕博士培养改革2026年招生工作校企对接会",
    )

    detail = adapter.parse_detail(read_fixture("graduate_school/detail_video_static.html"), item)

    assert detail.content_kind == "video"
    assert detail.assets == ()


def test_graduate_school_adapter_parses_row_list_next_page_detail_and_attachment(tmp_path):
    source, adapter = _source_and_adapter(tmp_path, "graduate_school", GraduateSchoolAdapter)

    items = adapter.parse_list_page(read_fixture("graduate_school/list.html"), source.list_url)
    detail = adapter.parse_detail(read_fixture("graduate_school/detail_text.html"), items[0])

    assert len(items) == 1
    assert items[0].title == "2026年上海大学高等教育（研究生）国家教学成果奖参评资格公示"
    assert items[0].canonical_url == "https://gs.shu.edu.cn/info/1026/173112.htm"
    assert items[0].published_at.hour == 14
    assert adapter.find_next_page_url(read_fixture("graduate_school/list.html"), source.list_url) == "https://gs.shu.edu.cn/xwlb/sy/6.htm"
    assert "研究生院首页" not in detail.content
    assert "国家教学成果奖参评资格" in detail.content
    assert detail.attachments[0].name == "附件【2026年上海大学高等教育（研究生）国家教学成果奖.pdf】"
    assert detail.attachments[0].url == "https://gs.shu.edu.cn/__local/1/2026.pdf"
    assert detail.assets[0].kind == "pdf"
    assert detail.assets[0].url == "https://gs.shu.edu.cn/__local/1/2026.pdf"


def test_source_adapters_fallback_to_generic_article_content(tmp_path):
    config = load_config(env={}, repo_root=tmp_path)
    html = """
    <html>
      <body>
        <main>
          <h1>备用正文容器通知</h1>
          <article>
            <p>这是来自通用 article 容器的第一段正文。</p>
            <p>这是来自通用 article 容器的第二段正文。</p>
          </article>
        </main>
      </body>
    </html>
    """
    adapters = [
        ShuOfficialAdapter(config.source_by_id("shu_official"), detail_parser=build_detail_parser(config)),
        ManagementSchoolAdapter(
            config.source_by_id("management_school"),
            detail_parser=build_detail_parser(config),
        ),
        GraduateSchoolAdapter(
            config.source_by_id("graduate_school"),
            detail_parser=build_detail_parser(config),
        ),
    ]

    for adapter in adapters:
        source = adapter.source
        detail = adapter.parse_detail(
            html,
            NoticeListItem(
                source_id=source.id,
                url=source.list_url,
                canonical_url=source.list_url,
                title="备用正文容器通知",
            ),
        )
        assert "通用 article 容器的第一段正文" in detail.content
        assert "通用 article 容器的第二段正文" in detail.content
