import pytest

from notice_push.observability.publication_manifest import PublicationCounts
from notice_push.observability.run_summary_contract import (
    RUN_SUMMARY_SCHEMA_VERSION,
    FailureRunSummaryContract,
    RunSummaryContract,
)


def test_publication_counts_reject_negative_values():
    with pytest.raises(ValueError, match="greater than or equal to 0"):
        PublicationCounts.from_json({"source_error_count": -1})


def run_summary_payload():
    return {
        "schema_version": RUN_SUMMARY_SCHEMA_VERSION,
        "report_date": "2026-07-14",
        "new_count": 1,
        "updated_count": 0,
        "retried_count": 0,
        "summarized_count": 1,
        "manual_review_count": 0,
        "failed_count": 0,
        "source_error_count": 0,
        "audit_error_count": 0,
        "audit_warning_count": 0,
        "refresh_seen_error_count": 0,
        "publication_eligibility": "published",
        "publication_blockers": [],
        "started_at": "2026-07-14T01:00:00+00:00",
        "finished_at": "2026-07-14T01:00:01+00:00",
        "duration_seconds": 1.0,
        "git_sha": "abc",
        "failure_types": {},
        "source_errors": [],
        "audit_issues": [],
        "models": ["test-model"],
        "media_counts": {},
        "sources": [],
        "report_path": "resources/results/2026-07-14.md",
    }


def test_run_summary_contract_round_trips_json_text():
    contract = RunSummaryContract.model_validate(run_summary_payload())

    restored = RunSummaryContract.from_json_text(contract.to_json_text())

    assert restored == contract


def test_run_summary_contract_rejects_unknown_fields():
    payload = run_summary_payload()
    payload["unexpected"] = True

    with pytest.raises(ValueError, match="unexpected"):
        RunSummaryContract.from_json_text(__import__("json").dumps(payload))


def test_failure_run_summary_contract_uses_typed_counts():
    contract = FailureRunSummaryContract.model_validate(
        {
            "schema_version": RUN_SUMMARY_SCHEMA_VERSION,
            "report_date": "2026-07-14",
            "publication_eligibility": "blocked",
            "publication_blockers": ["source_error_count=1"],
            "pipeline_exit_code": 2,
            "pipeline_log_path": "notice_pipeline.log",
            "counts": {
                "new_count": 0,
                "updated_count": 0,
                "retried_count": 0,
                "summarized_count": 0,
                "failed_count": 0,
                "manual_review_count": 0,
                "source_error_count": 1,
                "audit_error_count": 0,
                "audit_warning_count": 0,
                "refresh_seen_error_count": 0,
            },
            "fallback": True,
        }
    )

    assert contract.counts.source_error_count == 1
