from __future__ import annotations

import shutil
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path

from notice_push.observability.workflow_monitor import BEIJING_TIMEZONE, WorkflowMonitorDecision


@dataclass(frozen=True)
class MonitorSnapshotContext:
    snapshot_root: Path
    decision: WorkflowMonitorDecision
    evidence_root: Path | None = None


def build_monitor_snapshot(context: MonitorSnapshotContext) -> Path:
    destination = (
        Path(context.snapshot_root)
        / "failure-snapshots"
        / context.decision.report_date
        / f"run-{context.decision.source_run_key}"
    )
    destination.mkdir(parents=True, exist_ok=True)
    evidence = _find_failure_evidence(context.evidence_root)
    if evidence is not None:
        shutil.copytree(evidence, destination, dirs_exist_ok=True)
    (destination / "monitor_decision.json").write_text(
        context.decision.to_json_text(),
        encoding="utf-8",
    )
    (destination / "monitor_metadata.md").write_text(
        _metadata(context.decision),
        encoding="utf-8",
    )
    return destination


def _find_failure_evidence(root: Path | None) -> Path | None:
    if root is None or not Path(root).is_dir():
        return None
    candidates = sorted(Path(root).rglob("publication.json"))
    for publication in candidates:
        parent = publication.parent
        if (parent / "metadata.md").is_file() or (parent / "notice_pipeline.log").is_file():
            return parent
    return None


def _metadata(decision: WorkflowMonitorDecision) -> str:
    created_at = datetime.now(BEIJING_TIMEZONE).isoformat(timespec="seconds")
    lines = [
        "# GitHub Actions 监控快照",
        "",
        f"- 生成时间（北京时间）: {created_at}",
        f"- 异常类型: {decision.failure_type.value if decision.failure_type else '无'}",
        f"- 异常说明: {decision.failure_label}",
        f"- 报告日期: {decision.report_date}",
        f"- 源 Workflow: {decision.source_workflow_name}",
        f"- 源 Run ID: {decision.source_run_id if decision.source_run_id is not None else '不可用'}",
        f"- 源 Run Attempt: {decision.source_run_attempt if decision.source_run_attempt is not None else '不可用'}",
        f"- 源 Run URL: {decision.source_url or '不可用'}",
        f"- Git SHA: {decision.head_sha or '不可用'}",
        f"- 运行结论: {decision.source_conclusion or '不可用'}",
        f"- Pipeline 退出码: {decision.pipeline_exit_code if decision.pipeline_exit_code is not None else '不可用'}",
        f"- 业务证据: {'可用' if decision.evidence_available else '不可用'}",
        f"- 摘要: {decision.summary}",
        f"- 阻断原因: {', '.join(decision.blockers) or '无'}",
    ]
    if decision.counts is not None:
        lines.extend(("", "## 运行计数", ""))
        for key, value in sorted(decision.counts.to_json().items()):
            lines.append(f"- {key}: {value}")
    return "\n".join(lines).rstrip() + "\n"
