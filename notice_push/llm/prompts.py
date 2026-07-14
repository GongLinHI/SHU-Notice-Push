from __future__ import annotations

from pathlib import Path
import threading
from typing import Optional

from notice_push.domain import NoticeDetail
from notice_push.reporting.resources import visible_notice_resources


class CachedPrompt:
    def __init__(self, prompt_dir: Path, prompt_name: str):
        self.prompt_dir = Path(prompt_dir)
        self.prompt_name = prompt_name
        self._content: str | None = None
        self._lock = threading.Lock()

    def get(self) -> str:
        if self._content is not None:
            return self._content
        with self._lock:
            if self._content is None:
                self._content = load_prompt(self.prompt_dir, self.prompt_name)
        return self._content


def load_prompt(prompt_dir: Path, prompt_name: str) -> str:
    path = Path(prompt_dir) / f"{prompt_name}.md"
    if not path.exists():
        raise FileNotFoundError(f"Prompt file not found: {path}")
    return path.read_text(encoding="utf-8")


def render_notice_user_prompt(
    detail: NoticeDetail,
    source_name: Optional[str] = None,
    content: Optional[str] = None,
) -> str:
    resources = visible_notice_resources(detail)
    attachments = "\n".join(f"- {name}: {url}" for name, url in resources) or "未提及"
    published_at = detail.published_at.isoformat(sep=" ") if detail.published_at else "未提及"
    body = detail.content if content is None else content
    return (
        f"- 来源：{source_name or detail.source_id}\n"
        f"- 标题：{detail.title}\n"
        f"- 发布时间：{published_at}\n"
        f"- url：{detail.url}\n"
        f"- 附件：\n{attachments}\n"
        f"- 目录页摘要（仅供参考，不可替代正文）：{detail.list_excerpt or '未提及'}\n"
        f"- 正文：{body}\n"
    )
