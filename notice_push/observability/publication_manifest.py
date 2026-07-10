from __future__ import annotations

from dataclasses import dataclass
from typing import Mapping

from notice_push.observability.publication import PublicationDecision, PublicationStatus


COUNT_FIELD_NAMES = (
    "new_count",
    "updated_count",
    "retried_count",
    "summarized_count",
    "failed_count",
    "manual_review_count",
    "source_error_count",
    "audit_error_count",
    "audit_warning_count",
    "refresh_seen_error_count",
)
FAILURE_SNAPSHOT_BRANCH = "bot/failure-snapshots"
MANIFEST_FIELD_NAMES = frozenset(
    {
        "schema_version",
        "report_date",
        "workflow_run_id",
        "workflow_url",
        "trigger",
        "git_sha",
        "pipeline_exit_code",
        "publication_status",
        "publication_blockers",
        "counts",
        "report_path",
        "report_exists",
        "run_summary_path",
        "master_state_updated",
        "report_email_sent",
        "alert_email_requested",
        "failure_snapshot_push_status",
        "failure_snapshot_branch",
        "failure_snapshot_path",
        "artifact_name",
        "state_snapshot_available",
        "failure_detail",
    }
)


@dataclass(frozen=True)
class PublicationCounts:
    new_count: int = 0
    updated_count: int = 0
    retried_count: int = 0
    summarized_count: int = 0
    failed_count: int = 0
    manual_review_count: int = 0
    source_error_count: int = 0
    audit_error_count: int = 0
    audit_warning_count: int = 0
    refresh_seen_error_count: int = 0

    def to_json(self) -> dict[str, int]:
        return {name: getattr(self, name) for name in COUNT_FIELD_NAMES}

    @classmethod
    def from_json(cls, payload: object) -> "PublicationCounts":
        if not isinstance(payload, Mapping):
            raise ValueError("publication manifest counts must be a mapping")
        unexpected_fields = sorted(str(name) for name in set(payload) - set(COUNT_FIELD_NAMES))
        if unexpected_fields:
            raise ValueError(
                f"publication manifest counts contains unexpected fields: {', '.join(unexpected_fields)}"
            )
        values: dict[str, int] = {}
        for name in COUNT_FIELD_NAMES:
            value = payload.get(name)
            if isinstance(value, bool) or not isinstance(value, int):
                raise ValueError(f"publication manifest counts.{name} must be an integer")
            values[name] = value
        return cls(**values)


@dataclass(frozen=True)
class PublicationManifest:
    report_date: str
    workflow_run_id: str
    workflow_url: str
    trigger: str
    git_sha: str
    pipeline_exit_code: int
    status: PublicationStatus
    blockers: tuple[str, ...]
    counts: PublicationCounts
    report_path: str
    report_exists: bool
    run_summary_path: str
    master_state_updated: bool
    report_email_sent: bool
    alert_email_requested: bool
    failure_snapshot_push_status: str
    failure_snapshot_branch: str
    failure_snapshot_path: str
    artifact_name: str
    state_snapshot_available: bool | None = None
    failure_detail: str = ""

    @classmethod
    def from_decision(
        cls,
        *,
        report_date: str,
        run_id: str,
        workflow_url: str,
        trigger: str,
        git_sha: str,
        pipeline_exit_code: int,
        decision: PublicationDecision,
        counts: PublicationCounts,
        report_path: str,
        report_exists: bool,
        run_summary_path: str,
        failure_snapshot_branch: str = FAILURE_SNAPSHOT_BRANCH,
    ) -> "PublicationManifest":
        needs_snapshot = decision.requires_failure_snapshot
        snapshot_path = f"failure-snapshots/{report_date}/run-{run_id}" if needs_snapshot else ""
        artifact_name = f"notice-failure-snapshot-{report_date}-{run_id}" if needs_snapshot else ""
        return cls(
            report_date=report_date,
            workflow_run_id=run_id,
            workflow_url=workflow_url,
            trigger=trigger,
            git_sha=git_sha,
            pipeline_exit_code=pipeline_exit_code,
            status=decision.status,
            blockers=decision.blockers,
            counts=counts,
            report_path=report_path,
            report_exists=report_exists,
            run_summary_path=run_summary_path,
            master_state_updated=False,
            report_email_sent=False,
            alert_email_requested=needs_snapshot,
            failure_snapshot_push_status="pending" if needs_snapshot else "not_required",
            failure_snapshot_branch=failure_snapshot_branch,
            failure_snapshot_path=snapshot_path,
            artifact_name=artifact_name,
        )

    @classmethod
    def blocked_fallback(
        cls,
        *,
        report_date: str,
        run_id: str,
        workflow_url: str,
        trigger: str,
        git_sha: str,
        pipeline_exit_code: int,
        blocker: str,
        counts: PublicationCounts | None = None,
        report_path: str = "",
        report_exists: bool = False,
        run_summary_path: str = "",
        failure_snapshot_branch: str = FAILURE_SNAPSHOT_BRANCH,
    ) -> "PublicationManifest":
        return cls(
            report_date=report_date,
            workflow_run_id=run_id,
            workflow_url=workflow_url,
            trigger=trigger,
            git_sha=git_sha,
            pipeline_exit_code=2,
            status=PublicationStatus.BLOCKED,
            blockers=(blocker,),
            counts=counts or PublicationCounts(),
            report_path=report_path,
            report_exists=report_exists,
            run_summary_path=run_summary_path,
            master_state_updated=False,
            report_email_sent=False,
            alert_email_requested=True,
            failure_snapshot_push_status="pending",
            failure_snapshot_branch=failure_snapshot_branch,
            failure_snapshot_path=f"failure-snapshots/{report_date}/run-{run_id}",
            artifact_name=f"notice-failure-snapshot-{report_date}-{run_id}",
        )

    def to_json(self) -> dict[str, object]:
        payload: dict[str, object] = {
            "schema_version": 1,
            "report_date": self.report_date,
            "workflow_run_id": self.workflow_run_id,
            "workflow_url": self.workflow_url,
            "trigger": self.trigger,
            "git_sha": self.git_sha,
            "pipeline_exit_code": self.pipeline_exit_code,
            "publication_status": self.status.value,
            "publication_blockers": list(self.blockers),
            "counts": self.counts.to_json(),
            "report_path": self.report_path,
            "report_exists": self.report_exists,
            "run_summary_path": self.run_summary_path,
            "master_state_updated": self.master_state_updated,
            "report_email_sent": self.report_email_sent,
            "alert_email_requested": self.alert_email_requested,
            "failure_snapshot_push_status": self.failure_snapshot_push_status,
            "failure_snapshot_branch": self.failure_snapshot_branch,
            "failure_snapshot_path": self.failure_snapshot_path,
            "artifact_name": self.artifact_name,
            "failure_detail": self.failure_detail,
        }
        if self.state_snapshot_available is not None:
            payload["state_snapshot_available"] = self.state_snapshot_available
        return payload

    @classmethod
    def from_json(cls, payload: Mapping[str, object]) -> "PublicationManifest":
        if not isinstance(payload, Mapping):
            raise ValueError("publication manifest must be a mapping")
        unexpected_fields = sorted(str(name) for name in set(payload) - MANIFEST_FIELD_NAMES)
        if unexpected_fields:
            raise ValueError(
                f"publication manifest contains unexpected fields: {', '.join(unexpected_fields)}"
            )
        if payload.get("schema_version") != 1:
            raise ValueError("publication manifest schema_version must be 1")
        counts = PublicationCounts.from_json(payload.get("counts"))
        status_value = _required_string(payload, "publication_status")
        try:
            status = PublicationStatus(status_value)
        except ValueError as exc:
            raise ValueError(f"publication manifest publication_status is invalid: {status_value}") from exc
        blockers_value = payload.get("publication_blockers")
        if not isinstance(blockers_value, list) or not all(isinstance(value, str) for value in blockers_value):
            raise ValueError("publication manifest publication_blockers must be a string list")
        state_snapshot_available = payload.get("state_snapshot_available")
        if "state_snapshot_available" in payload and not isinstance(state_snapshot_available, bool):
            raise ValueError("publication manifest state_snapshot_available must be a boolean")
        return cls(
            report_date=_required_string(payload, "report_date"),
            workflow_run_id=_required_string(payload, "workflow_run_id"),
            workflow_url=_required_string(payload, "workflow_url"),
            trigger=_required_string(payload, "trigger"),
            git_sha=_required_string(payload, "git_sha"),
            pipeline_exit_code=_required_int(payload, "pipeline_exit_code"),
            status=status,
            blockers=tuple(blockers_value),
            counts=counts,
            report_path=_required_string(payload, "report_path"),
            report_exists=_required_bool(payload, "report_exists"),
            run_summary_path=_required_string(payload, "run_summary_path"),
            master_state_updated=_required_bool(payload, "master_state_updated"),
            report_email_sent=_required_bool(payload, "report_email_sent"),
            alert_email_requested=_required_bool(payload, "alert_email_requested"),
            failure_snapshot_push_status=_required_string(payload, "failure_snapshot_push_status"),
            failure_snapshot_branch=_required_string(payload, "failure_snapshot_branch"),
            failure_snapshot_path=_required_string(payload, "failure_snapshot_path"),
            artifact_name=_required_string(payload, "artifact_name"),
            state_snapshot_available=state_snapshot_available,
            failure_detail=_required_string(payload, "failure_detail"),
        )

    def workflow_outputs(self, *, prefix: str = "") -> dict[str, str]:
        outputs = {
            "publication_status": self.status.value,
            "publication_blockers": ",".join(self.blockers),
            "master_state_updated": str(self.master_state_updated).lower(),
            "report_exists": str(self.report_exists).lower(),
            "report_path": self.report_path,
            "run_summary_path": self.run_summary_path,
            "pipeline_exit_code": str(self.pipeline_exit_code),
            "snapshot_path": self.failure_snapshot_path,
            "artifact_name": self.artifact_name,
            **{name: str(value) for name, value in self.counts.to_json().items()},
        }
        return {f"{prefix}{key}": value for key, value in outputs.items()}


def _required_string(payload: Mapping[str, object], name: str) -> str:
    value = payload.get(name)
    if not isinstance(value, str):
        raise ValueError(f"publication manifest {name} must be a string")
    return value


def _required_int(payload: Mapping[str, object], name: str) -> int:
    value = payload.get(name)
    if isinstance(value, bool) or not isinstance(value, int):
        raise ValueError(f"publication manifest {name} must be an integer")
    return value


def _required_bool(payload: Mapping[str, object], name: str) -> bool:
    value = payload.get(name)
    if not isinstance(value, bool):
        raise ValueError(f"publication manifest {name} must be a boolean")
    return value
