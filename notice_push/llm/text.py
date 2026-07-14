from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

from notice_push.llm.chat import create_chat_completion_with_retry
from notice_push.llm.client_factory import OpenAIClientProvider
from notice_push.llm.prompts import CachedPrompt, render_notice_user_prompt
from notice_push.llm.summary_format import SummaryFormatProcessor
from notice_push.domain import NoticeDetail, NoticeSummary


class NoticeSummarizer:
    def __init__(
        self,
        prompt_dir: Path,
        prompt_name: str,
        model: str,
        api_key: Optional[str] = None,
        base_url: Optional[str] = None,
        provider_name: str = "text",
        client=None,
        timeout: int = 60,
        max_retries: int = 2,
        initial_retry_delay: float = 0.5,
        retry_backoff: float = 2.0,
        summary_format_repair_retries: int = 1,
    ):
        self.prompt_dir = Path(prompt_dir)
        self.prompt_name = prompt_name
        self.model = model
        self.api_key = api_key
        self.base_url = base_url
        self.provider_name = provider_name
        self._client_provider = OpenAIClientProvider(
            client=client,
            api_key=api_key,
            base_url=base_url,
            provider_name=provider_name,
        )
        self.timeout = timeout
        self.max_retries = max(1, max_retries)
        self.initial_retry_delay = max(0.0, initial_retry_delay)
        self.retry_backoff = max(1.0, retry_backoff)
        self._format_processor = SummaryFormatProcessor(summary_format_repair_retries)
        self._system_prompt = CachedPrompt(self.prompt_dir, self.prompt_name)

    def summarize(self, notice_id: int, detail: NoticeDetail, source_name: Optional[str] = None) -> NoticeSummary:
        if not detail.content.strip():
            raise ValueError("detail content is required for summarization")

        system_prompt = self._get_system_prompt()
        user_prompt = self.render_user_prompt(detail, source_name=source_name)
        content = self._chat(system_prompt, user_prompt)
        content = self._format_processor.normalize_validate_or_repair(
            content,
            source_detail=detail,
            source_name=source_name,
            chat_for_repair=lambda repair_prompt: self._chat(system_prompt, repair_prompt),
        )

        return NoticeSummary(
            notice_id=notice_id,
            markdown=content,
            model=self.model,
            prompt_version=self.prompt_name,
            generated_at=datetime.now(timezone.utc).replace(microsecond=0),
        )

    def render_user_prompt(self, detail: NoticeDetail, source_name: Optional[str] = None) -> str:
        return render_notice_user_prompt(detail, source_name=source_name)

    def _chat(self, system_prompt: str, user_prompt: str) -> str:
        return create_chat_completion_with_retry(
            self._get_client(),
            model=self.model,
            messages=[
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": user_prompt},
            ],
            timeout=self.timeout,
            max_retries=self.max_retries,
            initial_retry_delay=self.initial_retry_delay,
            retry_backoff=self.retry_backoff,
        )

    def _get_system_prompt(self) -> str:
        return self._system_prompt.get()

    def _get_client(self):
        return self._client_provider.get()
