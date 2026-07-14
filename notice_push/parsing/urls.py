from __future__ import annotations

from pathlib import PurePosixPath
from urllib.parse import urljoin, urlparse

from notice_push.parsing.content import DEFAULT_PARSING_RULES, ParsingRules


def absolute_url(href: str, base_url: str) -> str:
    return urljoin(base_url, href.strip())


def filename_from_url(url: str) -> str:
    return PurePosixPath(urlparse(url).path).name


def is_external_video_url(url: str, rules: ParsingRules = DEFAULT_PARSING_RULES) -> bool:
    hostname = (urlparse(url).hostname or "").lower()
    return any(
        hostname == domain or hostname.endswith(f".{domain}")
        for domain in rules.external_video_domains
    )


def is_external_video_page(url: str, rules: ParsingRules = DEFAULT_PARSING_RULES) -> bool:
    return is_external_video_url(url, rules)
