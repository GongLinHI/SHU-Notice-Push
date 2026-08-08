from __future__ import annotations

from notice_push.observability.monitor_snapshot import MonitorSnapshotContext, build_monitor_snapshot
from notice_push.observability.workflow_monitor import (
    MonitorFailureType,
    MonitorStatus,
    WORKFLOW_MONITOR_SCHEMA_VERSION,
    WorkflowMonitorDecision,
)


def _decision() -> WorkflowMonitorDecision:
    return WorkflowMonitorDecision(
        schema_version=WORKFLOW_MONITOR_SCHEMA_VERSION,
        status=MonitorStatus.ALERT,
        failure_type=MonitorFailureType.RUNNER_UNAVAILABLE,
        alert_required=True,
        snapshot_required=True,
        report_date="2026-08-07",
        source_workflow_name="Daily Report",
        source_run_id=123,
        source_run_attempt=1,
        source_run_key="123-attempt-1",
        source_event="schedule",
        source_conclusion="failure",
        source_url="https://github.com/example/repo/actions/runs/123",
        head_sha="abc",
        summary="Runner was unavailable",
        blockers=("runner_unavailable",),
        pipeline_exit_code=None,
        publication_status=None,
        counts=None,
        evidence_available=False,
    )


def test_monitor_snapshot_builds_metadata_only_evidence_without_pipeline_artifact(tmp_path):
    snapshot = build_monitor_snapshot(
        MonitorSnapshotContext(snapshot_root=tmp_path, decision=_decision())
    )

    assert snapshot.name == "run-123-attempt-1"
    assert (snapshot / "monitor_decision.json").is_file()
    metadata = (snapshot / "monitor_metadata.md").read_text(encoding="utf-8")
    assert "GitHub 托管 Runner 分配失败" in metadata
    assert "Pipeline 退出码: 不可用" in metadata


def test_monitor_snapshot_merges_available_business_evidence(tmp_path):
    evidence = tmp_path / "artifacts" / "failure-snapshots" / "2026-08-07" / "run-123"
    evidence.mkdir(parents=True)
    (evidence / "publication.json").write_text("{}", encoding="utf-8")
    (evidence / "notice_pipeline.log").write_text("failed", encoding="utf-8")

    snapshot = build_monitor_snapshot(
        MonitorSnapshotContext(
            snapshot_root=tmp_path / "output",
            decision=_decision(),
            evidence_root=tmp_path / "artifacts",
        )
    )

    assert (snapshot / "notice_pipeline.log").read_text(encoding="utf-8") == "failed"
    assert (snapshot / "monitor_decision.json").is_file()
