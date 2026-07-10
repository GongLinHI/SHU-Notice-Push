from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum


class PublicationStatus(StrEnum):
    PUBLISHED = "published"
    NO_REPORT = "no_report"
    BLOCKED = "blocked"


@dataclass(frozen=True)
class PublicationFacts:
    report_path: str
    source_error_count: int
    audit_error_count: int


@dataclass(frozen=True)
class PublicationDecision:
    status: PublicationStatus
    blockers: tuple[str, ...]
    may_send_report: bool
    may_update_master: bool
    requires_failure_snapshot: bool


@dataclass(frozen=True)
class WorkflowPublicationInput:
    raw_exit_code: int
    expected_counts_present: bool
    pipeline_decision: PublicationDecision | None


def decide_pipeline_publication(facts: PublicationFacts) -> PublicationDecision:
    blockers = _pipeline_blockers(facts)
    if blockers:
        return _blocked(blockers)
    if facts.report_path:
        return PublicationDecision(
            status=PublicationStatus.PUBLISHED,
            blockers=(),
            may_send_report=True,
            may_update_master=True,
            requires_failure_snapshot=False,
        )
    return PublicationDecision(
        status=PublicationStatus.NO_REPORT,
        blockers=(),
        may_send_report=False,
        may_update_master=True,
        requires_failure_snapshot=False,
    )


def decide_workflow_publication(input: WorkflowPublicationInput) -> PublicationDecision:
    if input.raw_exit_code not in (0, 1) or not input.expected_counts_present or input.pipeline_decision is None:
        return _blocked(("pipeline_exit_code=2",))
    return input.pipeline_decision


def _pipeline_blockers(facts: PublicationFacts) -> tuple[str, ...]:
    blockers: list[str] = []
    if facts.source_error_count > 0:
        blockers.append(f"source_error_count={facts.source_error_count}")
    if facts.audit_error_count > 0:
        blockers.append(f"audit_error_count={facts.audit_error_count}")
    return tuple(blockers)


def _blocked(blockers: tuple[str, ...]) -> PublicationDecision:
    return PublicationDecision(
        status=PublicationStatus.BLOCKED,
        blockers=blockers,
        may_send_report=False,
        may_update_master=False,
        requires_failure_snapshot=True,
    )
