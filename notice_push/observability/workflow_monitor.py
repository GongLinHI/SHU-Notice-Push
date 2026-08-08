from __future__ import annotations

from datetime import datetime, timedelta, timezone
from enum import StrEnum
from typing import Literal, Mapping

from pydantic import BaseModel, ConfigDict, StrictBool, StrictInt, StrictStr, ValidationError

from notice_push.observability.publication import PublicationStatus
from notice_push.observability.publication_manifest import PublicationCounts, PublicationManifest


WORKFLOW_MONITOR_SCHEMA_VERSION = 1
BEIJING_TIMEZONE = timezone(timedelta(hours=8))
DAILY_REPORT_WORKFLOW_NAME = "Daily Report"


class MonitorStatus(StrEnum):
    HEALTHY = "healthy"
    ALERT = "alert"
    IGNORED = "ignored"


class MonitorFailureType(StrEnum):
    BUSINESS_BLOCKED = "business_blocked"
    DAILY_EMAIL_FAILED = "daily_email_failed"
    RUNNER_UNAVAILABLE = "runner_unavailable"
    RUN_TIMED_OUT = "run_timed_out"
    RUN_CANCELLED = "run_cancelled"
    WORKFLOW_INFRASTRUCTURE_FAILED = "workflow_infrastructure_failed"
    MISSED_SCHEDULE = "missed_schedule"
    STALLED_RUN = "stalled_run"
    UNKNOWN_FAILURE = "unknown_failure"


_FAILURE_TYPE_LABELS = {
    MonitorFailureType.BUSINESS_BLOCKED: "业务运行被质量门禁阻断",
    MonitorFailureType.DAILY_EMAIL_FAILED: "日报邮件投递失败",
    MonitorFailureType.RUNNER_UNAVAILABLE: "GitHub 托管 Runner 分配失败",
    MonitorFailureType.RUN_TIMED_OUT: "GitHub Actions 运行超时",
    MonitorFailureType.RUN_CANCELLED: "GitHub Actions 运行被取消",
    MonitorFailureType.WORKFLOW_INFRASTRUCTURE_FAILED: "GitHub Actions 基础设施或步骤失败",
    MonitorFailureType.MISSED_SCHEDULE: "定时日报未按期启动",
    MonitorFailureType.STALLED_RUN: "定时日报长时间未完成",
    MonitorFailureType.UNKNOWN_FAILURE: "未分类的运行异常",
}


class WorkflowMonitorDecision(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    schema_version: Literal[WORKFLOW_MONITOR_SCHEMA_VERSION]
    status: MonitorStatus
    failure_type: MonitorFailureType | None = None
    alert_required: StrictBool
    snapshot_required: StrictBool
    report_date: StrictStr
    source_workflow_name: StrictStr
    source_run_id: StrictInt | None = None
    source_run_attempt: StrictInt | None = None
    source_run_key: StrictStr
    source_event: StrictStr
    source_conclusion: StrictStr
    source_url: StrictStr
    head_sha: StrictStr
    summary: StrictStr
    blockers: tuple[StrictStr, ...]
    pipeline_exit_code: StrictInt | None = None
    publication_status: PublicationStatus | None = None
    counts: PublicationCounts | None = None
    evidence_available: StrictBool

    @property
    def failure_label(self) -> str:
        if self.failure_type is None:
            return "无异常"
        return failure_type_label(self.failure_type)

    @property
    def alert_subject(self) -> str:
        return f"上海大学通知推送运行异常 - {self.report_date} - {self.failure_label}"

    def to_json_text(self) -> str:
        return self.model_dump_json(indent=2, exclude_none=True) + "\n"

    @classmethod
    def from_json_text(cls, text: str) -> "WorkflowMonitorDecision":
        try:
            return cls.model_validate_json(text)
        except ValidationError as exc:
            raise ValueError(f"invalid workflow monitor decision: {exc}") from exc

    def workflow_outputs(self) -> dict[str, str]:
        return {
            "monitor_status": self.status.value,
            "alert_required": str(self.alert_required).lower(),
            "snapshot_required": str(self.snapshot_required).lower(),
            "failure_type": self.failure_type.value if self.failure_type else "",
            "failure_label": self.failure_label,
            "alert_subject": self.alert_subject,
            "report_date": self.report_date,
            "source_run_key": self.source_run_key,
            "source_run_id": str(self.source_run_id) if self.source_run_id is not None else "",
        }


def classify_workflow_run(
    event_payload: Mapping[str, object],
    context_payload: Mapping[str, object] | None,
    publication: PublicationManifest | None,
) -> WorkflowMonitorDecision:
    run = _mapping(event_payload.get("workflow_run"))
    repository = _mapping(event_payload.get("repository"))
    workflow_name = _text(run.get("name"))
    source_event = _text(run.get("event"))
    head_branch = _text(run.get("head_branch"))
    default_branch = _text(repository.get("default_branch"))
    run_id = _integer(run.get("id"))
    run_attempt = _integer(run.get("run_attempt")) or 1
    run_key = f"{run_id}-attempt-{run_attempt}" if run_id is not None else "unavailable"
    report_date = publication.report_date if publication else _beijing_date(_text(run.get("created_at")))
    common = {
        "schema_version": WORKFLOW_MONITOR_SCHEMA_VERSION,
        "report_date": report_date,
        "source_workflow_name": workflow_name,
        "source_run_id": run_id,
        "source_run_attempt": run_attempt,
        "source_run_key": run_key,
        "source_event": source_event,
        "source_conclusion": _text(run.get("conclusion")),
        "source_url": _text(run.get("html_url")),
        "head_sha": _text(run.get("head_sha")),
        "pipeline_exit_code": publication.pipeline_exit_code if publication else None,
        "publication_status": publication.status if publication else None,
        "counts": publication.counts if publication else None,
        "evidence_available": publication is not None,
    }

    if (
        workflow_name != DAILY_REPORT_WORKFLOW_NAME
        or source_event not in {"schedule", "workflow_dispatch"}
        or (default_branch and head_branch != default_branch)
    ):
        return WorkflowMonitorDecision(
            **common,
            status=MonitorStatus.IGNORED,
            alert_required=False,
            snapshot_required=False,
            summary="该运行不属于受监控的默认分支日报。",
            blockers=(),
        )

    conclusion = _text(run.get("conclusion"))
    if conclusion == "success":
        return WorkflowMonitorDecision(
            **common,
            status=MonitorStatus.HEALTHY,
            alert_required=False,
            snapshot_required=False,
            summary="日报工作流已成功完成。",
            blockers=(),
        )

    jobs = _jobs(context_payload)
    annotations = _annotation_messages(context_payload)
    failure_type = _classify_failure(conclusion, jobs, annotations, publication)
    blockers = publication.blockers if publication and publication.blockers else (failure_type.value,)
    return WorkflowMonitorDecision(
        **common,
        status=MonitorStatus.ALERT,
        failure_type=failure_type,
        alert_required=True,
        snapshot_required=True,
        summary=_failure_summary(failure_type, annotations),
        blockers=blockers,
    )


def failure_type_label(failure_type: MonitorFailureType) -> str:
    return _FAILURE_TYPE_LABELS[failure_type]


def _classify_failure(
    conclusion: str,
    jobs: tuple[Mapping[str, object], ...],
    annotations: tuple[str, ...],
    publication: PublicationManifest | None,
) -> MonitorFailureType:
    lowered_annotations = "\n".join(annotations).lower()
    no_runner_acquired = "not acquired by runner" in lowered_annotations or (
        bool(jobs)
        and all((_integer(job.get("runner_id")) or 0) == 0 for job in jobs)
        and all(not _job_steps(job) for job in jobs)
        and all(_text(job.get("conclusion")) == "cancelled" for job in jobs)
    )
    if no_runner_acquired:
        return MonitorFailureType.RUNNER_UNAVAILABLE
    if publication and publication.status is PublicationStatus.BLOCKED:
        return MonitorFailureType.BUSINESS_BLOCKED
    if publication and _step_failed(jobs, "Send daily report email"):
        return MonitorFailureType.DAILY_EMAIL_FAILED
    if conclusion == "timed_out" or any(
        _text(job.get("conclusion")) == "timed_out" for job in jobs
    ):
        return MonitorFailureType.RUN_TIMED_OUT
    if conclusion == "cancelled":
        return MonitorFailureType.RUN_CANCELLED
    if publication is None and conclusion in {"failure", "startup_failure", "action_required", "stale"}:
        return MonitorFailureType.WORKFLOW_INFRASTRUCTURE_FAILED
    if conclusion == "failure":
        return MonitorFailureType.WORKFLOW_INFRASTRUCTURE_FAILED
    return MonitorFailureType.UNKNOWN_FAILURE


def _failure_summary(failure_type: MonitorFailureType, annotations: tuple[str, ...]) -> str:
    label = failure_type_label(failure_type)
    if failure_type is MonitorFailureType.RUNNER_UNAVAILABLE and annotations:
        return f"{label}，GitHub 多次尝试后仍未能为 job 分配托管 Runner。"
    return f"{label}，GitHub 未提供额外注解。"


def _step_failed(jobs: tuple[Mapping[str, object], ...], name: str) -> bool:
    return any(
        _text(step.get("name")) == name and _text(step.get("conclusion")) == "failure"
        for job in jobs
        for step in _job_steps(job)
    )


def _jobs(context: Mapping[str, object] | None) -> tuple[Mapping[str, object], ...]:
    payload = _mapping(context)
    raw_jobs = payload.get("jobs", ())
    if not isinstance(raw_jobs, list):
        return ()
    return tuple(item for value in raw_jobs if (item := _mapping(value)))


def _job_steps(job: Mapping[str, object]) -> tuple[Mapping[str, object], ...]:
    raw_steps = job.get("steps", ())
    if not isinstance(raw_steps, list):
        return ()
    return tuple(item for value in raw_steps if (item := _mapping(value)))


def _annotation_messages(context: Mapping[str, object] | None) -> tuple[str, ...]:
    payload = _mapping(context)
    raw_annotations = payload.get("annotations", ())
    if not isinstance(raw_annotations, list):
        return ()
    messages: list[str] = []
    for value in raw_annotations:
        annotation = _mapping(value)
        message = _text(annotation.get("message"))
        if message:
            messages.append(message)
    return tuple(messages)


def _beijing_date(created_at: str) -> str:
    try:
        parsed = datetime.fromisoformat(created_at.replace("Z", "+00:00"))
    except ValueError:
        return datetime.now(BEIJING_TIMEZONE).date().isoformat()
    return parsed.astimezone(BEIJING_TIMEZONE).date().isoformat()


def _mapping(value: object) -> Mapping[str, object]:
    return value if isinstance(value, Mapping) else {}


def _text(value: object) -> str:
    return value if isinstance(value, str) else ""


def _integer(value: object) -> int | None:
    return value if isinstance(value, int) and not isinstance(value, bool) else None
