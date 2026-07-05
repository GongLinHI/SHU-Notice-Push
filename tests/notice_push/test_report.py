from datetime import date, datetime

from src.notice_push.models import Attachment, FailedNotice, NoticeAsset, NoticeDetail, NoticeSummary, ReportStats
from src.notice_push.report import ReportEntry, render_report, write_report


def make_entry() -> ReportEntry:
    detail = NoticeDetail(
        source_id="shu_official",
        url="https://www.shu.edu.cn/info/1051/397035.htm",
        canonical_url="https://www.shu.edu.cn/info/1051/397035.htm",
        title="关于宝山校区部分楼宇停电的通知",
        content="详情页正文",
        published_at=datetime(2026, 6, 16),
        attachments=(Attachment(name="附件.pdf", url="https://example.com/a.pdf"),),
    )
    summary = NoticeSummary(
        notice_id=1,
        markdown="## 上海大学官网|服务|三日限期|关于宝山校区部分楼宇停电的通知",
        model="deepseek-chat",
        prompt_version="notice_summary_v1",
        generated_at=datetime(2026, 6, 30, 8, 0),
    )
    return ReportEntry(source_id="shu_official", source_name="上海大学官网", detail=detail, summary=summary)


def test_render_report_groups_summaries_and_failures():
    markdown = render_report(
        report_date=date(2026, 6, 30),
        entries=[make_entry()],
        failures=[
            FailedNotice(
                source_id="graduate_school",
                source_name="上海大学研究生院",
                title="详情抓取失败的通知",
                url="https://gs.shu.edu.cn/info/1.htm",
                reason="detail content is empty",
                published_at=datetime(2026, 6, 29),
            )
        ],
        stats=ReportStats(new_count=2, retried_count=0, summarized_count=1, manual_review_count=1),
    )

    assert "## 运行概览" in markdown
    assert "- 新增通知: 2" in markdown
    assert "- 成功摘要: 1" in markdown
    assert "- 按来源统计:" in markdown
    assert "上海大学官网: 处理 1，成功 1，失败 0" in markdown
    assert "上海大学研究生院: 处理 1，成功 0，失败 1" in markdown
    assert "## 上海大学官网" in markdown
    assert "关于宝山校区部分楼宇停电的通知" in markdown
    assert "[附件.pdf](https://example.com/a.pdf)" in markdown
    assert "## 需要人工复核" in markdown
    assert "- **来源**: 上海大学研究生院" in markdown
    assert "detail content is empty" in markdown


def test_render_report_uses_explicit_stats_for_retry_only_report():
    entry = make_entry()

    markdown = render_report(
        report_date=date(2026, 7, 5),
        entries=[entry],
        failures=[],
        stats=ReportStats(new_count=0, retried_count=1, summarized_count=1, manual_review_count=0),
    )

    assert "- 新增通知: 0" in markdown
    assert "- 重试通知: 1" in markdown
    assert "- 成功摘要: 1" in markdown
    assert "新增 1" not in markdown


def test_render_report_includes_assets_when_attachments_are_empty():
    detail = NoticeDetail(
        source_id="management_school",
        url="https://ms.shu.edu.cn/info/1245/91475.htm",
        canonical_url="https://ms.shu.edu.cn/info/1245/91475.htm",
        title="管理学院2026年寒假值班安排",
        content="",
        assets=(
            NoticeAsset(
                kind="image",
                role="primary",
                name="值班安排.png",
                url="https://ms.shu.edu.cn/__local/duty.png",
                mime_type="image/png",
            ),
        ),
        content_kind="image",
    )
    summary = NoticeSummary(
        notice_id=1,
        markdown="## 上海大学管理学院|行政|周常事务|管理学院2026年寒假值班安排",
        model="kimi-k2.7-code",
        prompt_version="notice_summary_v1",
        generated_at=datetime(2026, 7, 5),
    )

    markdown = render_report(
        date(2026, 7, 5),
        [ReportEntry("management_school", "上海大学管理学院", detail, summary)],
        [],
        ReportStats(new_count=1, retried_count=0, summarized_count=1, manual_review_count=0),
    )

    assert "- **附件**: [值班安排.png](https://ms.shu.edu.cn/__local/duty.png)" in markdown


def test_write_report_creates_date_named_markdown(tmp_path):
    path = write_report(tmp_path, date(2026, 6, 30), "report")

    assert path == tmp_path / "2026-06-30.md"
    assert path.read_text(encoding="utf-8") == "report"
