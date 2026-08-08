from __future__ import annotations

from datetime import datetime, timezone

from notice_push.observability.heartbeat import evaluate_daily_heartbeat
from notice_push.observability.publication import PublicationDecision, PublicationStatus
from notice_push.observability.publication_manifest import PublicationCounts, PublicationManifest
from notice_push.observability.workflow_monitor import (
    MonitorFailureType,
    MonitorStatus,
    classify_workflow_run,
)
from scripts.workflow.render_monitor_alert import render_monitor_alert


def _event(*, conclusion: str = "failure") -> dict[str, object]:
    return {
        "workflow_run": {
            "id": 31125849540,
            "run_attempt": 1,
            "name": "Daily Report",
            "event": "schedule",
            "head_branch": "master",
            "head_sha": "abc",
            "conclusion": conclusion,
            "created_at": "2026-08-06T18:23:47Z",
            "html_url": "https://github.com/example/repo/actions/runs/31125849540",
        },
        "repository": {"default_branch": "master"},
    }


def _publication(status: PublicationStatus) -> PublicationManifest:
    decision = PublicationDecision(
        status=status,
        blockers=("source_error_count=1",) if status is PublicationStatus.BLOCKED else (),
        may_send_report=status is PublicationStatus.PUBLISHED,
        may_update_master=status is not PublicationStatus.BLOCKED,
        requires_failure_snapshot=status is PublicationStatus.BLOCKED,
    )
    return PublicationManifest.from_decision(
        report_date="2026-08-07",
        run_id="31125849540-attempt-1",
        workflow_url="https://github.com/example/repo/actions/runs/31125849540",
        trigger="schedule",
        git_sha="abc",
        pipeline_exit_code=2 if status is PublicationStatus.BLOCKED else 0,
        decision=decision,
        counts=PublicationCounts(source_error_count=1 if status is PublicationStatus.BLOCKED else 0),
        report_path="resources/results/2026-08-07.md" if status is PublicationStatus.PUBLISHED else "",
        report_exists=status is PublicationStatus.PUBLISHED,
        run_summary_path="resources/results/json/2026-08-07.json",
    )


def test_classifies_unallocated_hosted_runner_without_fabricating_business_counts():
    context = {
        "jobs": [
            {
                "id": 92696270848,
                "conclusion": "cancelled",
                "runner_id": 0,
                "runner_name": "",
                "steps": [],
            }
        ],
        "annotations": [
            {"message": "The job was not acquired by Runner of type hosted even after multiple attempts"}
        ],
    }

    decision = classify_workflow_run(_event(), context, None)

    assert decision.status is MonitorStatus.ALERT
    assert decision.failure_type is MonitorFailureType.RUNNER_UNAVAILABLE
    assert decision.pipeline_exit_code is None
    assert decision.counts is None
    assert decision.evidence_available is False
    assert "托管 Runner" in decision.summary


def test_classifies_blocked_publication_as_business_failure_with_real_counts():
    context = {
        "jobs": [{"conclusion": "failure", "runner_id": 42, "steps": [{"name": "Fail blocked publication", "conclusion": "failure"}]}],
        "annotations": [],
    }

    decision = classify_workflow_run(
        _event(),
        context,
        _publication(PublicationStatus.BLOCKED),
    )

    assert decision.failure_type is MonitorFailureType.BUSINESS_BLOCKED
    assert decision.counts is not None
    assert decision.counts.source_error_count == 1
    assert decision.blockers == ("source_error_count=1",)


def test_classifies_daily_email_failure_after_successful_publication():
    context = {
        "jobs": [
            {
                "conclusion": "failure",
                "runner_id": 42,
                "steps": [{"name": "Send daily report email", "conclusion": "failure"}],
            }
        ],
        "annotations": [],
    }

    decision = classify_workflow_run(
        _event(),
        context,
        _publication(PublicationStatus.PUBLISHED),
    )

    assert decision.failure_type is MonitorFailureType.DAILY_EMAIL_FAILED
    assert decision.publication_status is PublicationStatus.PUBLISHED


def test_classifies_timeout_before_generic_infrastructure_failure():
    context = {
        "jobs": [{"conclusion": "timed_out", "runner_id": 42, "steps": []}],
        "annotations": [],
    }

    decision = classify_workflow_run(_event(conclusion="timed_out"), context, None)

    assert decision.failure_type is MonitorFailureType.RUN_TIMED_OUT


def test_successful_run_requires_no_monitor_job_actions():
    decision = classify_workflow_run(_event(conclusion="success"), {"jobs": []}, None)

    assert decision.status is MonitorStatus.HEALTHY
    assert decision.alert_required is False
    assert decision.snapshot_required is False


def test_monitor_alert_does_not_fabricate_unavailable_pipeline_values():
    context = {
        "jobs": [{"conclusion": "cancelled", "runner_id": 0, "steps": []}],
        "annotations": [{"message": "not acquired by Runner"}],
    }
    decision = classify_workflow_run(_event(), context, None)

    alert = render_monitor_alert(decision, snapshot_push_status="artifact_failed")

    assert "Pipeline 退出码: 不可用" in alert
    assert "source_error_count" not in alert
    assert "Artifact 下载现场" in alert


def test_heartbeat_alerts_when_scheduled_run_is_missing():
    decision = evaluate_daily_heartbeat(
        {"workflow_runs": []},
        now=datetime(2026, 8, 7, 22, 0, tzinfo=timezone.utc),
        lookback_hours=8,
    )

    assert decision.failure_type is MonitorFailureType.MISSED_SCHEDULE
    assert decision.source_run_id is None
    assert decision.pipeline_exit_code is None


def test_heartbeat_accepts_recent_completed_run_even_when_failure_monitor_owns_result():
    decision = evaluate_daily_heartbeat(
        {
            "workflow_runs": [
                {
                    "id": 123,
                    "run_attempt": 1,
                    "name": "Daily Report",
                    "event": "schedule",
                    "status": "completed",
                    "conclusion": "failure",
                    "created_at": "2026-08-07T18:00:00Z",
                    "html_url": "https://github.com/example/repo/actions/runs/123",
                    "head_sha": "abc",
                }
            ]
        },
        monitor_runs_payload={
            "workflow_runs": [
                {
                    "display_title": "监控日报 run-123-attempt-1",
                    "status": "completed",
                    "conclusion": "success",
                }
            ]
        },
        now=datetime(2026, 8, 7, 22, 0, tzinfo=timezone.utc),
        lookback_hours=8,
    )

    assert decision.status is MonitorStatus.HEALTHY
    assert decision.alert_required is False


def test_heartbeat_alerts_when_failed_run_was_not_handled_by_monitor():
    decision = evaluate_daily_heartbeat(
        {
            "workflow_runs": [
                {
                    "id": 123,
                    "run_attempt": 1,
                    "name": "Daily Report",
                    "event": "schedule",
                    "status": "completed",
                    "conclusion": "failure",
                    "created_at": "2026-08-07T18:00:00Z",
                    "html_url": "https://github.com/example/repo/actions/runs/123",
                    "head_sha": "abc",
                }
            ]
        },
        monitor_runs_payload={"workflow_runs": []},
        now=datetime(2026, 8, 7, 22, 0, tzinfo=timezone.utc),
        lookback_hours=8,
    )

    assert decision.status is MonitorStatus.ALERT
    assert decision.failure_type is MonitorFailureType.WORKFLOW_INFRASTRUCTURE_FAILED


def test_heartbeat_alerts_for_stalled_recent_run():
    decision = evaluate_daily_heartbeat(
        {
            "workflow_runs": [
                {
                    "id": 123,
                    "run_attempt": 1,
                    "name": "Daily Report",
                    "event": "schedule",
                    "status": "in_progress",
                    "conclusion": None,
                    "created_at": "2026-08-07T18:00:00Z",
                    "html_url": "https://github.com/example/repo/actions/runs/123",
                    "head_sha": "abc",
                }
            ]
        },
        now=datetime(2026, 8, 7, 22, 0, tzinfo=timezone.utc),
        stalled_after_minutes=180,
    )

    assert decision.failure_type is MonitorFailureType.STALLED_RUN
