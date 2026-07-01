from pathlib import Path

from src.notice_push.models import NoticeListItem
from src.notice_push.config import load_config
from src.notice_push.sources.graduate_school import GraduateSchoolAdapter
from src.notice_push.sources.management_school import ManagementSchoolAdapter
from src.notice_push.sources.shu_official import ShuOfficialAdapter


FIXTURE_DIR = Path(__file__).parents[1] / "fixtures" / "source_pages"


def read_fixture(name: str) -> str:
    return (FIXTURE_DIR / name).read_text(encoding="utf-8")


def test_shu_official_adapter_parses_list_next_page_and_detail(tmp_path):
    source = load_config(env={}, repo_root=tmp_path).source_by_id("shu_official")
    adapter = ShuOfficialAdapter(source)

    items = adapter.parse_list_page(read_fixture("shu_official_list.html"), source.list_url)
    detail = adapter.parse_detail(read_fixture("shu_official_detail.html"), items[0])

    assert len(items) == 1
    assert items[0].title == "关于宝山校区部分楼宇停电的通知"
    assert items[0].canonical_url == "https://www.shu.edu.cn/info/1051/397035.htm"
    assert items[0].published_at.year == 2026
    assert adapter.find_next_page_url(read_fixture("shu_official_list.html"), source.list_url) == "https://www.shu.edu.cn/tzgg/123.htm"
    assert detail.content == "广大师生：\n因电力检修，将会对宝山校区部分楼宇的用电产生影响。\n联系人：徐老师、王老师"
    assert detail.list_excerpt == "目录页摘要不应作为正文。"


def test_management_school_adapter_parses_table_list_next_page_and_detail(tmp_path):
    source = load_config(env={}, repo_root=tmp_path).source_by_id("management_school")
    adapter = ManagementSchoolAdapter(source)

    items = adapter.parse_list_page(read_fixture("management_school_list.html"), source.list_url)
    detail = adapter.parse_detail(read_fixture("management_school_detail.html"), items[0])

    assert len(items) == 1
    assert items[0].title == "管理学院关于2026年度本科生校长奖学金学院推荐名单公示"
    assert items[0].canonical_url == "https://ms.shu.edu.cn/info/1245/91925.htm"
    assert items[0].published_at.month == 4
    assert adapter.find_next_page_url(read_fixture("management_school_list.html"), source.list_url) == "https://ms.shu.edu.cn/syzl/zytz/52.htm"
    assert "经学生申请和学院评审" in detail.content
    assert "创建时间" not in detail.content


def test_graduate_school_adapter_parses_row_list_next_page_detail_and_attachment(tmp_path):
    source = load_config(env={}, repo_root=tmp_path).source_by_id("graduate_school")
    adapter = GraduateSchoolAdapter(source)

    items = adapter.parse_list_page(read_fixture("graduate_school_list.html"), source.list_url)
    detail = adapter.parse_detail(read_fixture("graduate_school_detail.html"), items[0])

    assert len(items) == 1
    assert items[0].title == "2026年上海大学高等教育（研究生）国家教学成果奖参评资格公示"
    assert items[0].canonical_url == "https://gs.shu.edu.cn/info/1026/173112.htm"
    assert items[0].published_at.hour == 14
    assert adapter.find_next_page_url(read_fixture("graduate_school_list.html"), source.list_url) == "https://gs.shu.edu.cn/xwlb/sy/6.htm"
    assert "研究生院首页" not in detail.content
    assert "国家教学成果奖参评资格" in detail.content
    assert detail.attachments[0].name == "附件【2026年上海大学高等教育（研究生）国家教学成果奖.pdf】"
    assert detail.attachments[0].url == "https://gs.shu.edu.cn/__local/1/2026.pdf"


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
        ShuOfficialAdapter(config.source_by_id("shu_official")),
        ManagementSchoolAdapter(config.source_by_id("management_school")),
        GraduateSchoolAdapter(config.source_by_id("graduate_school")),
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
