from __future__ import annotations

import argparse
import html
from pathlib import Path

from notice_push.observability.publication_manifest import PublicationManifest
from notice_push.observability.run_summary_contract import (
    FailureRunSummaryContract,
    RunSummaryContract,
)


def main() -> int:
    parser = argparse.ArgumentParser(description="Render a safe HTML alert from a notice failure snapshot.")
    parser.add_argument("--snapshot-directory", default="")
    parser.add_argument("--publication-json", type=Path, required=True)
    parser.add_argument("--run-summary-path", type=Path, default=None)
    parser.add_argument("--snapshot-push-status", required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()

    snapshot = _existing_snapshot_directory(args.snapshot_directory)
    publication_path = snapshot / "publication.json" if snapshot and (snapshot / "publication.json").exists() else args.publication_json
    summary_path = snapshot / "run_summary.json" if snapshot and (snapshot / "run_summary.json").exists() else args.run_summary_path
    publication = PublicationManifest.from_json_text(
        publication_path.read_text(encoding="utf-8")
    )
    issues = _load_summary_issues(summary_path)
    counts = publication.counts
    master_state_updated = publication.master_state_updated
    publication_message = (
        "master 正式状态已更新，但后续发布收尾失败；日报邮件未发送"
        if master_state_updated
        else "日报未发布；master 正式状态未更新"
    )
    items = [
        ("报告日期", publication.report_date),
        ("Workflow Run ID", publication.workflow_run_id),
        ("Workflow", publication.workflow_url),
        ("触发方式", publication.trigger),
        ("Git SHA", publication.git_sha),
        ("发布状态", publication_message),
        ("Pipeline 退出码", publication.pipeline_exit_code),
        ("阻断原因", ", ".join(publication.blockers) or "未知"),
        ("失败详情", publication.failure_detail or "无"),
        ("异常快照分支", publication.failure_snapshot_branch),
        ("异常快照路径", publication.failure_snapshot_path),
        ("Artifact", publication.artifact_name),
        ("快照推送状态", args.snapshot_push_status),
    ]
    for key in (
        "source_error_count",
        "audit_error_count",
        "audit_warning_count",
        "refresh_seen_error_count",
        "failed_count",
        "manual_review_count",
    ):
        items.append((key, getattr(counts, key)))
    issue_rows = []
    for issue in issues:
        issue_rows.append(
            "<li><strong>{}</strong>: {} ({})</li>".format(
                html.escape(issue.source_name or issue.source_id),
                html.escape(issue.reason),
                html.escape(issue.url),
            )
        )
    details = "".join(f"<li>{html.escape(str(key))}: {html.escape(str(value))}</li>" for key, value in items)
    push_warning = "" if args.snapshot_push_status == "succeeded" else "<p>异常快照分支推送失败，请从 Artifact 下载现场。</p>"
    body = (
        "<!doctype html><html><body style=\"font-family:Arial,sans-serif;line-height:1.6;color:#1f2937;\">"
        "<h2>上海大学通知推送运行异常</h2>"
        f"<p>{publication_message}。</p>"
        f"<ul>{details}</ul>{push_warning}"
        + (f"<h3>源站异常详情</h3><ul>{''.join(issue_rows)}</ul>" if issue_rows else "")
        + "</body></html>"
    )
    args.output.write_text(body, encoding="utf-8")
    return 0


def _load_summary_issues(summary_path: Path | None):
    if summary_path is None or not summary_path.is_file():
        return ()
    text = summary_path.read_text(encoding="utf-8")
    try:
        summary = RunSummaryContract.from_json_text(text)
    except ValueError:
        try:
            FailureRunSummaryContract.from_json_text(text)
        except ValueError:
            return ()
        return ()
    return (*summary.source_errors, *summary.audit_issues)


def _existing_snapshot_directory(raw_path: str) -> Path | None:
    if not raw_path:
        return None
    path = Path(raw_path)
    return path if path.is_dir() else None


if __name__ == "__main__":
    raise SystemExit(main())
