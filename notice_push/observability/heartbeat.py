from __future__ import annotations

from datetime import datetime, timedelta, timezone
from typing import Mapping

from notice_push.observability.workflow_monitor import (
    BEIJING_TIMEZONE,
    DAILY_REPORT_WORKFLOW_NAME,
    MonitorFailureType,
    MonitorStatus,
    WORKFLOW_MONITOR_SCHEMA_VERSION,
    WorkflowMonitorDecision,
)


def evaluate_daily_heartbeat(
    runs_payload: Mapping[str, object],
    *,
    monitor_runs_payload: Mapping[str, object] | None = None,
    now: datetime | None = None,
    lookback_hours: float = 8.0,
    stalled_after_minutes: float = 180.0,
) -> WorkflowMonitorDecision:
    current = _as_utc(now or datetime.now(timezone.utc))
    runs = _scheduled_daily_runs(runs_payload)
    cutoff = current - timedelta(hours=max(0.0, lookback_hours))
    recent = tuple(run for run in runs if (_created_at(run) or datetime.min.replace(tzinfo=timezone.utc)) >= cutoff)
    latest = max(recent, key=lambda run: _created_at(run) or datetime.min.replace(tzinfo=timezone.utc), default=None)

    if latest is None:
        report_date = current.astimezone(BEIJING_TIMEZONE).date().isoformat()
        return WorkflowMonitorDecision(
            schema_version=WORKFLOW_MONITOR_SCHEMA_VERSION,
            status=MonitorStatus.ALERT,
            failure_type=MonitorFailureType.MISSED_SCHEDULE,
            alert_required=True,
            snapshot_required=True,
            report_date=report_date,
            source_workflow_name=DAILY_REPORT_WORKFLOW_NAME,
            source_run_id=None,
            source_run_attempt=None,
            source_run_key=f"watchdog-{report_date}",
            source_event="schedule_watchdog",
            source_conclusion="missing",
            source_url="",
            head_sha="",
            summary=f"过去 {lookback_hours:g} 小时内没有发现 {DAILY_REPORT_WORKFLOW_NAME} 定时运行。",
            blockers=(MonitorFailureType.MISSED_SCHEDULE.value,),
            pipeline_exit_code=None,
            publication_status=None,
            counts=None,
            evidence_available=False,
        )

    created_at = _created_at(latest) or current
    status = _text(latest.get("status"))
    age_minutes = (current - created_at).total_seconds() / 60
    if status != "completed" and age_minutes >= stalled_after_minutes:
        return _decision_for_run(
            latest,
            status=MonitorStatus.ALERT,
            failure_type=MonitorFailureType.STALLED_RUN,
            alert_required=True,
            summary=f"Daily Report 已运行或排队 {age_minutes:.0f} 分钟，仍未完成。",
        )

    conclusion = _text(latest.get("conclusion"))
    if status == "completed" and conclusion != "success":
        monitor_state = _monitor_handling_state(latest, monitor_runs_payload)
        if monitor_state not in {"succeeded", "in_progress"}:
            return _decision_for_run(
                latest,
                status=MonitorStatus.ALERT,
                failure_type=MonitorFailureType.WORKFLOW_INFRASTRUCTURE_FAILED,
                alert_required=True,
                summary="Daily Report 已失败，且未发现成功完成的独立监控处理。",
            )

    return _decision_for_run(
        latest,
        status=MonitorStatus.HEALTHY,
        failure_type=None,
        alert_required=False,
        summary="预期时间窗口内已发现 Daily Report 运行。",
    )


def _decision_for_run(
    run: Mapping[str, object],
    *,
    status: MonitorStatus,
    failure_type: MonitorFailureType | None,
    alert_required: bool,
    summary: str,
) -> WorkflowMonitorDecision:
    created_at = _created_at(run) or datetime.now(timezone.utc)
    run_id = _integer(run.get("id"))
    attempt = _integer(run.get("run_attempt")) or 1
    report_date = created_at.astimezone(BEIJING_TIMEZONE).date().isoformat()
    return WorkflowMonitorDecision(
        schema_version=WORKFLOW_MONITOR_SCHEMA_VERSION,
        status=status,
        failure_type=failure_type,
        alert_required=alert_required,
        snapshot_required=alert_required,
        report_date=report_date,
        source_workflow_name=_text(run.get("name")) or DAILY_REPORT_WORKFLOW_NAME,
        source_run_id=run_id,
        source_run_attempt=attempt,
        source_run_key=(f"{run_id}-attempt-{attempt}" if run_id is not None else f"watchdog-{report_date}"),
        source_event=_text(run.get("event")) or "schedule",
        source_conclusion=_text(run.get("conclusion")) or _text(run.get("status")),
        source_url=_text(run.get("html_url")),
        head_sha=_text(run.get("head_sha")),
        summary=summary,
        blockers=(failure_type.value,) if failure_type else (),
        pipeline_exit_code=None,
        publication_status=None,
        counts=None,
        evidence_available=False,
    )


def _scheduled_daily_runs(payload: Mapping[str, object]) -> tuple[Mapping[str, object], ...]:
    raw_runs = payload.get("workflow_runs", ())
    if not isinstance(raw_runs, list):
        return ()
    return tuple(
        run
        for value in raw_runs
        if isinstance(value, Mapping)
        and (run := value)
        and _text(run.get("name")) == DAILY_REPORT_WORKFLOW_NAME
        and _text(run.get("event")) == "schedule"
    )


def _monitor_handling_state(
    source_run: Mapping[str, object],
    monitor_runs_payload: Mapping[str, object] | None,
) -> str:
    source_id = _integer(source_run.get("id"))
    source_attempt = _integer(source_run.get("run_attempt")) or 1
    if source_id is None:
        return "missing"
    expected_title = f"监控日报 run-{source_id}-attempt-{source_attempt}"
    payload = monitor_runs_payload if isinstance(monitor_runs_payload, Mapping) else {}
    raw_runs = payload.get("workflow_runs", ())
    if not isinstance(raw_runs, list):
        return "missing"
    for value in raw_runs:
        if not isinstance(value, Mapping) or _text(value.get("display_title")) != expected_title:
            continue
        if _text(value.get("status")) != "completed":
            return "in_progress"
        return "succeeded" if _text(value.get("conclusion")) == "success" else "failed"
    return "missing"


def _created_at(run: Mapping[str, object]) -> datetime | None:
    value = _text(run.get("created_at"))
    if not value:
        return None
    try:
        return _as_utc(datetime.fromisoformat(value.replace("Z", "+00:00")))
    except ValueError:
        return None


def _as_utc(value: datetime) -> datetime:
    if value.tzinfo is None:
        value = value.replace(tzinfo=timezone.utc)
    return value.astimezone(timezone.utc)


def _text(value: object) -> str:
    return value if isinstance(value, str) else ""


def _integer(value: object) -> int | None:
    return value if isinstance(value, int) and not isinstance(value, bool) else None
