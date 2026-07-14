from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import dataclass

from notice_push.crawler.detail_fetcher import PreparedNotice, fetch_details_for_items
from notice_push.crawler.failures import FailureRetryPolicy, classify_failure, retry_limit_for_failure
from notice_push.crawler.list_scanner import item_key
from notice_push.crawler.refresh_seen import update_seen_details_if_changed
from notice_push.crawler.source_scan import ScannedListPage
from notice_push.domain import FailedNotice, NoticeSource, PipelineRunOptions, RefreshSeenError
from notice_push.reporting.markdown import ReportEntry
from notice_push.storage.selection import PipelineItemSelection


@dataclass(frozen=True)
class SummaryOutcome:
    entries: tuple[ReportEntry, ...] = ()
    failures: tuple[FailedNotice, ...] = ()


@dataclass(frozen=True)
class ProcessingOutcome:
    entries: tuple[ReportEntry, ...] = ()
    failures: tuple[FailedNotice, ...] = ()
    refresh_seen_errors: tuple[RefreshSeenError, ...] = ()
    new_count: int = 0
    retried_count: int = 0
    updated_count: int = 0
    processed_count: int = 0
    had_candidates: bool = False


class NoticeProcessor:
    def __init__(self, *, storage, http_client, summarizer, detail_min_chars: int):
        self.storage = storage
        self.http_client = http_client
        self.summarizer = summarizer
        self.detail_min_chars = detail_min_chars

    def process_page(
        self,
        *,
        source: NoticeSource,
        adapter,
        page: ScannedListPage,
        options: PipelineRunOptions,
        retry_policy: FailureRetryPolicy,
        remaining_capacity: int | None,
    ) -> ProcessingOutcome:
        items = page.processable_items
        if options.bootstrap_seen:
            if not options.dry_run:
                self.storage.mark_seen_baseline(items)
            return ProcessingOutcome()

        selection = self._select_items(items, options, retry_policy)
        categories = _selection_categories(selection)
        candidate_items = tuple(item for item in items if item_key(item) in categories)
        if remaining_capacity == 0:
            return ProcessingOutcome(had_candidates=bool(candidate_items))
        selected_items = (
            candidate_items
            if remaining_capacity is None
            else candidate_items[:remaining_capacity]
        )
        selected_keys = {item_key(item) for item in selected_items}
        selected_updated = tuple(
            updated
            for updated in selection.updated_seen
            if item_key(updated.item) in selected_keys
        )
        updated_keys = {item_key(updated.item) for updated in selected_updated}
        selected_fetch_items = tuple(
            item for item in selected_items if item_key(item) not in updated_keys
        )

        failures: list[FailedNotice] = []
        prepared = [
            PreparedNotice(source=source, notice_id=updated.notice_id, detail=updated.detail)
            for updated in selected_updated
        ]
        prepared.extend(
            fetch_details_for_items(
                source=source,
                adapter=adapter,
                items=selected_fetch_items,
                dry_run=options.dry_run,
                failures=failures,
                storage=self.storage,
                http_client=self.http_client,
                detail_min_chars=self.detail_min_chars,
                max_workers=options.detail_max_workers,
                retry_policy=retry_policy,
            )
        )
        summary = self.summarize(
            tuple(prepared),
            max_workers=options.summary_max_workers,
            retry_policy=retry_policy,
        )
        failures.extend(summary.failures)

        refresh_entries: tuple[ReportEntry, ...] = ()
        refresh_failures: tuple[FailedNotice, ...] = ()
        refresh_errors: tuple[RefreshSeenError, ...] = ()
        refreshed_count = 0
        if not options.dry_run and options.refresh_seen_details and selection.seen_rows:
            seen_items = [
                item
                for item in items
                if (item.source_id, item.canonical_url) in selection.seen_rows
                and item_key(item) not in selected_keys
            ]
            if options.refresh_seen_limit > 0:
                seen_items = seen_items[: options.refresh_seen_limit]
            refreshed, errors = update_seen_details_if_changed(
                source=source,
                adapter=adapter,
                items=seen_items,
                seen_rows=dict(selection.seen_rows),
                http_client=self.http_client,
                storage=self.storage,
                detail_min_chars=self.detail_min_chars,
                max_workers=options.refresh_seen_max_workers,
            )
            refresh_errors = tuple(errors)
            refreshed_count = len(refreshed)
            refreshed_summary = self.summarize(
                tuple(refreshed),
                max_workers=options.summary_max_workers,
                retry_policy=retry_policy,
            )
            refresh_entries = refreshed_summary.entries
            refresh_failures = refreshed_summary.failures

        new_keys = {item_key(item) for item in selection.new_items}
        retry_keys = {item_key(item) for item in selection.retry_items}
        return ProcessingOutcome(
            entries=summary.entries + refresh_entries,
            failures=tuple(failures) + refresh_failures,
            refresh_seen_errors=refresh_errors,
            new_count=sum(1 for item in selected_items if item_key(item) in new_keys),
            retried_count=sum(1 for item in selected_items if item_key(item) in retry_keys),
            updated_count=len(selected_updated) + refreshed_count,
            processed_count=len(selected_items),
            had_candidates=bool(candidate_items),
        )

    def summarize(
        self,
        prepared_notices: tuple[PreparedNotice, ...],
        *,
        max_workers: int,
        retry_policy: FailureRetryPolicy,
    ) -> SummaryOutcome:
        if not prepared_notices:
            return SummaryOutcome()
        worker_count = min(max(1, max_workers), len(prepared_notices))
        outcomes: dict[int, object] = {}
        with ThreadPoolExecutor(max_workers=worker_count) as executor:
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

        entries: list[ReportEntry] = []
        failures: list[FailedNotice] = []
        for index, prepared in enumerate(prepared_notices):
            outcome = outcomes[index]
            if isinstance(outcome, Exception):
                failure_type = classify_failure(outcome, stage="summary")
                failures.append(
                    FailedNotice(
                        source_id=prepared.source.id,
                        source_name=prepared.source.name,
                        title=prepared.detail.title,
                        url=prepared.detail.url,
                        reason=str(outcome),
                        published_at=prepared.detail.published_at,
                        failure_type=failure_type,
                    )
                )
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
        return SummaryOutcome(entries=tuple(entries), failures=tuple(failures))

    def _select_items(
        self,
        items,
        options: PipelineRunOptions,
        retry_policy: FailureRetryPolicy,
    ) -> PipelineItemSelection:
        if options.dry_run:
            return PipelineItemSelection(tuple(items), (), (), {})
        return self.storage.classify_pipeline_items(
            items,
            retry_failed=options.retry_failed,
            retry_policy=retry_policy,
        )


def _selection_categories(selection: PipelineItemSelection) -> dict[tuple[str, str], str]:
    categories = {item_key(item): "new" for item in selection.new_items}
    categories.update((item_key(item), "retry") for item in selection.retry_items)
    categories.update((item_key(item.item), "updated") for item in selection.updated_seen)
    return categories
