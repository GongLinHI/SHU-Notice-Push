from __future__ import annotations

from typing import Annotated, Literal, Mapping

from pydantic import BaseModel, ConfigDict, Field, StrictBool, StrictInt, StrictStr, ValidationError

from notice_push.observability.publication import PublicationDecision, PublicationStatus


PUBLICATION_MANIFEST_SCHEMA_VERSION = 1
FAILURE_SNAPSHOT_BRANCH = "bot/failure-snapshots"
NonNegativeCount = Annotated[int, Field(strict=True, ge=0)]


class PublicationCounts(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    new_count: NonNegativeCount = 0
    updated_count: NonNegativeCount = 0
    retried_count: NonNegativeCount = 0
    summarized_count: NonNegativeCount = 0
    failed_count: NonNegativeCount = 0
    manual_review_count: NonNegativeCount = 0
    source_error_count: NonNegativeCount = 0
    audit_error_count: NonNegativeCount = 0
    audit_warning_count: NonNegativeCount = 0
    refresh_seen_error_count: NonNegativeCount = 0

    def to_json(self) -> dict[str, int]:
        return self.model_dump(mode="json")

    @classmethod
    def from_json(cls, payload: object) -> "PublicationCounts":
        try:
            return cls.model_validate(payload)
        except ValidationError as exc:
            _raise_contract_error("publication manifest counts", exc)


COUNT_FIELD_NAMES = tuple(PublicationCounts.model_fields)


class PublicationManifest(BaseModel):
    model_config = ConfigDict(
        extra="forbid",
        frozen=True,
        populate_by_name=True,
    )

    schema_version: Literal[PUBLICATION_MANIFEST_SCHEMA_VERSION]
    report_date: StrictStr
    workflow_run_id: StrictStr
    workflow_url: StrictStr
    trigger: StrictStr
    git_sha: StrictStr
    pipeline_exit_code: StrictInt
    status: PublicationStatus = Field(alias="publication_status")
    blockers: tuple[StrictStr, ...] = Field(alias="publication_blockers")
    counts: PublicationCounts
    report_path: StrictStr
    report_exists: StrictBool
    run_summary_path: StrictStr
    master_state_updated: StrictBool
    report_email_sent: StrictBool
    alert_email_requested: StrictBool
    failure_snapshot_push_status: StrictStr
    failure_snapshot_branch: StrictStr
    failure_snapshot_path: StrictStr
    artifact_name: StrictStr
    state_snapshot_available: StrictBool | None = None
    failure_detail: StrictStr

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
        return cls(
            schema_version=PUBLICATION_MANIFEST_SCHEMA_VERSION,
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
            failure_snapshot_path=(
                f"failure-snapshots/{report_date}/run-{run_id}" if needs_snapshot else ""
            ),
            artifact_name=(
                f"notice-failure-snapshot-{report_date}-{run_id}" if needs_snapshot else ""
            ),
            failure_detail="",
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
            schema_version=PUBLICATION_MANIFEST_SCHEMA_VERSION,
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
            failure_detail="",
        )

    def to_json(self) -> dict[str, object]:
        return self.model_dump(
            mode="json",
            by_alias=True,
            exclude_none=True,
        )

    def to_json_text(self) -> str:
        return self.model_dump_json(
            by_alias=True,
            exclude_none=True,
            indent=2,
        ) + "\n"

    @classmethod
    def from_json(cls, payload: Mapping[str, object]) -> "PublicationManifest":
        try:
            return cls.model_validate(payload)
        except ValidationError as exc:
            _raise_contract_error("publication manifest", exc)

    @classmethod
    def from_json_text(cls, text: str) -> "PublicationManifest":
        try:
            return cls.model_validate_json(text)
        except ValidationError as exc:
            _raise_contract_error("publication manifest", exc)

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


def _raise_contract_error(name: str, exc: ValidationError):
    unexpected = [
        ".".join(str(part) for part in error["loc"])
        for error in exc.errors()
        if error["type"] == "extra_forbidden"
    ]
    if unexpected:
        raise ValueError(
            f"{name} contains unexpected fields: {', '.join(sorted(unexpected))}"
        ) from exc
    raise ValueError(f"invalid {name}: {exc}") from exc
