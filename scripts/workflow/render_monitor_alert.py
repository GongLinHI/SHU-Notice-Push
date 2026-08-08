from __future__ import annotations

import argparse
import html
from pathlib import Path

from notice_push.observability.workflow_monitor import WorkflowMonitorDecision


def main() -> int:
    parser = argparse.ArgumentParser(description="Render an HTML alert for a monitored workflow failure.")
    parser.add_argument("--decision-json", type=Path, required=True)
    parser.add_argument("--snapshot-push-status", required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()

    decision = WorkflowMonitorDecision.from_json_text(
        args.decision_json.read_text(encoding="utf-8")
    )
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(
        render_monitor_alert(decision, snapshot_push_status=args.snapshot_push_status),
        encoding="utf-8",
    )
    return 0


def render_monitor_alert(
    decision: WorkflowMonitorDecision,
    *,
    snapshot_push_status: str,
) -> str:
    items: list[tuple[str, object]] = [
        ("异常类型", decision.failure_label),
        ("报告日期", decision.report_date),
        ("源 Workflow", decision.source_workflow_name),
        ("源 Run ID", decision.source_run_id if decision.source_run_id is not None else "不可用"),
        ("源 Run Attempt", decision.source_run_attempt if decision.source_run_attempt is not None else "不可用"),
        ("源 Run", decision.source_url or "不可用"),
        ("触发方式", decision.source_event),
        ("运行结论", decision.source_conclusion or "不可用"),
        ("Git SHA", decision.head_sha or "不可用"),
        ("Pipeline 退出码", decision.pipeline_exit_code if decision.pipeline_exit_code is not None else "不可用"),
        ("阻断原因", ", ".join(decision.blockers) or "未知"),
        ("快照推送状态", snapshot_push_status),
    ]
    if decision.counts is not None:
        for key in (
            "source_error_count",
            "audit_error_count",
            "audit_warning_count",
            "refresh_seen_error_count",
            "failed_count",
            "manual_review_count",
        ):
            items.append((key, getattr(decision.counts, key)))
    details = "".join(
        f"<li>{html.escape(str(key))}: {html.escape(str(value))}</li>"
        for key, value in items
    )
    push_warning = (
        ""
        if snapshot_push_status in {"succeeded", "not_required", "artifact_success"}
        else "<p>异常快照分支推送失败，请从本次监控运行的 Artifact 下载现场。</p>"
    )
    return (
        "<!doctype html><html><body style=\"font-family:Arial,sans-serif;line-height:1.6;color:#1f2937;\">"
        "<h2>上海大学通知推送运行异常</h2>"
        f"<p>{html.escape(decision.summary)}</p>"
        f"<ul>{details}</ul>{push_warning}"
        "</body></html>"
    )


if __name__ == "__main__":
    raise SystemExit(main())
