from __future__ import annotations

from collections.abc import Callable, Iterable

from src.notice_push.models import NoticeSource, SourceAuditIssue, SourceAuditResult, SourceAuditSample


class SourceAuditor:
    def __init__(
        self,
        http_client,
        adapter_factory: Callable[[NoticeSource], object],
        min_list_items: int = 1,
        sample_detail_count: int = 1,
        required_content_kinds: tuple[str, ...] = ("text", "pdf", "image"),
    ):
        self.http_client = http_client
        self.adapter_factory = adapter_factory
        self.min_list_items = min_list_items
        self.sample_detail_count = max(1, sample_detail_count)
        self.required_content_kinds = set(required_content_kinds)

    def audit_source(self, source: NoticeSource) -> SourceAuditResult:
        adapter = self.adapter_factory(source)
        issues: list[SourceAuditIssue] = []
        try:
            list_html = self.http_client.get_text(source.list_url)
            items = adapter.parse_list_page(list_html, source.list_url)
        except Exception as exc:
            issue = SourceAuditIssue(
                source_id=source.id,
                source_name=source.name,
                url=source.list_url,
                severity="error",
                reason=str(exc),
            )
            return SourceAuditResult(
                source_id=source.id,
                source_name=source.name,
                list_url=source.list_url,
                list_item_count=0,
                issues=(issue,),
            )

        if len(items) < self.min_list_items:
            issues.append(
                SourceAuditIssue(
                    source_id=source.id,
                    source_name=source.name,
                    url=source.list_url,
                    severity="error",
                    reason=f"list page parsed {len(items)} items; expected at least {self.min_list_items}",
                )
            )

        samples: list[SourceAuditSample] = []
        sampled_items = items[: self.sample_detail_count]
        for sampled_item in sampled_items:
            try:
                detail_html = self.http_client.get_text(sampled_item.url)
                detail = adapter.parse_detail(detail_html, sampled_item)
                content_kind = detail.content_kind or "text"
                samples.append(
                    SourceAuditSample(
                        title=detail.title,
                        url=detail.url,
                        content_kind=content_kind,
                        content_length=len(detail.content.strip()),
                        asset_count=len(detail.assets),
                    )
                )
                if content_kind not in self.required_content_kinds and content_kind != "video":
                    issues.append(
                        SourceAuditIssue(
                            source_id=source.id,
                            source_name=source.name,
                            url=sampled_item.url,
                            severity="warning",
                            reason=f"sample detail content kind '{content_kind}' is not configured as expected",
                        )
                    )
            except Exception as exc:
                issues.append(
                    SourceAuditIssue(
                        source_id=source.id,
                        source_name=source.name,
                        url=sampled_item.url,
                        severity="warning",
                        reason=str(exc),
                    )
                )
        if sampled_items and not samples:
            issues.append(
                SourceAuditIssue(
                    source_id=source.id,
                    source_name=source.name,
                    url=source.list_url,
                    severity="error",
                    reason=f"all {len(sampled_items)} sampled detail pages failed",
                )
            )

        return SourceAuditResult(
            source_id=source.id,
            source_name=source.name,
            list_url=source.list_url,
            list_item_count=len(items),
            sampled_detail_url=samples[0].url if samples else "",
            detail_content_kind=samples[0].content_kind if samples else "",
            samples=tuple(samples),
            issues=tuple(issues),
        )

    def audit_sources(self, sources: Iterable[NoticeSource]) -> tuple[SourceAuditResult, ...]:
        return tuple(self.audit_source(source) for source in sources)
