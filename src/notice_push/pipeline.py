from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import dataclass
from datetime import date
from importlib import import_module
from typing import Callable, Iterable, Optional

from src.notice_push.config import AppConfig
from src.notice_push.http import HttpClient
from src.notice_push.models import FailedNotice, NoticeDetail, NoticeListItem, NoticeSource, PipelineResult, SourceError
from src.notice_push.report import ReportEntry, render_report, write_report
from src.notice_push.storage import NoticeStorage


AdapterFactory = Callable[[NoticeSource], object]
ADAPTER_ALIASES = {
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
        detail_max_workers: Optional[int] = None,
        summary_max_workers: Optional[int] = None,
        bootstrap_seen: bool = False,
    ) -> PipelineResult:
        selected_sources = self._select_sources(source_ids)
        max_pages = self.config.max_pages_per_source if max_pages_per_source is UNSET else max_pages_per_source
        stop_after_seen = self.config.stop_after_seen_pages if stop_after_seen_pages is UNSET else stop_after_seen_pages
        if max_pages is None:
            max_pages = UNBOUNDED_PAGE_SCAN
        report_day = report_date or date.today()

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

            while page_url and pages_scanned < max_pages:
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

                if bootstrap_seen:
                    if not dry_run:
                        self.storage.mark_seen_baseline(list_items)
                    page_url = adapter.find_next_page_url(list_html, page_url)
                    pages_scanned += 1
                    continue

                seen_rows = {} if dry_run else self.storage.find_seen_items(list_items)
                candidate_items = list_items if dry_run else self.storage.filter_new_items(list_items)
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
                    max_workers=detail_max_workers,
                )

                if prepared_notices:
                    self._summarize_notices(prepared_notices, entries, failures, max_workers=summary_max_workers)

                if not dry_run and seen_rows:
                    seen_items = [item for item in list_items if item.canonical_url in seen_rows]
                    self._update_seen_details_if_changed(adapter, seen_items, seen_rows)

                if not dry_run and limit is not None and processed_for_source >= limit:
                    break
                if stop_after_seen is not None and seen_only_pages >= stop_after_seen:
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
                self.storage.mark_failed(notice_id, str(exc))
            return None

    def _fetch_details_for_items(
        self,
        source: NoticeSource,
        adapter,
        items: list[NoticeListItem],
        dry_run: bool,
        failures: list[FailedNotice],
        max_workers: Optional[int] = None,
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
    ) -> None:
        for item in items:
            try:
                detail_html = self.http_client.get_text(item.url)
                detail = adapter.parse_detail(detail_html, item)
                if len(detail.content.strip()) < self.config.detail_min_chars:
                    continue
                notice_id = int(seen_rows[item.canonical_url]["id"])
                self.storage.update_seen_detail_if_changed(notice_id, detail)
            except Exception:
                continue

    def _summarize_notices(
        self,
        prepared_notices: list[PreparedNotice],
        entries: list[ReportEntry],
        failures: list[FailedNotice],
        max_workers: Optional[int] = None,
    ) -> None:
        max_workers = min(max(1, max_workers or self.config.summary_max_workers), len(prepared_notices))
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
                self.storage.mark_failed(prepared.notice_id, str(outcome))
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
            return [source for source in self.config.sources if source.id in requested]
        return [source for source in self.config.sources if source.enabled]


def create_adapter(source: NoticeSource):
    adapter_path = ADAPTER_ALIASES.get(source.adapter, source.adapter)
    module_name, _, class_name = adapter_path.rpartition(".")
    if not module_name or not class_name:
        raise ValueError(
            f"Adapter for source '{source.id}' must be an import path like "
            f"'package.module.AdapterClass', got: {source.adapter}"
        )
    module = import_module(module_name)
    adapter_class = getattr(module, class_name)
    return adapter_class(source)
