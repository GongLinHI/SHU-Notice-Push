from __future__ import annotations

import os
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

from openai import OpenAI

from src.notice_push.models import NoticeDetail, NoticeSummary


DEEPSEEK_BASE_URL = "https://api.deepseek.com"


def load_prompt(prompt_dir: Path, prompt_name: str) -> str:
    path = Path(prompt_dir) / f"{prompt_name}.md"
    if not path.exists():
        raise FileNotFoundError(f"Prompt file not found: {path}")
    return path.read_text(encoding="utf-8")


class NoticeSummarizer:
    def __init__(
        self,
        prompt_dir: Path,
        prompt_name: str,
        model: str,
        api_key: Optional[str] = None,
        client=None,
        max_retries: int = 2,
    ):
        self.prompt_dir = Path(prompt_dir)
        self.prompt_name = prompt_name
        self.model = model
        self.api_key = api_key
        self._client = client
        self.max_retries = max(1, max_retries)

    def summarize(self, notice_id: int, detail: NoticeDetail, source_name: Optional[str] = None) -> NoticeSummary:
        if not detail.content.strip():
            raise ValueError("detail content is required for summarization")

        system_prompt = load_prompt(self.prompt_dir, self.prompt_name)
        user_prompt = self.render_user_prompt(detail, source_name=source_name)
        content = self._chat(system_prompt, user_prompt)

        return NoticeSummary(
            notice_id=notice_id,
            markdown=content,
            model=self.model,
            prompt_version=self.prompt_name,
            generated_at=datetime.now(timezone.utc).replace(microsecond=0),
        )

    def render_user_prompt(self, detail: NoticeDetail, source_name: Optional[str] = None) -> str:
        attachments = "\n".join(f"- {item.name}: {item.url}" for item in detail.attachments) or "未提及"
        published_at = detail.published_at.isoformat(sep=" ") if detail.published_at else "未提及"
        return (
            f"- 来源：{source_name or detail.source_id}\n"
            f"- 标题：{detail.title}\n"
            f"- 发布时间：{published_at}\n"
            f"- url：{detail.url}\n"
            f"- 附件：\n{attachments}\n"
            f"- 目录页摘要（仅供参考，不可替代正文）：{detail.list_excerpt or '未提及'}\n"
            f"- 正文：{detail.content}\n"
        )

    def _chat(self, system_prompt: str, user_prompt: str) -> str:
        last_error: Optional[Exception] = None
        for _ in range(self.max_retries):
            try:
                response = self._get_client().chat.completions.create(
                    model=self.model,
                    messages=[
                        {"role": "system", "content": system_prompt},
                        {"role": "user", "content": user_prompt},
                    ],
                    stream=False,
                )
                return response.choices[0].message.content
            except Exception as exc:
                last_error = exc
        raise last_error  # type: ignore[misc]

    def _get_client(self):
        if self._client is not None:
            return self._client

        api_key = self.api_key or os.getenv("DEEPSEEK_API_KEY")
        if not api_key:
            raise ValueError("DEEPSEEK_API_KEY must be provided for real summarization")
        self._client = OpenAI(api_key=api_key, base_url=DEEPSEEK_BASE_URL)
        return self._client
