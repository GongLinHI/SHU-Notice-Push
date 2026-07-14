from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, ConfigDict, StrictBool, StrictFloat, StrictInt, StrictStr, ValidationError

from notice_push.observability.publication import PublicationStatus
from notice_push.observability.publication_manifest import PublicationCounts


RUN_SUMMARY_SCHEMA_VERSION = 2


class _StrictContract(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)


class SourceErrorRecord(_StrictContract):
    source_id: StrictStr
    source_name: StrictStr
    url: StrictStr
    reason: StrictStr


class AuditIssueRecord(SourceErrorRecord):
    severity: StrictStr


class SourceStatsRecord(_StrictContract):
    source_id: StrictStr
    source_name: StrictStr
    summarized_count: StrictInt
    failed_count: StrictInt
    source_error_count: StrictInt
    audit_error_count: StrictInt
    audit_warning_count: StrictInt
    refresh_seen_error_count: StrictInt


class RunSummaryContract(_StrictContract):
    schema_version: Literal[RUN_SUMMARY_SCHEMA_VERSION]
    report_date: StrictStr
    new_count: StrictInt
    updated_count: StrictInt
    retried_count: StrictInt
    summarized_count: StrictInt
    manual_review_count: StrictInt
    failed_count: StrictInt
    source_error_count: StrictInt
    audit_error_count: StrictInt
    audit_warning_count: StrictInt
    refresh_seen_error_count: StrictInt
    publication_eligibility: PublicationStatus
    publication_blockers: tuple[StrictStr, ...]
    started_at: StrictStr
    finished_at: StrictStr
    duration_seconds: StrictFloat
    git_sha: StrictStr
    failure_types: dict[StrictStr, StrictInt]
    source_errors: tuple[SourceErrorRecord, ...]
    audit_issues: tuple[AuditIssueRecord, ...]
    models: tuple[StrictStr, ...]
    media_counts: dict[StrictStr, StrictInt]
    sources: tuple[SourceStatsRecord, ...]
    report_path: StrictStr

    def to_json_text(self) -> str:
        return self.model_dump_json(indent=2) + "\n"

    @classmethod
    def from_json_text(cls, text: str) -> "RunSummaryContract":
        try:
            return cls.model_validate_json(text)
        except ValidationError as exc:
            raise ValueError(f"invalid run summary: {exc}") from exc


class FailureRunSummaryContract(_StrictContract):
    schema_version: Literal[RUN_SUMMARY_SCHEMA_VERSION]
    report_date: StrictStr
    publication_eligibility: PublicationStatus
    publication_blockers: tuple[StrictStr, ...]
    pipeline_exit_code: StrictInt
    pipeline_log_path: StrictStr
    counts: PublicationCounts
    fallback: Literal[True]

    def to_json_text(self) -> str:
        return self.model_dump_json(indent=2) + "\n"

    @classmethod
    def from_json_text(cls, text: str) -> "FailureRunSummaryContract":
        try:
            return cls.model_validate_json(text)
        except ValidationError as exc:
            raise ValueError(f"invalid failure run summary: {exc}") from exc
