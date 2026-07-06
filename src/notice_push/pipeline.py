from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import dataclass, replace
from datetime import date, datetime, time, timedelta, timezone
from importlib import import_module
from time import perf_counter
from typing import Callable, Iterable, Optional

from src.notice_push.config import AppConfig
from src.notice_push.http import HttpClient
from src.notice_push.models import (
    FailedNotice,
    NoticeDetail,
    NoticeListItem,
    NoticeSource,
    PipelineResult,
    PipelineRunOptions,
    PipelineSourceStats,
    RefreshSeenError,
    ReportStats,
    SourceError,
)
from src.notice_push.report import ReportEntry, render_report, write_report
from src.notice_push.run_summary import write_run_summary
from src.notice_push.source_audit import SourceAuditor
from src.notice_push.storage import NoticeStorage


AdapterFactory = Callable[[NoticeSource], object]
UNBOUNDED_PAGE_SCAN = float("inf")
SUPPORTED_ASSET_KINDS = {"pdf", "image"}
SUPPORTED_ASSET_ROLES = {"primary", "attachment"}


@dataclass(frozen=True)
class PreparedNotice:
    source: NoticeSource
    notice_id: int
    detail: NoticeDetail


@dataclass(frozen=True)
class DetailFetchResult:
    prepared: Optional[PreparedNotice] = None
    failure: Optional[FailedNotice] = None


@dataclass(frozen=True)
class FailureRetryPolicy:
    limit: int = 0
    after_hours: int = 0


class UnsupportedContentError(ValueError):
    pass


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
        started_at = _utc_now()
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
        cutoff = _cutoff_datetime(report_day, active_lookback_days)
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

                processable_list_items = _items_within_lookback(list_items, cutoff)
                page_is_before_cutoff = _page_is_before_cutoff(list_items, cutoff)

                if options.bootstrap_seen:
                    if not options.dry_run:
                        self.storage.mark_seen_baseline(processable_list_items)
                    if page_is_before_cutoff:
                        break
                    page_url = adapter.find_next_page_url(list_html, page_url)
                    pages_scanned += 1
                    continue

                seen_rows = {} if options.dry_run else self.storage.find_seen_items(processable_list_items)
                if options.dry_run:
                    new_items = processable_list_items
                    retry_items: list[NoticeListItem] = []
                else:
                    new_items, retry_items = self.storage.split_processable_items(
                        processable_list_items,
                        retry_failed=active_retry_failed,
                        failed_retry_limit=active_failed_retry_limit,
                    )
                new_keys = {_item_key(item) for item in new_items}
                retry_keys = {_item_key(item) for item in retry_items}
                processable_keys = new_keys | retry_keys
                candidate_items = [item for item in processable_list_items if _item_key(item) in processable_keys]
                if candidate_items:
                    seen_only_pages = 0
                else:
                    seen_only_pages += 1

                remaining_capacity = None if options.limit is None else max(0, options.limit - processed_for_source)
                if remaining_capacity == 0:
                    break

                selected_items = candidate_items if remaining_capacity is None else candidate_items[:remaining_capacity]
                processed_for_source += len(selected_items)
                new_count += sum(1 for item in selected_items if _item_key(item) in new_keys)
                retried_count += sum(1 for item in selected_items if _item_key(item) in retry_keys)

                prepared_notices = self._fetch_details_for_items(
                    source=source,
                    adapter=adapter,
                    items=selected_items,
                    dry_run=options.dry_run,
                    failures=failures,
                    max_workers=detail_worker_count,
                    retry_policy=failure_retry_policy,
                )

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
                        refresh_seen_errors.extend(
                            self._update_seen_details_if_changed(
                                source,
                                adapter,
                                seen_items,
                                seen_rows,
                                max_workers=active_refresh_seen_workers,
                            )
                        )

                if not options.dry_run and options.limit is not None and processed_for_source >= options.limit:
                    break
                if stop_after_seen is not None and seen_only_pages >= stop_after_seen:
                    break
                if page_is_before_cutoff:
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
            )
            markdown = render_report(report_day, entries, failures, stats)
            report_path = write_report(self.config.output_dir, report_day, markdown)

        finished_at = _utc_now()
        result = PipelineResult(
            report_path=report_path,
            new_count=new_count,
            summarized_count=len(entries),
            retried_count=retried_count,
            manual_review_count=len(failures),
            failed=tuple(failures),
            source_errors=tuple(source_errors),
            audit_results=audit_results,
            refresh_seen_errors=tuple(refresh_seen_errors),
            source_stats=_source_stats(
                selected_sources,
                entries,
                failures,
                source_errors,
                audit_results,
                refresh_seen_errors,
            ),
            models_used=_models_used(entries),
            media_counts=_media_counts(entries),
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

    def _fetch_and_store_detail(
        self,
        source: NoticeSource,
        adapter,
        item: NoticeListItem,
        dry_run: bool,
        retry_policy: FailureRetryPolicy,
    ) -> DetailFetchResult:
        notice_id = None
        if not dry_run:
            notice_id = self.storage.upsert_seen_item(item)

        try:
            detail_html = self.http_client.get_text(item.url)
            detail: NoticeDetail = adapter.parse_detail(detail_html, item)
            if not is_summarizable_detail(detail, self.config.detail_min_chars):
                if detail.content_kind in {"video", "external_video"}:
                    raise UnsupportedContentError("unsupported video content")
                raise ValueError("detail content is empty or too short")

            if dry_run:
                return DetailFetchResult()

            assert notice_id is not None
            self.storage.save_detail(notice_id, detail)
            return DetailFetchResult(prepared=PreparedNotice(source=source, notice_id=notice_id, detail=detail))
        except Exception as exc:
            failure_type = _classify_failure(exc, stage="detail")
            failure = FailedNotice(
                source_id=source.id,
                source_name=source.name,
                title=item.title,
                url=item.url,
                reason=str(exc),
                published_at=item.published_at,
                failure_type=failure_type,
            )
            if not dry_run and notice_id is not None:
                self.storage.mark_failed(
                    notice_id,
                    str(exc),
                    failure_type=failure_type,
                    retry_after_hours=retry_policy.after_hours,
                    retry_limit=retry_policy.limit,
                )
            return DetailFetchResult(failure=failure)

    def _fetch_details_for_items(
        self,
        source: NoticeSource,
        adapter,
        items: list[NoticeListItem],
        dry_run: bool,
        failures: list[FailedNotice],
        max_workers: Optional[int] = None,
        retry_policy: FailureRetryPolicy = FailureRetryPolicy(),
    ) -> list[PreparedNotice]:
        if not items:
            return []

        worker_count = min(max(1, max_workers or 1), len(items))
        outcomes: dict[int, DetailFetchResult] = {}

        with ThreadPoolExecutor(max_workers=worker_count) as executor:
            future_to_index = {
                executor.submit(
                    self._fetch_and_store_detail,
                    source,
                    adapter,
                    item,
                    dry_run,
                    retry_policy,
                ): index
                for index, item in enumerate(items)
            }
            for future in as_completed(future_to_index):
                index = future_to_index[future]
                outcomes[index] = future.result()

        prepared_notices: list[PreparedNotice] = []
        for index in range(len(items)):
            outcome = outcomes[index]
            if outcome.failure is not None:
                failures.append(outcome.failure)
            if outcome.prepared is not None:
                prepared_notices.append(outcome.prepared)
        return prepared_notices

    def _update_seen_details_if_changed(
        self,
        source: NoticeSource,
        adapter,
        items: list[NoticeListItem],
        seen_rows: dict[str, object],
        max_workers: Optional[int] = None,
    ) -> list[RefreshSeenError]:
        if not items:
            return []

        worker_count = min(max(1, max_workers or 1), len(items))

        def update_one(item: NoticeListItem) -> RefreshSeenError | None:
            try:
                detail_html = self.http_client.get_text(item.url)
                detail = adapter.parse_detail(detail_html, item)
                if not is_summarizable_detail(detail, self.config.detail_min_chars):
                    return None
                notice_id = int(seen_rows[item.canonical_url]["id"])
                self.storage.update_seen_detail_if_changed(notice_id, detail)
                return None
            except Exception as exc:
                return RefreshSeenError(
                    source_id=source.id,
                    source_name=source.name,
                    title=item.title,
                    url=item.url,
                    reason=str(exc),
                )

        with ThreadPoolExecutor(max_workers=worker_count) as executor:
            results = list(executor.map(update_one, items))
        return [error for error in results if error is not None]

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
                failure_type = _classify_failure(outcome, stage="summary")
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
                    retry_limit=retry_policy.limit,
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


def _source_stats(
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


def _models_used(entries: list[ReportEntry]) -> tuple[str, ...]:
    return tuple(sorted({entry.summary.model for entry in entries if entry.summary.model}))


def _media_counts(entries: list[ReportEntry]) -> dict[str, int]:
    counts = {"pdf": 0, "image": 0, "video": 0}
    for entry in entries:
        content_kind = entry.detail.content_kind
        if content_kind in counts:
            counts[content_kind] += 1
    return {key: value for key, value in counts.items() if value}


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


def _cutoff_datetime(report_day: date, lookback_days: Optional[int]) -> Optional[datetime]:
    if lookback_days is None or lookback_days <= 0:
        return None
    return datetime.combine(report_day, time.min) - timedelta(days=lookback_days)


def _utc_now() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat()


def _items_within_lookback(items: list[NoticeListItem], cutoff: Optional[datetime]) -> list[NoticeListItem]:
    if cutoff is None:
        return items
    return [item for item in items if item.published_at is None or item.published_at >= cutoff]


def _item_key(item: NoticeListItem) -> tuple[str, str]:
    return item.source_id, item.canonical_url


def _page_is_before_cutoff(items: list[NoticeListItem], cutoff: Optional[datetime]) -> bool:
    if cutoff is None or not items:
        return False
    dated_items = [item for item in items if item.published_at is not None]
    return bool(dated_items) and all(item.published_at < cutoff for item in dated_items)


def is_summarizable_detail(detail: NoticeDetail, min_chars: int) -> bool:
    if len(detail.content.strip()) >= min_chars:
        return True
    return any(
        asset.kind in SUPPORTED_ASSET_KINDS and asset.role in SUPPORTED_ASSET_ROLES
        for asset in detail.assets
    )


def _classify_failure(exc: Exception, *, stage: str = "") -> str:
    message = str(exc).lower()
    if isinstance(exc, UnsupportedContentError) or "unsupported video content" in message:
        return "unsupported_video_content"
    if "empty or too short" in message:
        return "detail_empty"
    if "timeout" in message:
        return f"{stage}_timeout" if stage else "timeout"
    if "rate" in message or "429" in message:
        return "llm_rate_limit"
    failure_name = type(exc).__name__
    return f"{stage}_{failure_name}" if stage else failure_name
