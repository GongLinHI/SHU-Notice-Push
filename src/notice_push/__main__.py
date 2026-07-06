from __future__ import annotations

import argparse
import os
from datetime import date
from pathlib import Path
from typing import Optional

from src.notice_push.config import load_config
from src.notice_push.detail_parser import DetailParser
from src.notice_push.doctor import has_doctor_errors, run_doctor
from src.notice_push.html_utils import ParsingRules
from src.notice_push.http import HttpClient
from src.notice_push.llm import resolve_optional_provider
from src.notice_push.models import NoticeRuntimeProfile, PipelineRunOptions
from src.notice_push.pipeline import NoticePipeline, create_adapter
from src.notice_push.run_summary import pipeline_counters
from src.notice_push.source_audit import SourceAuditor
from src.notice_push.storage import NoticeStorage
from src.notice_push.summarizer import KimiMultimodalSummarizer, NoticeSummarizer, SummarizerRouter


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Fetch, summarize, and report SHU notices.")
    parser.add_argument(
        "--profile",
        choices=("daily", "backfill"),
        default="daily",
        help="Runtime profile. daily is for scheduled incremental runs; backfill scans history without early stop.",
    )
    parser.add_argument("--source", action="append", dest="sources", help="Run only one source id; repeatable.")
    parser.add_argument("--all-sources", action="store_true", help="Run all enabled sources. This is the default.")
    parser.add_argument("--dry-run", action="store_true", help="Fetch and parse without writing SQLite or reports.")
    parser.add_argument("--bootstrap-seen", action="store_true", help="Mark existing directory items as seen without summaries.")
    parser.add_argument("--limit", type=int, default=None, help="Maximum new notices to process per source.")
    parser.add_argument("--date", dest="report_date", default=None, help="Report date in YYYY-MM-DD format.")
    parser.add_argument("--state-path", type=Path, default=None, help="Override SQLite state path.")
    parser.add_argument("--output-dir", type=Path, default=None, help="Override report output directory.")
    parser.add_argument("--max-pages-per-source", type=int, default=None, help="Maximum directory pages to scan per source.")
    parser.add_argument("--stop-after-seen-pages", type=int, default=None, help="Stop after N pages with no new notices.")
    parser.add_argument("--detail-max-workers", type=int, default=None, help="Maximum concurrent detail page fetches.")
    parser.add_argument("--summary-max-workers", type=int, default=None, help="Maximum concurrent summary generation tasks.")
    parser.add_argument("--lookback-days", type=int, default=None, help="Only process notices within the last N days.")
    parser.add_argument("--skip-source-audit", action="store_true", help="Skip the lightweight source DOM audit.")
    parser.add_argument("--audit-only", action="store_true", help="Run source DOM audit only and exit.")
    parser.add_argument("--doctor", action="store_true", help="Check local configuration and state health.")
    return parser


def build_detail_parser(config) -> DetailParser:
    return DetailParser(
        ParsingRules(
            external_video_domains=config.parsing.external_video_domains,
            noise_image_markers=config.parsing.noise_image_markers,
        )
    )


def build_http_client(profile: NoticeRuntimeProfile) -> HttpClient:
    return HttpClient(
        timeout=profile.http_timeout,
        max_retries=profile.http_max_retries,
        initial_retry_delay=profile.http_initial_retry_delay,
    )


def build_pipeline(config, profile: NoticeRuntimeProfile) -> NoticePipeline:
    detail_parser = build_detail_parser(config)
    storage = NoticeStorage(config.state_path, config.sources)
    http_client = build_http_client(profile)
    deepseek_provider = resolve_optional_provider("deepseek", config.llm_providers["deepseek"])
    kimi_provider = resolve_optional_provider("kimi", config.llm_providers["kimi"])
    text_summarizer = NoticeSummarizer(
        prompt_dir=config.repo_root / "resources" / "prompts",
        prompt_name=config.prompt_name,
        model=deepseek_provider.model,
        api_key=deepseek_provider.api_key,
        base_url=deepseek_provider.base_url,
        timeout=profile.llm_timeout,
        max_retries=profile.llm_max_retries,
        initial_retry_delay=profile.llm_initial_retry_delay,
        retry_backoff=profile.llm_retry_backoff,
        summary_format_repair_retries=config.summary_format_repair_retries,
    )
    kimi_summarizer = KimiMultimodalSummarizer(
        prompt_dir=config.repo_root / "resources" / "prompts",
        prompt_name=config.prompt_name,
        model=kimi_provider.model,
        api_key=kimi_provider.api_key,
        base_url=kimi_provider.base_url,
        http_client=http_client,
        timeout=profile.llm_timeout,
        max_retries=profile.llm_max_retries,
        initial_retry_delay=profile.llm_initial_retry_delay,
        retry_backoff=profile.llm_retry_backoff,
        media_policy=config.media_policy,
        summary_format_repair_retries=config.summary_format_repair_retries,
    )
    summarizer = SummarizerRouter(
        text_summarizer=text_summarizer,
        kimi_summarizer=kimi_summarizer,
        routing=config.llm_routing,
    )
    return NoticePipeline(
        config=config,
        storage=storage,
        http_client=http_client,
        summarizer=summarizer,
        adapter_factory=lambda source: create_adapter(source, detail_parser=detail_parser),
    )


def run_source_audit(config, profile: NoticeRuntimeProfile, source_ids: tuple[str, ...]):
    detail_parser = build_detail_parser(config)
    http_client = build_http_client(profile)
    auditor = SourceAuditor(
        http_client=http_client,
        adapter_factory=lambda source: create_adapter(source, detail_parser=detail_parser),
        min_list_items=config.audit_policy.min_list_items,
        sample_detail_count=config.audit_policy.sample_detail_count,
        required_content_kinds=config.audit_policy.required_content_kinds,
    )
    return auditor.audit_sources(select_sources(config, source_ids or None))


def select_sources(config, source_ids: Optional[tuple[str, ...]]):
    if source_ids:
        requested = set(source_ids)
        selected = [source for source in config.sources if source.id in requested]
        found = {source.id for source in selected}
        missing = sorted(requested - found)
        if missing:
            available = ", ".join(source.id for source in config.sources)
            raise ValueError(f"Unknown source id(s): {', '.join(missing)}. Available sources: {available}")
        return selected
    return [source for source in config.sources if source.enabled]


def audit_counts(audit_results) -> tuple[int, int]:
    error_count = sum(1 for result in audit_results for issue in result.issues if issue.severity == "error")
    warning_count = sum(1 for result in audit_results for issue in result.issues if issue.severity == "warning")
    return error_count, warning_count


def print_audit_counts(audit_results) -> None:
    audit_error_count, audit_warning_count = audit_counts(audit_results)
    print(f"audit_error_count={audit_error_count}")
    print(f"audit_warning_count={audit_warning_count}")


def run_options_from_args(args, profile: NoticeRuntimeProfile) -> PipelineRunOptions:
    return PipelineRunOptions(
        source_ids=tuple(args.sources or ()),
        dry_run=args.dry_run,
        limit=args.limit,
        report_date=date.fromisoformat(args.report_date) if args.report_date else None,
        max_pages_per_source=(
            args.max_pages_per_source if args.max_pages_per_source is not None else profile.max_pages_per_source
        ),
        stop_after_seen_pages=(
            args.stop_after_seen_pages if args.stop_after_seen_pages is not None else profile.stop_after_seen_pages
        ),
        detail_max_workers=args.detail_max_workers if args.detail_max_workers is not None else profile.detail_max_workers,
        summary_max_workers=args.summary_max_workers if args.summary_max_workers is not None else profile.summary_max_workers,
        lookback_days=args.lookback_days if args.lookback_days is not None else profile.lookback_days,
        retry_failed=profile.retry_failed,
        failed_retry_limit=profile.failed_retry_limit,
        failed_retry_after_hours=profile.failed_retry_after_hours,
        refresh_seen_details=profile.refresh_seen_details,
        refresh_seen_max_workers=profile.refresh_seen_max_workers,
        refresh_seen_limit=profile.refresh_seen_limit,
        bootstrap_seen=args.bootstrap_seen,
        audit_sources=not args.skip_source_audit,
        git_sha=os.environ.get("GITHUB_SHA", ""),
    )


def main(argv: Optional[list[str]] = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    config = load_config(state_path=args.state_path, output_dir=args.output_dir)
    profile = config.runtime_profile(args.profile)
    if args.doctor:
        findings = run_doctor(config)
        for finding in findings:
            if finding.startswith("error:"):
                print(f"doctor_error={finding.removeprefix('error:').strip()}")
            elif finding.startswith("warning:"):
                print(f"doctor_warning={finding.removeprefix('warning:').strip()}")
            else:
                print(f"doctor_warning={finding}")
        return 2 if has_doctor_errors(findings) else 0

    if args.sources:
        available_sources = {source.id for source in config.sources}
        missing_sources = sorted(set(args.sources) - available_sources)
        if missing_sources:
            parser.error(
                "unknown source id(s): "
                + ", ".join(missing_sources)
                + ". Available sources: "
                + ", ".join(sorted(available_sources))
            )
    if args.audit_only:
        audit_results = run_source_audit(config, profile, tuple(args.sources or ()))
        print_audit_counts(audit_results)
        audit_error_count, _ = audit_counts(audit_results)
        return 0 if audit_error_count == 0 else 1

    pipeline = build_pipeline(config, profile)
    result = pipeline.run(run_options_from_args(args, profile))
    counters = pipeline_counters(result)

    print(f"new_count={counters.new_count}")
    print(f"retried_count={counters.retried_count}")
    print(f"summarized_count={counters.summarized_count}")
    print(f"failed_count={counters.failed_count}")
    print(f"manual_review_count={counters.manual_review_count}")
    print(f"source_error_count={counters.source_error_count}")
    print(f"audit_error_count={counters.audit_error_count}")
    print(f"audit_warning_count={counters.audit_warning_count}")
    print(f"refresh_seen_error_count={counters.refresh_seen_error_count}")
    if result.report_path:
        print(f"report_path={result.report_path}")
    if result.run_summary_path:
        print(f"run_summary_path={result.run_summary_path}")

    if args.dry_run:
        return 0
    return 0 if result.report_path else 1


if __name__ == "__main__":
    raise SystemExit(main())
