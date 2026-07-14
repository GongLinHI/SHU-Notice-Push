from dataclasses import dataclass
from datetime import datetime
from pathlib import Path

import pytest

from notice_push.app_factory import build_detail_parser
from notice_push.domain import NoticeListItem
from notice_push.pipeline import create_adapter
from notice_push.settings.loader import load_config


pytestmark = pytest.mark.usefixtures("seed_runtime_config_for_temporary_repo")
FIXTURE_ROOT = Path(__file__).parents[1] / "fixtures" / "sources"


def _source_and_adapter(tmp_path, source_id):
    config = load_config(env={}, repo_root=tmp_path)
    source = config.source_by_id(source_id)
    return source, create_adapter(source, detail_parser=build_detail_parser(config))


@dataclass(frozen=True)
class ListContract:
    source_id: str
    next_page_url: str
    published_at: datetime


LIST_CONTRACTS = (
    ListContract(
        "shu_official",
        "https://www.shu.edu.cn/tzgg/123.htm",
        datetime(2026, 6, 16),
    ),
    ListContract(
        "management_school",
        "https://ms.shu.edu.cn/syzl/zytz/52.htm",
        datetime(2026, 4, 30),
    ),
    ListContract(
        "graduate_school",
        "https://gs.shu.edu.cn/xwlb/sy/6.htm",
        datetime(2026, 6, 29, 14, 52, 3),
    ),
)


def _read(source_id: str, name: str) -> str:
    return (FIXTURE_ROOT / source_id / name).read_text(encoding="utf-8")


@pytest.mark.parametrize("contract", LIST_CONTRACTS, ids=lambda contract: contract.source_id)
def test_source_list_and_pagination_contract(tmp_path, contract):
    source, adapter = _source_and_adapter(tmp_path, contract.source_id)
    html = _read(contract.source_id, "list.html")

    items = adapter.parse_list_page(html, source.list_url)

    assert items
    assert all(item.title and item.url and item.canonical_url for item in items)
    assert items[0].published_at == contract.published_at
    assert adapter.find_next_page_url(html, source.list_url) == contract.next_page_url


@pytest.mark.parametrize("source_id", [contract.source_id for contract in LIST_CONTRACTS])
def test_source_text_detail_contract(tmp_path, source_id):
    source, adapter = _source_and_adapter(tmp_path, source_id)
    item = adapter.parse_list_page(_read(source_id, "list.html"), source.list_url)[0]

    detail = adapter.parse_detail(_read(source_id, "detail_text.html"), item)

    assert detail.content_kind == "text"
    assert len(detail.content) >= 20
    assert detail.title
    assert detail.url == item.url


@pytest.mark.parametrize(
    ("source_id", "fixture_name", "url", "title", "content_kind", "asset_kind"),
    [
        (
            "management_school",
            "detail_pdf.html",
            "https://ms.shu.edu.cn/info/1245/91745.htm",
            "巡察公告",
            "pdf",
            "pdf",
        ),
        (
            "management_school",
            "detail_pdfjs.html",
            "https://ms.shu.edu.cn/info/1245/91745.htm",
            "巡察公告",
            "pdf",
            "pdf",
        ),
        (
            "management_school",
            "detail_image.html",
            "https://ms.shu.edu.cn/info/1245/91475.htm",
            "管理学院2026年寒假值班安排",
            "image",
            "image",
        ),
        (
            "graduate_school",
            "detail_pdfjs_script.html",
            "https://gs.shu.edu.cn/info/1029/172562.htm",
            "第二届全国教材建设奖推荐申报公示",
            "pdf",
            "pdf",
        ),
    ],
)
def test_source_media_detail_contract(tmp_path, source_id, fixture_name, url, title, content_kind, asset_kind):
    source, adapter = _source_and_adapter(tmp_path, source_id)
    item = NoticeListItem(source_id=source_id, url=url, canonical_url=url, title=title)

    detail = adapter.parse_detail(_read(source_id, fixture_name), item)

    assert detail.content_kind == content_kind
    assert any(asset.kind == asset_kind and asset.role == "primary" for asset in detail.assets)


@pytest.mark.parametrize("fixture_name", ["detail_video.html", "detail_video_static.html"])
def test_graduate_school_external_video_contract(tmp_path, fixture_name):
    source, adapter = _source_and_adapter(tmp_path, "graduate_school")
    url = "https://www.kankanews.com/detail/dZ2e81vaawR"
    item = NoticeListItem(
        source_id=source.id,
        url=url,
        canonical_url=url,
        title="卓越工程师学院承办上海市工程硕博士培养改革2026年招生工作校企对接会",
    )

    detail = adapter.parse_detail(_read(source.id, fixture_name), item)

    assert detail.content_kind == "video"
