from __future__ import annotations

import argparse
import html
import json
from pathlib import Path


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
    publication = json.loads(publication_path.read_text(encoding="utf-8"))
    summary = (
        json.loads(summary_path.read_text(encoding="utf-8"))
        if summary_path and summary_path.is_file()
        else {"source_errors": [], "audit_issues": []}
    )
    counts = publication.get("counts", {})
    master_state_updated = publication.get("master_state_updated") is True
    publication_message = (
        "master 正式状态已更新，但后续发布收尾失败；日报邮件未发送"
        if master_state_updated
        else "日报未发布；master 正式状态未更新"
    )
    items = [
        ("报告日期", publication.get("report_date", "")),
        ("Workflow Run ID", publication.get("workflow_run_id", "")),
        ("Workflow", publication.get("workflow_url", "")),
        ("触发方式", publication.get("trigger", "")),
        ("Git SHA", publication.get("git_sha", "")),
        ("发布状态", publication_message),
        ("Pipeline 退出码", publication.get("pipeline_exit_code", 2)),
        ("阻断原因", ", ".join(publication.get("publication_blockers", [])) or "未知"),
        ("失败详情", publication.get("failure_detail", "") or "无"),
        ("异常快照分支", publication.get("failure_snapshot_branch", "")),
        ("异常快照路径", publication.get("failure_snapshot_path", "")),
        ("Artifact", publication.get("artifact_name", "")),
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
        items.append((key, counts.get(key, 0)))
    issue_rows = []
    for issue in [*summary.get("source_errors", []), *summary.get("audit_issues", [])]:
        issue_rows.append(
            "<li><strong>{}</strong>: {} ({})</li>".format(
                html.escape(str(issue.get("source_name", issue.get("source_id", "")))),
                html.escape(str(issue.get("reason", ""))),
                html.escape(str(issue.get("url", ""))),
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


def _existing_snapshot_directory(raw_path: str) -> Path | None:
    if not raw_path:
        return None
    path = Path(raw_path)
    return path if path.is_dir() else None


if __name__ == "__main__":
    raise SystemExit(main())
