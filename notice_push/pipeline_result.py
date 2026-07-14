from __future__ import annotations

from dataclasses import dataclass, field, replace
from datetime import date
from time import perf_counter

from notice_push.crawler.notice_processing import ProcessingOutcome
from notice_push.crawler.stats import media_counts, models_used, source_stats, utc_now
from notice_push.domain import FailedNotice, PipelineResult, PipelineRunOptions, RefreshSeenError, ReportStats, SourceError
from notice_push.observability.run_summary import write_run_summary
from notice_push.reporting.markdown import ReportEntry, render_report, write_report


@dataclass
class PipelineRunAccumulator:
    entries: list[ReportEntry] = field(default_factory=list)
    failures: list[FailedNotice] = field(default_factory=list)
    source_errors: list[SourceError] = field(default_factory=list)
    refresh_seen_errors: list[RefreshSeenError] = field(default_factory=list)
    new_count: int = 0
    retried_count: int = 0
    updated_count: int = 0

    def add_processing(self, outcome: ProcessingOutcome) -> None:
        self.entries.extend(outcome.entries)
        self.failures.extend(outcome.failures)
        self.refresh_seen_errors.extend(outcome.refresh_seen_errors)
        self.new_count += outcome.new_count
        self.retried_count += outcome.retried_count
        self.updated_count += outcome.updated_count


def finalize_pipeline_result(
    *,
    config,
    storage,
    options: PipelineRunOptions,
    report_day: date,
    selected_sources,
    audit_results,
    accumulator: PipelineRunAccumulator,
    started_at: str,
    started_perf: float,
) -> PipelineResult:
    report_path = None
    if not options.dry_run and (accumulator.entries or accumulator.failures):
        stats = ReportStats(
            new_count=accumulator.new_count,
            retried_count=accumulator.retried_count,
            summarized_count=len(accumulator.entries),
            manual_review_count=len(accumulator.failures),
            updated_count=accumulator.updated_count,
        )
        markdown = render_report(report_day, accumulator.entries, accumulator.failures, stats)
        report_path = write_report(config.output_dir, report_day, markdown)

    result = PipelineResult(
        report_path=report_path,
        new_count=accumulator.new_count,
        updated_count=accumulator.updated_count,
        summarized_count=len(accumulator.entries),
        retried_count=accumulator.retried_count,
        manual_review_count=len(accumulator.failures),
        failed=tuple(accumulator.failures),
        source_errors=tuple(accumulator.source_errors),
        audit_results=audit_results,
        refresh_seen_errors=tuple(accumulator.refresh_seen_errors),
        source_stats=source_stats(
            selected_sources,
            accumulator.entries,
            accumulator.failures,
            accumulator.source_errors,
            audit_results,
            accumulator.refresh_seen_errors,
        ),
        models_used=models_used(accumulator.entries),
        media_counts=media_counts(accumulator.entries),
        started_at=started_at,
        finished_at=utc_now(),
        duration_seconds=round(perf_counter() - started_perf, 3),
        git_sha=options.git_sha,
    )
    if options.dry_run:
        return result
    run_summary_path = write_run_summary(config.output_dir, report_day, result)
    storage.checkpoint()
    return replace(result, run_summary_path=run_summary_path)
