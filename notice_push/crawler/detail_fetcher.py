from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import dataclass
from typing import Optional

from notice_push.crawler.failures import FailureRetryPolicy, UnsupportedContentError, classify_failure
from notice_push.domain import FailedNotice, NoticeDetail, NoticeSource


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


def is_summarizable_detail(detail: NoticeDetail, min_chars: int) -> bool:
    if len(detail.content.strip()) >= min_chars:
        return True
    return any(
        asset.kind in SUPPORTED_ASSET_KINDS and asset.role in SUPPORTED_ASSET_ROLES
        for asset in detail.assets
    )


def fetch_and_store_detail(
    *,
    source: NoticeSource,
    adapter,
    item,
    dry_run: bool,
    retry_policy: FailureRetryPolicy,
    storage,
    http_client,
    detail_min_chars: int,
) -> DetailFetchResult:
    notice_id = None
    if not dry_run:
        notice_id = storage.upsert_seen_item(item)

    try:
        detail_html = http_client.get_text(item.url)
        detail: NoticeDetail = adapter.parse_detail(detail_html, item)
        if not is_summarizable_detail(detail, detail_min_chars):
            if detail.content_kind in {"video", "external_video"}:
                raise UnsupportedContentError("unsupported video content")
            raise ValueError("detail content is empty or too short")

        if dry_run:
            return DetailFetchResult()

        assert notice_id is not None
        storage.save_detail(notice_id, detail)
        return DetailFetchResult(prepared=PreparedNotice(source=source, notice_id=notice_id, detail=detail))
    except Exception as exc:
        failure_type = classify_failure(exc, stage="detail")
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
            storage.mark_failed(
                notice_id,
                str(exc),
                failure_type=failure_type,
                retry_after_hours=retry_policy.after_hours,
                retry_limit=retry_policy.limit,
            )
        return DetailFetchResult(failure=failure)


def fetch_details_for_items(
    *,
    source: NoticeSource,
    adapter,
    items,
    dry_run: bool,
    failures: list[FailedNotice],
    storage,
    http_client,
    detail_min_chars: int,
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
                fetch_and_store_detail,
                source=source,
                adapter=adapter,
                item=item,
                dry_run=dry_run,
                retry_policy=retry_policy,
                storage=storage,
                http_client=http_client,
                detail_min_chars=detail_min_chars,
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
