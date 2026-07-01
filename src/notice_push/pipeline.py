from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import dataclass
from datetime import date, datetime, time, timedelta
from importlib import import_module
from typing import Callable, Iterable, Optional

from src.notice_push.config import AppConfig
from src.notice_push.http import HttpClient
from src.notice_push.models import FailedNotice, NoticeDetail, NoticeListItem, NoticeSource, PipelineResult, SourceError
from src.notice_push.report import ReportEntry, render_report, write_report
from src.notice_push.storage import NoticeStorage


AdapterFactory = Callable[[NoticeSource], object]
LEGACY_ADAPTER_ALIASES = {
    "shu_official": "src.notice_push.sources.shu_official.ShuOfficialAdapter",
    "management_school": "src.notice_push.sources.management_school.ManagementSchoolAdapter",
    "graduate_school": "src.notice_push.sources.graduate_school.GraduateSchoolAdapter",
}
UNBOUNDED_PAGE_SCAN = float("inf")
UNSET = object()


@dataclass(frozen=True)
class PreparedNotice:
    source: NoticeSource
    notice_id: int
    detail: NoticeDetail


@dataclass(frozen=True)
class FailureRetryPolicy:
    limit: int = 0
    after_hours: int = 0


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
        source_ids: Optional[Iterable[str]] = None,
        dry_run: bool = False,
        limit: Optional[int] = None,
        report_date: Optional[date] = None,
        max_pages_per_source: Optional[int] | object = UNSET,
        stop_after_seen_pages: Optional[int] | object = UNSET,
        detail_max_workers: Optional[int] | object = UNSET,
        summary_max_workers: Optional[int] | object = UNSET,
        lookback_days: Optional[int] | object = UNSET,
        retry_failed: bool | object = UNSET,
        failed_retry_limit: int | object = UNSET,
        failed_retry_after_hours: int | object = UNSET,
        refresh_seen_details: bool | object = UNSET,
        refresh_seen_max_workers: Optional[int] | object = UNSET,
        refresh_seen_limit: int | object = UNSET,
        bootstrap_seen: bool = False,
    ) -> PipelineResult:
        selected_sources = self._select_sources(source_ids)
        default_profile = self.config.runtime_profile("daily")
        max_pages = default_profile.max_pages_per_source if max_pages_per_source is UNSET else max_pages_per_source
        stop_after_seen = (
            default_profile.stop_after_seen_pages if stop_after_seen_pages is UNSET else stop_after_seen_pages
        )
        detail_worker_count = (
            default_profile.detail_max_workers if detail_max_workers is UNSET else detail_max_workers
        )
        summary_worker_count = (
            default_profile.summary_max_workers if summary_max_workers is UNSET else summary_max_workers
        )
        active_lookback_days = default_profile.lookback_days if lookback_days is UNSET else lookback_days
        active_retry_failed = default_profile.retry_failed if retry_failed is UNSET else retry_failed
        active_failed_retry_limit = (
            default_profile.failed_retry_limit if failed_retry_limit is UNSET else failed_retry_limit
        )
        active_failed_retry_after_hours = (
            default_profile.failed_retry_after_hours
            if failed_retry_after_hours is UNSET
            else failed_retry_after_hours
        )
        active_refresh_seen_details = (
            default_profile.refresh_seen_details if refresh_seen_details is UNSET else refresh_seen_details
        )
        active_refresh_seen_workers = (
            default_profile.refresh_seen_max_workers
            if refresh_seen_max_workers is UNSET
            else refresh_seen_max_workers
        )
        active_refresh_seen_limit = (
            default_profile.refresh_seen_limit if refresh_seen_limit is UNSET else refresh_seen_limit
        )
        if max_pages is None:
            max_pages = UNBOUNDED_PAGE_SCAN
        report_day = report_date or date.today()
        cutoff = _cutoff_datetime(report_day, active_lookback_days)
        failure_retry_policy = FailureRetryPolicy(
            limit=active_failed_retry_limit,
            after_hours=active_failed_retry_after_hours,
        )

        entries: list[ReportEntry] = []
        failures: list[FailedNotice] = []
        source_errors: list[SourceError] = []
        new_count = 0

        if not dry_run:
            self.storage.initialize()
            self.storage.migrate_legacy_csv(self.config.repo_root / "resources" / "notice_records.csv")

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

                if bootstrap_seen:
                    if not dry_run:
                        self.storage.mark_seen_baseline(processable_list_items)
                    if page_is_before_cutoff:
                        break
                    page_url = adapter.find_next_page_url(list_html, page_url)
                    pages_scanned += 1
                    continue

                seen_rows = {} if dry_run else self.storage.find_seen_items(processable_list_items)
                candidate_items = (
                    processable_list_items
                    if dry_run
                    else self.storage.filter_processable_items(
                        processable_list_items,
                        retry_failed=active_retry_failed,
                        failed_retry_limit=active_failed_retry_limit,
                    )
                )
                if candidate_items:
                    seen_only_pages = 0
                else:
                    seen_only_pages += 1

                remaining_capacity = None if limit is None else max(0, limit - processed_for_source)
                if remaining_capacity == 0:
                    break

                selected_items = candidate_items if remaining_capacity is None else candidate_items[:remaining_capacity]
                processed_for_source += len(selected_items)
                new_count += len(selected_items)

                prepared_notices = self._fetch_details_for_items(
                    source=source,
                    adapter=adapter,
                    items=selected_items,
                    dry_run=dry_run,
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

                if not dry_run and seen_rows:
                    selected_urls = {item.canonical_url for item in selected_items}
                    seen_items = [
                        item
                        for item in processable_list_items
                        if item.canonical_url in seen_rows and item.canonical_url not in selected_urls
                    ]
                    if active_refresh_seen_details:
                        if active_refresh_seen_limit > 0:
                            seen_items = seen_items[:active_refresh_seen_limit]
                        self._update_seen_details_if_changed(
                            adapter,
                            seen_items,
                            seen_rows,
                            max_workers=active_refresh_seen_workers,
                        )

                if not dry_run and limit is not None and processed_for_source >= limit:
                    break
                if stop_after_seen is not None and seen_only_pages >= stop_after_seen:
                    break
                if page_is_before_cutoff:
                    break

                page_url = adapter.find_next_page_url(list_html, page_url)
                pages_scanned += 1

        report_path = None
        if not dry_run and (entries or failures):
            markdown = render_report(report_day, entries, failures)
            report_path = write_report(self.config.output_dir, report_day, markdown)

        return PipelineResult(
            report_path=report_path,
            new_count=new_count,
            summarized_count=len(entries),
            failed=tuple(failures),
            source_errors=tuple(source_errors),
        )

    def _fetch_and_store_detail(
        self,
        source: NoticeSource,
        adapter,
        item: NoticeListItem,
        dry_run: bool,
        failures: list[FailedNotice],
        retry_policy: FailureRetryPolicy,
    ) -> Optional[PreparedNotice]:
        notice_id = None
        if not dry_run:
            notice_id = self.storage.upsert_seen_item(item)

        try:
            detail_html = self.http_client.get_text(item.url)
            detail: NoticeDetail = adapter.parse_detail(detail_html, item)
            if len(detail.content.strip()) < self.config.detail_min_chars:
                raise ValueError("detail content is empty or too short")

            if dry_run:
                return None

            assert notice_id is not None
            self.storage.save_detail(notice_id, detail)
            return PreparedNotice(source=source, notice_id=notice_id, detail=detail)
        except Exception as exc:
            failure = FailedNotice(
                source_id=source.id,
                source_name=source.name,
                title=item.title,
                url=item.url,
                reason=str(exc),
                published_at=item.published_at,
            )
            failures.append(failure)
            if not dry_run and notice_id is not None:
                self.storage.mark_failed(
                    notice_id,
                    str(exc),
                    failure_type=_classify_failure(exc, stage="detail"),
                    retry_after_hours=retry_policy.after_hours,
                    retry_limit=retry_policy.limit,
                )
            return None

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
        outcomes: dict[int, Optional[PreparedNotice]] = {}

        with ThreadPoolExecutor(max_workers=worker_count) as executor:
            future_to_index = {
                executor.submit(
                    self._fetch_and_store_detail,
                    source,
                    adapter,
                    item,
                    dry_run,
                    failures,
                    retry_policy,
                ): index
                for index, item in enumerate(items)
            }
            for future in as_completed(future_to_index):
                index = future_to_index[future]
                outcomes[index] = future.result()

        return [outcomes[index] for index in range(len(items)) if outcomes[index] is not None]

    def _update_seen_details_if_changed(
        self,
        adapter,
        items: list[NoticeListItem],
        seen_rows: dict[str, object],
        max_workers: Optional[int] = None,
    ) -> None:
        if not items:
            return

        worker_count = min(max(1, max_workers or 1), len(items))

        def update_one(item: NoticeListItem) -> None:
            try:
                detail_html = self.http_client.get_text(item.url)
                detail = adapter.parse_detail(detail_html, item)
                if len(detail.content.strip()) < self.config.detail_min_chars:
                    return
                notice_id = int(seen_rows[item.canonical_url]["id"])
                self.storage.update_seen_detail_if_changed(notice_id, detail)
            except Exception:
                return

        with ThreadPoolExecutor(max_workers=worker_count) as executor:
            list(executor.map(update_one, items))

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
                failure = FailedNotice(
                    source_id=prepared.source.id,
                    source_name=prepared.source.name,
                    title=prepared.detail.title,
                    url=prepared.detail.url,
                    reason=str(outcome),
                    published_at=prepared.detail.published_at,
                )
                failures.append(failure)
                self.storage.mark_failed(
                    prepared.notice_id,
                    str(outcome),
                    failure_type=_classify_failure(outcome, stage="summary"),
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


def create_adapter(source: NoticeSource):
    adapter_path = LEGACY_ADAPTER_ALIASES.get(source.adapter, source.adapter)
    module_name, _, class_name = adapter_path.rpartition(".")
    if not module_name or not class_name:
        raise ValueError(
            f"Adapter for source '{source.id}' must be an import path like "
            f"'package.module.AdapterClass', got: {source.adapter}"
        )
    module = import_module(module_name)
    adapter_class = getattr(module, class_name)
    return adapter_class(source)


def _cutoff_datetime(report_day: date, lookback_days: Optional[int]) -> Optional[datetime]:
    if lookback_days is None or lookback_days <= 0:
        return None
    return datetime.combine(report_day, time.min) - timedelta(days=lookback_days)


def _items_within_lookback(items: list[NoticeListItem], cutoff: Optional[datetime]) -> list[NoticeListItem]:
    if cutoff is None:
        return items
    return [item for item in items if item.published_at is None or item.published_at >= cutoff]


def _page_is_before_cutoff(items: list[NoticeListItem], cutoff: Optional[datetime]) -> bool:
    if cutoff is None or not items:
        return False
    dated_items = [item for item in items if item.published_at is not None]
    return bool(dated_items) and all(item.published_at < cutoff for item in dated_items)


def _classify_failure(exc: Exception, *, stage: str = "") -> str:
    message = str(exc).lower()
    if "empty or too short" in message:
        return "detail_empty"
    if "timeout" in message:
        return f"{stage}_timeout" if stage else "timeout"
    if "rate" in message or "429" in message:
        return "llm_rate_limit"
    failure_name = type(exc).__name__
    return f"{stage}_{failure_name}" if stage else failure_name
