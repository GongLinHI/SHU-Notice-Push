from __future__ import annotations

from collections.abc import Callable

from notice_push.domain import NoticeDetail
from notice_push.llm.prompts import render_notice_user_prompt
from notice_push.llm.repair import render_summary_repair_prompt
from notice_push.summary_validator import normalize_summary_markdown, validate_summary_markdown


class SummaryFormatProcessor:
    def __init__(self, repair_retries: int):
        self.repair_retries = max(0, repair_retries)

    def normalize_validate_or_repair(
        self,
        markdown: str,
        *,
        source_detail: NoticeDetail,
        source_name: str | None,
        chat_for_repair: Callable[[str], str],
    ) -> str:
        normalized = normalize_summary_markdown(markdown)
        try:
            validate_summary_markdown(normalized)
            return normalized
        except ValueError as original_error:
            last_error = original_error

        original_prompt = render_notice_user_prompt(source_detail, source_name=source_name)
        for _ in range(self.repair_retries):
            repair_prompt = render_summary_repair_prompt(original_prompt, normalized)
            normalized = normalize_summary_markdown(chat_for_repair(repair_prompt))
            try:
                validate_summary_markdown(normalized)
                return normalized
            except ValueError as exc:
                last_error = exc
        raise last_error
