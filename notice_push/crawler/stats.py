from __future__ import annotations

from datetime import datetime, timezone

from notice_push.domain import FailedNotice, NoticeSource, PipelineSourceStats, RefreshSeenError, SourceError
from notice_push.reporting.markdown import ReportEntry


def source_stats(
    sources: list[NoticeSource],
    entries: list[ReportEntry],
    failures: list[FailedNotice],
    source_errors: list[SourceError],
    audit_results,
    refresh_seen_errors: list[RefreshSeenError],
) -> tuple[PipelineSourceStats, ...]:
    stats = {
        source.id: {
            "source": source,
            "summarized_count": 0,
            "failed_count": 0,
            "source_error_count": 0,
            "audit_error_count": 0,
            "audit_warning_count": 0,
            "refresh_seen_error_count": 0,
        }
        for source in sources
    }
    for entry in entries:
        if entry.source_id in stats:
            stats[entry.source_id]["summarized_count"] += 1
    for failure in failures:
        if failure.source_id in stats:
            stats[failure.source_id]["failed_count"] += 1
    for error in source_errors:
        if error.source_id in stats:
            stats[error.source_id]["source_error_count"] += 1
    for audit in audit_results:
        if audit.source_id not in stats:
            continue
        stats[audit.source_id]["audit_error_count"] += sum(
            1 for issue in audit.issues if issue.severity == "error"
        )
        stats[audit.source_id]["audit_warning_count"] += sum(
            1 for issue in audit.issues if issue.severity == "warning"
        )
    for error in refresh_seen_errors:
        if error.source_id in stats:
            stats[error.source_id]["refresh_seen_error_count"] += 1

    return tuple(
        PipelineSourceStats(
            source_id=source_id,
            source_name=values["source"].name,
            summarized_count=int(values["summarized_count"]),
            failed_count=int(values["failed_count"]),
            source_error_count=int(values["source_error_count"]),
            audit_error_count=int(values["audit_error_count"]),
            audit_warning_count=int(values["audit_warning_count"]),
            refresh_seen_error_count=int(values["refresh_seen_error_count"]),
        )
        for source_id, values in stats.items()
    )


def models_used(entries: list[ReportEntry]) -> tuple[str, ...]:
    return tuple(sorted({entry.summary.model for entry in entries if entry.summary.model}))


def media_counts(entries: list[ReportEntry]) -> dict[str, int]:
    counts = {"pdf": 0, "image": 0, "video": 0}
    for entry in entries:
        content_kind = entry.detail.content_kind
        if content_kind in counts:
            counts[content_kind] += 1
    return {key: value for key, value in counts.items() if value}


def utc_now() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat()
