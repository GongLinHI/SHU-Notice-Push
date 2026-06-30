from __future__ import annotations

import argparse
from datetime import date
from pathlib import Path
from typing import Optional

from src.notice_push.config import load_config
from src.notice_push.http import HttpClient
from src.notice_push.models import NoticeRuntimeProfile
from src.notice_push.pipeline import NoticePipeline
from src.notice_push.storage import NoticeStorage
from src.notice_push.summarizer import NoticeSummarizer


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
    return parser


def build_pipeline(config, profile: NoticeRuntimeProfile) -> NoticePipeline:
    storage = NoticeStorage(config.state_path, config.sources)
    http_client = HttpClient(
        timeout=profile.http_timeout,
        max_retries=profile.http_max_retries,
        initial_retry_delay=profile.http_initial_retry_delay,
    )
    summarizer = NoticeSummarizer(
        prompt_dir=config.repo_root / "resources" / "prompts",
        prompt_name=config.prompt_name,
        model=config.deepseek_model,
    )
    return NoticePipeline(
        config=config,
        storage=storage,
        http_client=http_client,
        summarizer=summarizer,
    )


def main(argv: Optional[list[str]] = None) -> int:
    args = build_parser().parse_args(argv)
    config = load_config(state_path=args.state_path, output_dir=args.output_dir)
    profile = config.runtime_profile(args.profile)
    pipeline = build_pipeline(config, profile)
    report_date = date.fromisoformat(args.report_date) if args.report_date else None
    max_pages_per_source = args.max_pages_per_source
    stop_after_seen_pages = args.stop_after_seen_pages
    detail_max_workers = args.detail_max_workers
    summary_max_workers = args.summary_max_workers

    if max_pages_per_source is None:
        max_pages_per_source = profile.max_pages_per_source
    if stop_after_seen_pages is None:
        stop_after_seen_pages = profile.stop_after_seen_pages
    if detail_max_workers is None:
        detail_max_workers = profile.detail_max_workers
    if summary_max_workers is None:
        summary_max_workers = profile.summary_max_workers

    result = pipeline.run(
        source_ids=args.sources,
        dry_run=args.dry_run,
        limit=args.limit,
        report_date=report_date,
        max_pages_per_source=max_pages_per_source,
        stop_after_seen_pages=stop_after_seen_pages,
        detail_max_workers=detail_max_workers,
        summary_max_workers=summary_max_workers,
        bootstrap_seen=args.bootstrap_seen,
    )

    print(f"new_count={result.new_count}")
    print(f"summarized_count={result.summarized_count}")
    print(f"failed_count={len(result.failed)}")
    print(f"source_error_count={len(result.source_errors)}")
    if result.report_path:
        print(f"report_path={result.report_path}")

    if args.dry_run:
        return 0
    return 0 if result.report_path else 1


if __name__ == "__main__":
    raise SystemExit(main())
