from __future__ import annotations

from typing import Optional

from notice_push.domain import NoticeDetail, NoticeSummary


class SummarizerRouter:
    def __init__(self, provider_summarizers: dict[str, object], routing: dict[str, str]):
        self.routing = dict(routing)
        self.provider_summarizers = dict(provider_summarizers)

    def summarize(self, notice_id: int, detail: NoticeDetail, source_name: Optional[str] = None) -> NoticeSummary:
        content_kind = detail.content_kind or "text"
        provider_name = self.routing.get(content_kind)
        if not provider_name:
            raise ValueError(f"unsupported content kind: {content_kind}")
        summarizer = self.provider_summarizers.get(provider_name)
        if summarizer is None:
            raise ValueError(f"no summarizer configured for provider: {provider_name}")
        return summarizer.summarize(notice_id, detail, source_name=source_name)
