from __future__ import annotations

from collections import Counter
from datetime import date
from pathlib import Path

from notice_push.domain import PipelineCounters, PipelineResult
from notice_push.observability.publication import PublicationFacts, decide_pipeline_publication
from notice_push.observability.run_summary_contract import (
    RUN_SUMMARY_SCHEMA_VERSION,
    RunSummaryContract,
)


def write_run_summary(output_dir: Path, report_date: date, pipeline_result: PipelineResult) -> Path:
    json_dir = Path(output_dir) / "json"
    json_dir.mkdir(parents=True, exist_ok=True)
    path = json_dir / f"{report_date.isoformat()}.json"
    contract = _run_summary_contract(report_date, pipeline_result)
    path.write_text(contract.to_json_text(), encoding="utf-8")
    return path


def _run_summary_payload(report_date: date, pipeline_result: PipelineResult) -> dict[str, object]:
    return _run_summary_contract(report_date, pipeline_result).model_dump(mode="json")


def _run_summary_contract(
    report_date: date,
    pipeline_result: PipelineResult,
) -> RunSummaryContract:
    counters = pipeline_counters(pipeline_result)
    publication = decide_pipeline_publication(
        PublicationFacts(
            report_path=str(pipeline_result.report_path or ""),
            source_error_count=counters.source_error_count,
            audit_error_count=counters.audit_error_count,
        )
    )
    return RunSummaryContract.model_validate({
        "schema_version": RUN_SUMMARY_SCHEMA_VERSION,
        "report_date": report_date.isoformat(),
        "new_count": counters.new_count,
        "updated_count": counters.updated_count,
        "retried_count": counters.retried_count,
        "summarized_count": counters.summarized_count,
        "manual_review_count": counters.manual_review_count,
        "failed_count": counters.failed_count,
        "source_error_count": counters.source_error_count,
        "audit_error_count": counters.audit_error_count,
        "audit_warning_count": counters.audit_warning_count,
        "refresh_seen_error_count": counters.refresh_seen_error_count,
        "publication_eligibility": publication.status.value,
        "publication_blockers": list(publication.blockers),
        "started_at": pipeline_result.started_at,
        "finished_at": pipeline_result.finished_at,
        "duration_seconds": pipeline_result.duration_seconds,
        "git_sha": pipeline_result.git_sha,
        "failure_types": _failure_types(pipeline_result),
        "source_errors": [
            {
                "source_id": error.source_id,
                "source_name": error.source_name,
                "url": error.url,
                "reason": error.reason,
            }
            for error in pipeline_result.source_errors
        ],
        "audit_issues": [
            {
                "source_id": issue.source_id,
                "source_name": issue.source_name,
                "url": issue.url,
                "severity": issue.severity,
                "reason": issue.reason,
            }
            for audit in pipeline_result.audit_results
            for issue in audit.issues
        ],
        "models": list(pipeline_result.models_used),
        "media_counts": pipeline_result.media_counts,
        "sources": [
            {
                "source_id": stats.source_id,
                "source_name": stats.source_name,
                "summarized_count": stats.summarized_count,
                "failed_count": stats.failed_count,
                "source_error_count": stats.source_error_count,
                "audit_error_count": stats.audit_error_count,
                "audit_warning_count": stats.audit_warning_count,
                "refresh_seen_error_count": stats.refresh_seen_error_count,
            }
            for stats in pipeline_result.source_stats
        ],
        "report_path": str(pipeline_result.report_path or ""),
    })


def pipeline_counters(result: PipelineResult) -> PipelineCounters:
    audit_error_count = sum(
        1
        for audit in result.audit_results
        for issue in audit.issues
        if issue.severity == "error"
    )
    audit_warning_count = sum(
        1
        for audit in result.audit_results
        for issue in audit.issues
        if issue.severity == "warning"
    )
    return PipelineCounters(
        new_count=result.new_count,
        updated_count=result.updated_count,
        retried_count=result.retried_count,
        summarized_count=result.summarized_count,
        failed_count=len(result.failed),
        manual_review_count=result.manual_review_count,
        source_error_count=len(result.source_errors),
        audit_error_count=audit_error_count,
        audit_warning_count=audit_warning_count,
        refresh_seen_error_count=len(getattr(result, "refresh_seen_errors", ())),
    )


def _failure_types(result: PipelineResult) -> dict[str, int]:
    counts = Counter(
        failure.failure_type or _failure_type_from_reason(failure.reason)
        for failure in result.failed
    )
    return dict(sorted(counts.items()))


def _failure_type_from_reason(reason: str) -> str:
    message = reason.lower()
    if "unsupported video content" in message:
        return "unsupported_video_content"
    if "empty or too short" in message:
        return "detail_empty"
    if "timeout" in message:
        return "timeout"
    if "rate" in message or "429" in message:
        return "llm_rate_limit"
    return "unknown"
