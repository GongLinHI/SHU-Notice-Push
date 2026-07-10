from pathlib import Path

from notice_push.domain import PipelineResult, SourceAuditIssue, SourceAuditResult, SourceError
from notice_push.observability.publication import (
    PublicationFacts,
    PublicationStatus,
    WorkflowPublicationInput,
    decide_pipeline_publication,
    decide_workflow_publication,
)
from notice_push.observability.run_summary import _run_summary_payload


def test_pipeline_publication_blocks_source_and_audit_failures_in_stable_order():
    decision = decide_pipeline_publication(
        PublicationFacts(
            report_path="resources/results/2026-07-10.md",
            source_error_count=2,
            audit_error_count=1,
        )
    )

    assert decision.status is PublicationStatus.BLOCKED
    assert decision.blockers == ("source_error_count=2", "audit_error_count=1")
    assert decision.may_send_report is False
    assert decision.may_update_master is False
    assert decision.requires_failure_snapshot is True


def test_pipeline_publication_allows_report_with_manual_review_failures():
    decision = decide_pipeline_publication(
        PublicationFacts(
            report_path="resources/results/2026-07-10.md",
            source_error_count=0,
            audit_error_count=0,
        )
    )

    assert decision.status is PublicationStatus.PUBLISHED
    assert decision.blockers == ()
    assert decision.may_send_report is True
    assert decision.may_update_master is True
    assert decision.requires_failure_snapshot is False


def test_pipeline_publication_returns_no_report_without_blockers():
    decision = decide_pipeline_publication(
        PublicationFacts(report_path="", source_error_count=0, audit_error_count=0)
    )

    assert decision.status is PublicationStatus.NO_REPORT
    assert decision.may_send_report is False
    assert decision.may_update_master is True
    assert decision.requires_failure_snapshot is False


def test_workflow_publication_blocks_unexpected_exit_or_missing_counts():
    pipeline_decision = decide_pipeline_publication(
        PublicationFacts(report_path="resources/results/2026-07-10.md", source_error_count=0, audit_error_count=0)
    )

    unexpected_exit = decide_workflow_publication(
        WorkflowPublicationInput(raw_exit_code=3, expected_counts_present=True, pipeline_decision=pipeline_decision)
    )
    missing_counts = decide_workflow_publication(
        WorkflowPublicationInput(raw_exit_code=0, expected_counts_present=False, pipeline_decision=pipeline_decision)
    )

    assert unexpected_exit.status is PublicationStatus.BLOCKED
    assert unexpected_exit.blockers == ("pipeline_exit_code=2",)
    assert missing_counts.status is PublicationStatus.BLOCKED
    assert missing_counts.blockers == ("pipeline_exit_code=2",)


def test_workflow_publication_accepts_cli_no_report_exit_code():
    pipeline_decision = decide_pipeline_publication(
        PublicationFacts(report_path="", source_error_count=0, audit_error_count=0)
    )

    decision = decide_workflow_publication(
        WorkflowPublicationInput(raw_exit_code=1, expected_counts_present=True, pipeline_decision=pipeline_decision)
    )

    assert decision.status is PublicationStatus.NO_REPORT


def test_run_summary_v2_contains_pipeline_publication_eligibility():
    result = PipelineResult(
        report_path=Path("resources/results/2026-07-10.md"),
        new_count=1,
        summarized_count=1,
        source_errors=(
            SourceError(
                source_id="shu_official",
                source_name="上海大学官网",
                url="https://www.shu.edu.cn/tzgg.htm",
                reason="directory request failed",
            ),
        ),
        audit_results=(
            SourceAuditResult(
                source_id="shu_official",
                source_name="上海大学官网",
                list_url="https://www.shu.edu.cn/tzgg.htm",
                list_item_count=0,
                issues=(
                    SourceAuditIssue(
                        source_id="shu_official",
                        source_name="上海大学官网",
                        url="https://www.shu.edu.cn/tzgg.htm",
                        severity="error",
                        reason="no list items",
                    ),
                ),
            ),
        ),
    )

    payload = _run_summary_payload(__import__("datetime").date(2026, 7, 10), result)

    assert payload["schema_version"] == 2
    assert payload["publication_eligibility"] == "blocked"
    assert payload["publication_blockers"] == ["source_error_count=1", "audit_error_count=1"]
    assert payload["source_errors"] == [
        {
            "source_id": "shu_official",
            "source_name": "上海大学官网",
            "url": "https://www.shu.edu.cn/tzgg.htm",
            "reason": "directory request failed",
        }
    ]
    assert payload["audit_issues"] == [
        {
            "source_id": "shu_official",
            "source_name": "上海大学官网",
            "url": "https://www.shu.edu.cn/tzgg.htm",
            "severity": "error",
            "reason": "no list items",
        }
    ]
