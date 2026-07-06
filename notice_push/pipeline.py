from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import replace
from datetime import date
from importlib import import_module
from time import perf_counter
from typing import Callable, Iterable, Optional

from notice_push.domain.config import AppConfig
from notice_push.crawler.detail_fetcher import PreparedNotice, fetch_details_for_items, is_summarizable_detail
from notice_push.crawler.failures import FailureRetryPolicy, classify_failure, retry_limit_for_failure
from notice_push.crawler.list_scanner import (
    UNBOUNDED_PAGE_SCAN,
    cutoff_datetime,
    item_key,
    items_within_lookback,
    page_is_before_cutoff,
)
from notice_push.crawler.refresh_seen import update_seen_details_if_changed
from notice_push.crawler.stats import media_counts, models_used, source_stats, utc_now
from notice_push.http import HttpClient
from notice_push.domain import (
    FailedNotice,
    NoticeListItem,
    NoticeSource,
    PipelineResult,
    PipelineRunOptions,
    RefreshSeenError,
    ReportStats,
    SourceError,
)
from notice_push.reporting.markdown import ReportEntry, render_report, write_report
from notice_push.observability.run_summary import write_run_summary
from notice_push.observability.source_audit import SourceAuditor
from notice_push.storage import NoticeStorage


AdapterFactory = Callable[[NoticeSource], object]


class NoticePipeline:
    def __init__(
        self,
        config: AppConfig,
        storage: NoticeStorage,
        http_client: HttpClient,
        summarizer,
        adapter_factory: Optional[AdapterFactory] = None,
    ):
        self.config = config
        self.storage = storage
        self.http_client = http_client
        self.summarizer = summarizer
        self.adapter_factory = adapter_factory or create_adapter

    def run(
        self,
        options: PipelineRunOptions,
    ) -> PipelineResult:
        started_at = utc_now()
        started_perf = perf_counter()
        selected_sources = self._select_sources(options.source_ids or None)
        max_pages = options.max_pages_per_source
        stop_after_seen = options.stop_after_seen_pages
        detail_worker_count = options.detail_max_workers
        summary_worker_count = options.summary_max_workers
        active_lookback_days = options.lookback_days
        active_retry_failed = options.retry_failed
        active_failed_retry_limit = options.failed_retry_limit
        active_failed_retry_after_hours = options.failed_retry_after_hours
        active_refresh_seen_details = options.refresh_seen_details
        active_refresh_seen_workers = options.refresh_seen_max_workers
        active_refresh_seen_limit = options.refresh_seen_limit
        if max_pages is None:
            max_pages = UNBOUNDED_PAGE_SCAN
        report_day = options.report_date or date.today()
        cutoff = cutoff_datetime(report_day, active_lookback_days)
        failure_retry_policy = FailureRetryPolicy(
            limit=active_failed_retry_limit,
            after_hours=active_failed_retry_after_hours,
        )

        entries: list[ReportEntry] = []
        failures: list[FailedNotice] = []
        source_errors: list[SourceError] = []
        refresh_seen_errors: list[RefreshSeenError] = []
        audit_results = ()
        new_count = 0
        retried_count = 0
        updated_count = 0

        if options.audit_sources:
            audit_results = SourceAuditor(
                self.http_client,
                self.adapter_factory,
                min_list_items=self.config.audit_policy.min_list_items,
                sample_detail_count=self.config.audit_policy.sample_detail_count,
                required_content_kinds=self.config.audit_policy.required_content_kinds,
            ).audit_sources(selected_sources)

        if not options.dry_run:
            self.storage.initialize()

        for source in selected_sources:
            adapter = self.adapter_factory(source)
            page_url: Optional[str] = source.list_url
            pages_scanned = 0
            seen_only_pages = 0
            processed_for_source = 0
            visited_page_urls: set[str] = set()

            while page_url and pages_scanned < max_pages:
                if page_url in visited_page_urls:
                    break
                visited_page_urls.add(page_url)
                try:
                    list_html = self.http_client.get_text(page_url)
                    list_items = adapter.parse_list_page(list_html, page_url)
                except Exception as exc:
                    source_errors.append(
                        SourceError(
                            source_id=source.id,
                            source_name=source.name,
                            url=page_url,
                            reason=str(exc),
                        )
                    )
                    break

                processable_list_items = items_within_lookback(list_items, cutoff)
                page_before_cutoff = page_is_before_cutoff(list_items, cutoff)

                if options.bootstrap_seen:
                    if not options.dry_run:
                        self.storage.mark_seen_baseline(processable_list_items)
                    if page_before_cutoff:
                        break
                    page_url = adapter.find_next_page_url(list_html, page_url)
                    pages_scanned += 1
                    continue

                seen_rows = {} if options.dry_run else self.storage.find_seen_items(processable_list_items)
                if options.dry_run:
                    new_items = processable_list_items
                    retry_items: list[NoticeListItem] = []
                    updated_items: list[NoticeListItem] = []
                else:
                    new_items, retry_items, updated_items = self.storage.split_pipeline_items(
                        processable_list_items,
                        retry_failed=active_retry_failed,
                        failed_retry_limit=active_failed_retry_limit,
                    )
                new_keys = {item_key(item) for item in new_items}
                retry_keys = {item_key(item) for item in retry_items}
                updated_keys = {item_key(item) for item in updated_items}
                processable_keys = new_keys | retry_keys | updated_keys
                candidate_items = [item for item in processable_list_items if item_key(item) in processable_keys]
                if candidate_items:
                    seen_only_pages = 0
                else:
                    seen_only_pages += 1

                remaining_capacity = None if options.limit is None else max(0, options.limit - processed_for_source)
                if remaining_capacity == 0:
                    break

                selected_items = candidate_items if remaining_capacity is None else candidate_items[:remaining_capacity]
                processed_for_source += len(selected_items)
                new_count += sum(1 for item in selected_items if item_key(item) in new_keys)
                retried_count += sum(1 for item in selected_items if item_key(item) in retry_keys)
                selected_updated_items = [item for item in selected_items if item_key(item) in updated_keys]
                selected_fetch_items = [item for item in selected_items if item_key(item) not in updated_keys]
                updated_prepared = (
                    [
                        PreparedNotice(source=source, notice_id=notice_id, detail=detail)
                        for notice_id, detail in self.storage.load_updated_seen_details(selected_updated_items)
                    ]
                    if selected_updated_items and not options.dry_run
                    else []
                )
                updated_count += len(updated_prepared)

                prepared_notices = fetch_details_for_items(
                    source=source,
                    adapter=adapter,
                    items=selected_fetch_items,
                    dry_run=options.dry_run,
                    failures=failures,
                    storage=self.storage,
                    http_client=self.http_client,
                    detail_min_chars=self.config.detail_min_chars,
                    max_workers=detail_worker_count,
                    retry_policy=failure_retry_policy,
                )
                prepared_notices = updated_prepared + prepared_notices

                if prepared_notices:
                    self._summarize_notices(
                        prepared_notices,
                        entries,
                        failures,
                        max_workers=summary_worker_count,
                        retry_policy=failure_retry_policy,
                    )

                if not options.dry_run and seen_rows:
                    selected_urls = {item.canonical_url for item in selected_items}
                    seen_items = [
                        item
                        for item in processable_list_items
                        if item.canonical_url in seen_rows and item.canonical_url not in selected_urls
                    ]
                    if active_refresh_seen_details:
                        if active_refresh_seen_limit > 0:
                            seen_items = seen_items[:active_refresh_seen_limit]
                        refreshed_prepared, refresh_errors = update_seen_details_if_changed(
                            source=source,
                            adapter=adapter,
                            items=seen_items,
                            seen_rows=seen_rows,
                            http_client=self.http_client,
                            storage=self.storage,
                            detail_min_chars=self.config.detail_min_chars,
                            max_workers=active_refresh_seen_workers,
                        )
                        refresh_seen_errors.extend(refresh_errors)
                        updated_count += len(refreshed_prepared)
                        if refreshed_prepared:
                            self._summarize_notices(
                                refreshed_prepared,
                                entries,
                                failures,
                                max_workers=summary_worker_count,
                                retry_policy=failure_retry_policy,
                            )

                if not options.dry_run and options.limit is not None and processed_for_source >= options.limit:
                    break
                if stop_after_seen is not None and seen_only_pages >= stop_after_seen:
                    break
                if page_before_cutoff:
                    break

                page_url = adapter.find_next_page_url(list_html, page_url)
                pages_scanned += 1

        report_path = None
        if not options.dry_run and (entries or failures):
            stats = ReportStats(
                new_count=new_count,
                retried_count=retried_count,
                summarized_count=len(entries),
                manual_review_count=len(failures),
                updated_count=updated_count,
            )
            markdown = render_report(report_day, entries, failures, stats)
            report_path = write_report(self.config.output_dir, report_day, markdown)

        finished_at = utc_now()
        result = PipelineResult(
            report_path=report_path,
            new_count=new_count,
            updated_count=updated_count,
            summarized_count=len(entries),
            retried_count=retried_count,
            manual_review_count=len(failures),
            failed=tuple(failures),
            source_errors=tuple(source_errors),
            audit_results=audit_results,
            refresh_seen_errors=tuple(refresh_seen_errors),
            source_stats=source_stats(
                selected_sources,
                entries,
                failures,
                source_errors,
                audit_results,
                refresh_seen_errors,
            ),
            models_used=models_used(entries),
            media_counts=media_counts(entries),
            started_at=started_at,
            finished_at=finished_at,
            duration_seconds=round(perf_counter() - started_perf, 3),
            git_sha=options.git_sha,
        )
        if not options.dry_run:
            run_summary_path = write_run_summary(self.config.output_dir, report_day, result)
            result = replace(result, run_summary_path=run_summary_path)
            self.storage.checkpoint()
        return result

    def _summarize_notices(
        self,
        prepared_notices: list[PreparedNotice],
        entries: list[ReportEntry],
        failures: list[FailedNotice],
        max_workers: Optional[int] = None,
        retry_policy: FailureRetryPolicy = FailureRetryPolicy(),
    ) -> None:
        default_workers = self.config.runtime_profile("daily").summary_max_workers
        max_workers = min(max(1, max_workers or default_workers), len(prepared_notices))
        outcomes: dict[int, object] = {}

        with ThreadPoolExecutor(max_workers=max_workers) as executor:
            future_to_index = {
                executor.submit(
                    self.summarizer.summarize,
                    prepared.notice_id,
                    prepared.detail,
                    source_name=prepared.source.name,
                ): index
                for index, prepared in enumerate(prepared_notices)
            }
            for future in as_completed(future_to_index):
                index = future_to_index[future]
                try:
                    outcomes[index] = future.result()
                except Exception as exc:
                    outcomes[index] = exc

        for index, prepared in enumerate(prepared_notices):
            outcome = outcomes[index]
            if isinstance(outcome, Exception):
                failure_type = classify_failure(outcome, stage="summary")
                failure = FailedNotice(
                    source_id=prepared.source.id,
                    source_name=prepared.source.name,
                    title=prepared.detail.title,
                    url=prepared.detail.url,
                    reason=str(outcome),
                    published_at=prepared.detail.published_at,
                    failure_type=failure_type,
                )
                failures.append(failure)
                self.storage.mark_failed(
                    prepared.notice_id,
                    str(outcome),
                    failure_type=failure_type,
                    retry_after_hours=retry_policy.after_hours,
                    retry_limit=retry_limit_for_failure(failure_type, retry_policy.limit),
                )
                continue

            self.storage.save_summary(prepared.notice_id, outcome)
            entries.append(
                ReportEntry(
                    source_id=prepared.source.id,
                    source_name=prepared.source.name,
                    detail=prepared.detail,
                    summary=outcome,
                )
            )

    def _select_sources(self, source_ids: Optional[Iterable[str]]) -> list[NoticeSource]:
        if source_ids:
            requested = set(source_ids)
            selected = [source for source in self.config.sources if source.id in requested]
            found = {source.id for source in selected}
            missing = sorted(requested - found)
            if missing:
                available = ", ".join(source.id for source in self.config.sources)
                raise ValueError(f"Unknown source id(s): {', '.join(missing)}. Available sources: {available}")
            return selected
        return [source for source in self.config.sources if source.enabled]


def create_adapter(source: NoticeSource, detail_parser=None):
    adapter_path = source.adapter
    module_name, _, class_name = adapter_path.rpartition(".")
    if not module_name or not class_name:
        raise ValueError(
            f"Adapter for source '{source.id}' must be an import path like "
            f"'package.module.AdapterClass', got: {source.adapter}"
        )
    module = import_module(module_name)
    adapter_class = getattr(module, class_name)
    return adapter_class(source, detail_parser=detail_parser)




