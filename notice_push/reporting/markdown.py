from __future__ import annotations

from dataclasses import dataclass
from datetime import date
from collections import defaultdict
from itertools import groupby
from pathlib import Path

from notice_push.domain import FailedNotice, NoticeDetail, NoticeSummary, ReportStats
from notice_push.reporting.resources import visible_notice_resources


@dataclass(frozen=True)
class ReportEntry:
    source_id: str
    source_name: str
    detail: NoticeDetail
    summary: NoticeSummary


def render_report(
    report_date: date,
    entries: list[ReportEntry],
    failures: list[FailedNotice],
    stats: ReportStats,
) -> str:
    lines: list[str] = []
    lines.extend(
        [
            "## 运行概览",
            "",
            f"- 报告日期: {report_date.isoformat()}",
            f"- 新增通知: {stats.new_count}",
            f"- 正文更新通知: {stats.updated_count}",
            f"- 重试通知: {stats.retried_count}",
            f"- 成功摘要: {stats.summarized_count}",
            f"- 需要人工复核: {stats.manual_review_count}",
            "",
        ]
    )
    source_stats = _source_stats(entries, failures)
    if source_stats:
        lines.append("- 按来源统计:")
        for source_name in sorted(source_stats):
            stats = source_stats[source_name]
            lines.append(
                f"  - {source_name}: 处理 {stats['total']}，成功 {stats['summarized']}，失败 {stats['failed']}"
            )
        lines.append("")

    sorted_entries = sorted(entries, key=lambda entry: entry.source_name)
    for source_name, group in groupby(sorted_entries, key=lambda entry: entry.source_name):
        lines.extend([f"## {source_name}", ""])
        for entry in group:
            lines.append(entry.summary.markdown.rstrip())
            lines.append(f"- **原文链接**: [{entry.detail.title}]({entry.detail.url})")
            resources = visible_notice_resources(entry.detail)
            if resources:
                resource_links = "；".join(f"[{name}]({url})" for name, url in resources)
                lines.append(f"- **附件**: {resource_links}")
            lines.append("")

    if failures:
        lines.extend(["## 需要人工复核", ""])
        for failure in failures:
            published_at = failure.published_at.isoformat(sep=" ") if failure.published_at else "未提及"
            source_name = failure.source_name or failure.source_id
            lines.extend(
                [
                    f"### {failure.title}",
                    f"- **来源**: {source_name}",
                    f"- **发布时间**: {published_at}",
                    f"- **原文链接**: [{failure.title}]({failure.url})",
                    f"- **失败原因**: {failure.reason}",
                    "",
                ]
            )

    return "\n".join(lines).rstrip() + "\n"


def _source_stats(entries: list[ReportEntry], failures: list[FailedNotice]) -> dict[str, dict[str, int]]:
    stats: dict[str, dict[str, int]] = defaultdict(lambda: {"total": 0, "summarized": 0, "failed": 0})
    for entry in entries:
        stats[entry.source_name]["total"] += 1
        stats[entry.source_name]["summarized"] += 1
    for failure in failures:
        source_name = failure.source_name or failure.source_id
        stats[source_name]["total"] += 1
        stats[source_name]["failed"] += 1
    return dict(stats)


def write_report(output_dir: Path, report_date: date, markdown: str) -> Path:
    output_dir.mkdir(parents=True, exist_ok=True)
    path = output_dir / f"{report_date.isoformat()}.md"
    path.write_text(markdown, encoding="utf-8")
    return path
