from __future__ import annotations

import re


REQUIRED_SUMMARY_FIELDS = ("发布时间", "影响对象", "核心信息", "行动指引", "截止时间", "相关链接")


def normalize_summary_markdown(markdown: str) -> str:
    for field in REQUIRED_SUMMARY_FIELDS:
        markdown = re.sub(
            rf"\*\*{field}[：:]\*\*\s*",
            f"**{field}**: ",
            markdown,
        )
    return markdown


def validate_summary_markdown(markdown: str) -> None:
    if not markdown.strip().startswith("## "):
        raise ValueError("summary must start with a level-2 heading")
    for field in REQUIRED_SUMMARY_FIELDS:
        if f"**{field}**" not in markdown:
            raise ValueError(f"summary missing required field: {field}")
