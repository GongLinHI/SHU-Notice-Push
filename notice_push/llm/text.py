from __future__ import annotations

import os
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

from openai import OpenAI

from notice_push.llm.chat import create_chat_completion_with_retry
from notice_push.llm.prompts import load_prompt, render_notice_user_prompt
from notice_push.llm.repair import render_summary_repair_prompt
from notice_push.domain import NoticeDetail, NoticeSummary
from notice_push.summary_validator import normalize_summary_markdown, validate_summary_markdown


DEEPSEEK_BASE_URL = "https://api.deepseek.com"


class NoticeSummarizer:
    def __init__(
        self,
        prompt_dir: Path,
        prompt_name: str,
        model: str,
        api_key: Optional[str] = None,
        base_url: str = DEEPSEEK_BASE_URL,
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
        self._client = client
        self.timeout = timeout
        self.max_retries = max(1, max_retries)
        self.initial_retry_delay = max(0.0, initial_retry_delay)
        self.retry_backoff = max(1.0, retry_backoff)
        self.summary_format_repair_retries = max(0, summary_format_repair_retries)
        self._system_prompt: Optional[str] = None

    def summarize(self, notice_id: int, detail: NoticeDetail, source_name: Optional[str] = None) -> NoticeSummary:
        if not detail.content.strip():
            raise ValueError("detail content is required for summarization")

        system_prompt = self._get_system_prompt()
        user_prompt = self.render_user_prompt(detail, source_name=source_name)
        content = self._chat(system_prompt, user_prompt)
        content = self._normalize_validate_or_repair(content, system_prompt, user_prompt)

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

    def _normalize_validate_or_repair(self, content: str, system_prompt: str, user_prompt: str) -> str:
        normalized = normalize_summary_markdown(content)
        try:
            validate_summary_markdown(normalized)
            return normalized
        except ValueError as original_error:
            last_error = original_error

        for _ in range(self.summary_format_repair_retries):
            repair_prompt = render_summary_repair_prompt(user_prompt, normalized)
            normalized = normalize_summary_markdown(self._chat(system_prompt, repair_prompt))
            try:
                validate_summary_markdown(normalized)
                return normalized
            except ValueError as exc:
                last_error = exc
        raise last_error

    def _get_system_prompt(self) -> str:
        if self._system_prompt is None:
            self._system_prompt = load_prompt(self.prompt_dir, self.prompt_name)
        return self._system_prompt

    def _get_client(self):
        if self._client is not None:
            return self._client

        api_key = self.api_key or os.getenv("DEEPSEEK_API_KEY")
        if not api_key:
            raise ValueError("DEEPSEEK_API_KEY must be provided for real summarization")
        self._client = OpenAI(api_key=api_key, base_url=self.base_url)
        return self._client
