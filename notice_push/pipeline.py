from __future__ import annotations

from datetime import date
from importlib import import_module
from time import perf_counter
from typing import Callable, Optional

from notice_push.crawler.failures import FailureRetryPolicy
from notice_push.crawler.list_scanner import UNBOUNDED_PAGE_SCAN, cutoff_datetime
from notice_push.crawler.notice_processing import NoticeProcessor
from notice_push.crawler.source_scan import scan_source_pages
from notice_push.domain import NoticeSource, PipelineResult, PipelineRunOptions
from notice_push.domain.config import AppConfig
from notice_push.observability.source_audit import SourceAuditor
from notice_push.pipeline_result import PipelineRunAccumulator, finalize_pipeline_result
from notice_push.sources.selection import select_sources
from notice_push.storage import NoticeStorage
from notice_push.crawler.stats import utc_now


AdapterFactory = Callable[[NoticeSource], object]


class NoticePipeline:
    def __init__(
        self,
        config: AppConfig,
        storage: NoticeStorage,
        http_client,
        summarizer,
        adapter_factory: Optional[AdapterFactory] = None,
    ):
        self.config = config
        self.storage = storage
        self.http_client = http_client
        self.summarizer = summarizer
        self.adapter_factory = adapter_factory or create_adapter

    def run(self, options: PipelineRunOptions) -> PipelineResult:
        started_at = utc_now()
        started_perf = perf_counter()
        report_day = options.report_date or date.today()
        selected_sources = select_sources(self.config.sources, options.source_ids)
        cutoff = cutoff_datetime(report_day, options.lookback_days)
        retry_policy = FailureRetryPolicy(
            limit=options.failed_retry_limit,
            after_hours=options.failed_retry_after_hours,
        )
        audit_results = self._audit_sources(selected_sources) if options.audit_sources else ()
        if not options.dry_run:
            self.storage.initialize()

        accumulator = PipelineRunAccumulator()
        processor = NoticeProcessor(
            storage=self.storage,
            http_client=self.http_client,
            summarizer=self.summarizer,
            detail_min_chars=self.config.detail_min_chars,
        )
        max_pages = options.max_pages_per_source
        if max_pages is None:
            max_pages = UNBOUNDED_PAGE_SCAN

        for source in selected_sources:
            adapter = self.adapter_factory(source)
            processed_count = 0
            seen_only_pages = 0

            def process_page(page):
                nonlocal processed_count, seen_only_pages
                remaining = (
                    None
                    if options.limit is None
                    else max(0, options.limit - processed_count)
                )
                outcome = processor.process_page(
                    source=source,
                    adapter=adapter,
                    page=page,
                    options=options,
                    retry_policy=retry_policy,
                    remaining_capacity=remaining,
                )
                accumulator.add_processing(outcome)
                processed_count += outcome.processed_count
                if options.bootstrap_seen:
                    return None
                seen_only_pages = 0 if outcome.had_candidates else seen_only_pages + 1
                if not options.dry_run and options.limit is not None and processed_count >= options.limit:
                    return "processing_limit"
                if (
                    options.stop_after_seen_pages is not None
                    and seen_only_pages >= options.stop_after_seen_pages
                ):
                    return "seen_page_limit"
                return None

            scan_outcome = scan_source_pages(
                source=source,
                adapter=adapter,
                http_client=self.http_client,
                max_pages=max_pages,
                cutoff=cutoff,
                on_page=process_page,
            )
            accumulator.source_errors.extend(scan_outcome.source_errors)

        return finalize_pipeline_result(
            config=self.config,
            storage=self.storage,
            options=options,
            report_day=report_day,
            selected_sources=selected_sources,
            audit_results=audit_results,
            accumulator=accumulator,
            started_at=started_at,
            started_perf=started_perf,
        )

    def _audit_sources(self, selected_sources):
        return SourceAuditor(
            self.http_client,
            self.adapter_factory,
            min_list_items=self.config.audit_policy.min_list_items,
            sample_detail_count=self.config.audit_policy.sample_detail_count,
            required_content_kinds=self.config.audit_policy.required_content_kinds,
        ).audit_sources(selected_sources)


def create_adapter(source: NoticeSource, detail_parser=None):
    module_name, _, class_name = source.adapter.rpartition(".")
    if not module_name or not class_name:
        raise ValueError(
            f"Adapter for source '{source.id}' must be an import path like "
            f"'package.module.AdapterClass', got: {source.adapter}"
        )
    module = import_module(module_name)
    adapter_class = getattr(module, class_name)
    return adapter_class(source, detail_parser=detail_parser)
